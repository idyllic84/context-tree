"""Recall candidate nodes and fetch their evidence from a read-only index."""
from ...common import llm as copilot_api
from ...common.vectors import _cosine, _load_emb
from ...common.scope import _project_session_filter

def _flat_node_recall(conn, utterance: str, top_n: int = 10,
                       min_score: float = 0.30,
                       project_path: str | None = None,
                       query_embedding: list[float] | None = None,
                       allowed_sessions: set[str] | None = None) -> list[dict]:
    """Dense recall; optional shared query embedding avoids duplicate API calls."""
    scope = _project_session_filter(conn, project_path)
    if scope is not None:
        allowed_sessions = scope if allowed_sessions is None else scope & allowed_sessions
    if allowed_sessions == set() or top_n <= 0:
        return []
    qe = query_embedding if query_embedding is not None else copilot_api.embeddings([utterance])[0]
    goal_rows = conn.execute(
        "SELECT session_id, goal_id, intent, last_at, embedding FROM goal_index"
    ).fetchall()
    task_rows = conn.execute(
        "SELECT session_id, task_id, parent_goal_id, name, last_at, embedding FROM task_index"
    ).fetchall()

    nodes = []
    for r in goal_rows:
        if allowed_sessions is not None and r[0] not in allowed_sessions: continue
        if not r[4]: continue
        emb = _load_emb(r[4])
        nodes.append({"kind": "goal", "session_id": r[0], "node_id": r[1],
                      "parent_goal_id": r[1], "text": r[2], "last_at": r[3] or "",
                      "sim": _cosine(qe, emb), "_emb": emb})
    for r in task_rows:
        if allowed_sessions is not None and r[0] not in allowed_sessions: continue
        if not r[5]: continue
        emb = _load_emb(r[5])
        nodes.append({"kind": "task", "session_id": r[0], "node_id": r[1],
                      "parent_goal_id": r[2], "text": r[3], "last_at": r[4] or "",
                      "sim": _cosine(qe, emb), "_emb": emb})
    nodes.sort(key=lambda n: -n["sim"])
    return [n for n in nodes if n["sim"] >= min_score][:top_n]


def _fetch_task_evidence(conn, session_id: str, task_id: str,
                          include_agent_content: bool, include_files: bool,
                          ac_per_task: int = 5) -> dict:
    """For a task: pull agent_content rows + file/directory edges.

    Returned files entries: {file_id, kind: "file"|"directory", relations: [...]}.
    Directory entries are folded multi-file edges (≥3 files in same dir at write
    time per tree_to_entities.DIR_FOLD_THRESHOLD).

    Stage 17 adaptation: file edges are now per-turn anchored (each turn's ac
    owns only that turn's files), so the file-touching ac may not be in the
    confidence top-K. We sample top-K ONLY for agent_content text display, but
    scan ALL ac of this task for file edges (cost is bounded — task has tens
    of ac at most, file edges deduped by file_id at the end).
    """
    out = {"agent_content": [], "files": []}
    if not include_agent_content and not include_files:
        return out
    sess_prefix = session_id

    if include_agent_content:
        ac_rows_topk = conn.execute(
            "SELECT id, title, content, json_extract(metadata,'$.subtype'), confidence "
            "FROM nodes WHERE type='agent_content' "
            "AND json_extract(metadata,'$.source_task_id')=? "
            "AND json_extract(metadata,'$.session') = ? "
            "ORDER BY confidence DESC NULLS LAST LIMIT ?",
            (task_id, sess_prefix, ac_per_task * 2)
        ).fetchall()
        out["agent_content"] = [
            {"id": r[0], "title": r[1], "content": (r[2] or "")[:500],
             "subtype": r[3], "confidence": r[4]}
            for r in ac_rows_topk[:ac_per_task]
        ]

    if include_files:
        # Scan ALL ac for this task (per-turn anchoring spreads file edges thin).
        all_ac_ids = [r[0] for r in conn.execute(
            "SELECT id FROM nodes WHERE type='agent_content' "
            "AND json_extract(metadata,'$.source_task_id')=? "
            "AND json_extract(metadata,'$.session') = ?",
            (task_id, sess_prefix)
        ).fetchall()]

        seen: dict[str, dict] = {}
        for ac_id in all_ac_ids:
            for er in conn.execute(
                "SELECT e.target_id, e.relation, n.type FROM edges e "
                "LEFT JOIN nodes n ON n.id = e.target_id "
                "WHERE e.source_id = ? AND n.type IN ('file', 'directory')",
                (ac_id,)
            ).fetchall():
                fid, rel, ntype = er[0], er[1], er[2]
                if fid not in seen:
                    seen[fid] = {"file_id": fid, "kind": ntype, "relations": set()}
                seen[fid]["relations"].add(rel)
        # Sort: directories first (folded modules — higher signal density)
        out["files"] = sorted(
            ({"file_id": v["file_id"], "kind": v["kind"],
              "relations": sorted(v["relations"])} for v in seen.values()),
            key=lambda v: (0 if v["kind"] == "directory" else 1, v["file_id"]),
        )
    return out


def _search_file_entities(conn, pattern: str, limit: int = 8,
                          allowed_sessions: set[str] | None = None) -> list[dict]:
    """SQL fuzzy match on file/directory entity titles. Returns matches with
    related tasks (which agent_content edges to them).

    Pattern: substring match (auto-wrapped with %). Case-sensitive.
    Used by branch retrieval `search_file` action when query mentions a
    specific file/path that cosine recall can't surface (path tokens don't
    semantically embed well).
    """
    if not pattern or len(pattern) < 2 or limit <= 0 or allowed_sessions == set():
        return []
    rows = conn.execute(
        "SELECT id, type, title FROM nodes "
        "WHERE type IN ('file', 'directory') AND instr(title, ?) > 0 ORDER BY id",
        (pattern,))
    matches = []
    for fid, ftype, title in rows:
        # Walk back: find tasks whose ac edges to this file
        task_rows = conn.execute("""
            SELECT json_extract(ac.metadata,'$.session') AS sid,
                   json_extract(ac.metadata,'$.source_task_id') AS task_id,
                   e.relation
            FROM nodes ac JOIN edges e ON e.source_id = ac.id
            WHERE ac.type='agent_content' AND e.target_id = ?
            ORDER BY sid, task_id, e.relation
        """, (fid,)).fetchall()
        related = []
        seen_keys = set()
        for sid, tid, rel in task_rows:
            if not sid or not tid: continue
            if allowed_sessions is not None and sid not in allowed_sessions: continue
            key = (sid, tid)
            if key in seen_keys: continue
            seen_keys.add(key)
            name_row = conn.execute(
                "SELECT name FROM task_index WHERE session_id=? AND task_id=?",
                (sid, tid)
            ).fetchone()
            related.append({
                "session": sid, "task_id": tid,
                "name": (name_row[0] if name_row else tid)[:80],
                "relation": rel,
            })
            if len(related) >= 5: break
        if not related:
            continue
        matches.append({"path": title, "kind": ftype, "file_id": fid,
                        "related_tasks": related})
        if len(matches) >= limit:
            break
    return matches


def _walk_shared_file_tasks(conn, file_ids: list[str], exclude_task_ids: set,
                             limit: int = 5,
                             allowed_sessions: set[str] | None = None) -> list[dict]:
    """For given file/dir entity ids, find OTHER tasks (any session) whose
    agent_content edges to them. Used by branch retrieval's `expand files`
    auto walk-back: when a task touches a file, surface other tasks touching
    the same file so the LLM can chain (e.g., V3 design discussion → file →
    documentation maintenance task that authored the doc).

    Returns at most `limit` entries: [{session, task_id, name, file_id, relation}, ...].
    Deterministic SQL — no LLM in the loop.
    """
    if not file_ids or limit <= 0 or allowed_sessions == set():
        return []
    placeholders = ",".join("?" * len(file_ids))
    rows = conn.execute(f"""
        SELECT json_extract(ac.metadata,'$.session') AS sid,
               json_extract(ac.metadata,'$.source_task_id') AS task_id,
               e.target_id, e.relation
        FROM nodes ac JOIN edges e ON e.source_id = ac.id
        WHERE ac.type='agent_content'
          AND e.target_id IN ({placeholders})
        ORDER BY sid, task_id, e.target_id, e.relation
    """, file_ids).fetchall()

    results: list[dict] = []
    seen: set[tuple] = set()
    for r in rows:
        sid_full, tid, fid, rel = r
        if not sid_full or not tid: continue
        if allowed_sessions is not None and sid_full not in allowed_sessions: continue
        key = (sid_full, tid)
        if key in exclude_task_ids: continue
        if key in seen: continue
        seen.add(key)
        # Look up task name from task_index
        name_row = conn.execute(
            "SELECT name FROM task_index WHERE session_id=? AND task_id=?",
            (sid_full, tid)
        ).fetchone()
        results.append({
            "session": sid_full,
            "task_id": tid,
            "name": (name_row[0] if name_row else tid)[:80],
            "file_id": fid,
            "relation": rel,
        })
        if len(results) >= limit:
            break
    return results
