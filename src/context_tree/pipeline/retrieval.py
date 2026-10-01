"""Query orchestration across recall, branch expansion, action selection and assembly."""
import json
from ..common import llm as copilot_api
from ..common.vectors import _cosine, _load_emb
from ..common.scope import _project_session_filter
from ..common.context_view import BRANCH_RETRIEVE_PROMPT, USER_VOICE, AGENT_VOICE, _parse_iter_action, _format_branched_state, format_branched_result
from ..stages.index.processor import _identifier_occurrences, _PATH_RE, search_identifier
from ..stages.recall.processor import _flat_node_recall, _search_file_entities, _fetch_task_evidence, _walk_shared_file_tasks
from ..stages.branches.processor import _natural_branches, _walk_ancestor_constraints, _branch_expand_node
from ..stages.context.processor import assemble_context, _finalize_branched
from ..stages.select.processor import select_action

def retrieve_branched(conn, utterance: str,
                      current_session_id: str | None = None,
                      project_path: str | None = None,
                      top_n_recall: int = 15,
                      max_iterations: int = 4,
                      model: str | None = None,
                      mode: str = "user",
                      verbose: int = 1) -> dict:
    """Branch-based retrieval. Returns list of candidate contexts (one per branch).

    `mode`: "user" (default, conversational answer-shaped output for human reader)
            or "agent" (terse tagged-facts for silent context injection into an
            AI coding agent's prompt). Only changes the LLM voice prompt and
            the renderer; the retrieval pipeline is identical.
    """
    import time as _t
    t_start = _t.time()
    timing = {}

    t0 = _t.time()
    allowed = _project_session_filter(conn, project_path)
    if allowed == set():
        return _finalize_branched([], [], set(), [], timing, 0, mode=mode)
    qe = copilot_api.embeddings([utterance])[0]
    candidates = _flat_node_recall(conn, utterance, top_n=top_n_recall,
                                   query_embedding=qe, allowed_sessions=allowed)
    if current_session_id:
        seen = {(c["session_id"], c["node_id"]) for c in candidates}
        rows = conn.execute(
            "SELECT session_id,task_id,name,last_at,embedding FROM task_index "
            "WHERE session_id LIKE ? ORDER BY last_at DESC LIMIT 4", (current_session_id + "%",))
        for sid, tid, name, last_at, blob in rows:
            if (sid, tid) in seen or (allowed is not None and sid not in allowed):
                continue
            candidates.append({"session_id": sid, "node_id": tid, "kind": "task", "text": name,
                               "sim": _cosine(qe, _load_emb(blob)) if blob else 0.0,
                               "last_at": last_at, "_injected": True})
    all_sessions = {}
    branches = []
    dropped = set()
    search_results = []

    def add_hits(hits):
        """Only candidate sessions are loaded; new hits create real tree branches."""
        lit = []
        seen = {(b["session_id"], m["node_id"]) for b in branches for m in b["lit_members"]}
        for hit in hits:
            sid = hit.get("session") or hit.get("session_id")
            tid = hit.get("task_id") or hit.get("node_id")
            if not sid or not tid or (allowed is not None and sid not in allowed):
                continue
            if (sid, tid) in seen:
                continue
            seen.add((sid, tid))
            if sid not in all_sessions:
                row = conn.execute("SELECT task_tree_json FROM processing_state WHERE session_id=?", (sid,)).fetchone()
                try:
                    tree = json.loads(row[0]) if row else None
                except (ValueError, TypeError):
                    tree = None
                all_sessions[sid] = tree if isinstance(tree, dict) else {}
            lit.append({"session_id": sid, "node_id": tid,
                        "kind": hit.get("kind", "task"),
                        "text": hit.get("text") or hit.get("name") or tid,
                        "sim": hit.get("sim", 1.0)})
        existing = {b["branch_id"]: b for b in branches}
        for branch in _natural_branches(lit, all_sessions, conn=conn):
            bid = branch["branch_id"]
            if bid in dropped:
                continue
            if bid not in existing:
                branches.append(branch)
                existing[bid] = branch
            else:
                old = existing[bid]
                old["lit_members"].extend(branch["lit_members"])
                old["lit_count"] = len(old["lit_members"])
                old["max_sim"] = max(old["max_sim"], branch["max_sim"])
                existing_nodes = {n["id"] for n in old["nodes"]}
                old["nodes"].extend(n for n in branch["nodes"] if n["id"] not in existing_nodes)

    def search(kind, pattern):
        if kind == "search_identifier":
            matches = search_identifier(conn, pattern, allowed_sessions=allowed)
            add_hits(matches)
        else:
            matches = _search_file_entities(conn, pattern, allowed_sessions=allowed)
            add_hits([t for m in matches for t in m["related_tasks"]])
        search_results.append({"type": kind, "pattern": pattern, "matches": matches})
        return len(matches)

    add_hits(candidates)
    for name in dict.fromkeys(x[0] for x in _identifier_occurrences(utterance)):
        search("search_identifier", name)
    for path in dict.fromkeys(m.group() for m in _PATH_RE.finditer(utterance)):
        search("search_file", path)
    timing["recall_ms"] = int((_t.time() - t0) * 1000)
    t0 = _t.time()
    # Auto-prefetch lit-node evidence + files (Stage 17 retrieval optim).
    # Saves 1-2 LLM round-trips per query: LLM sees content of lit nodes
    # immediately instead of spending iterations on basic discovery.
    # Cost: ~50-100ms SQL × N lit (typically <1.5s total).
    for b in branches:
        for m in b.get("lit_members", []):
            if m.get("kind") != "task":
                continue
            tid = m["node_id"]
            if tid in b["_expanded_data"]:
                continue
            ev = _fetch_task_evidence(conn, b["session_id"], tid,
                                       include_agent_content=True, include_files=True)
            slot = b["_expanded_data"].setdefault(tid, {})
            if ev["agent_content"]:
                slot["evidence"] = ev["agent_content"]
                b["_expanded"].setdefault(tid, set()).add("evidence")
            if ev["files"]:
                slot["files"] = ev["files"]
                b["_expanded"].setdefault(tid, set()).add("files")
                # Auto walk-back (Option C): expose tasks sharing the same files.
                shared = _walk_shared_file_tasks(
                    conn, [f["file_id"] for f in ev["files"]],
                    exclude_task_ids={(b["session_id"], tid)}, limit=5,
                    allowed_sessions=allowed)
                if shared:
                    slot["shared_file_tasks"] = shared
            # Ancestor constraints (tree inheritance — constraint at goal/task X
            # applies to all descendants). Auto-load so LLM sees full applicable
            # rule set without extra expand round.
            anc_constraints = _walk_ancestor_constraints(b, tid)
            if anc_constraints:
                slot["constraints"] = anc_constraints
                b["_expanded"].setdefault(tid, set()).add("constraints")
    timing["branch_ms"] = int((_t.time() - t0) * 1000)
    if verbose >= 1:
        print(f"   [branched] {len(candidates)} lit → {len(branches)} branches")
        for b in branches[:8]:
            print(f"     branch {b['branch_id'][:30]} lit={b['lit_count']} max_sim={b['max_sim']:.2f} {b['anchor_name'][:40]}")

    actions_log: list[str] = []

    def finish(candidates, iterations, all_active=False):
        selected_ids = {bid for candidate in candidates if isinstance(candidate, dict)
                        for bid in candidate.get("branch_ids", []) if isinstance(bid, str)}
        selected = [branch for branch in branches if branch["branch_id"] not in dropped
                    and (all_active or branch["branch_id"] in selected_ids)]
        error = None
        final_candidates = []
        if selected:
            started = _t.time()
            try:
                final_candidates = assemble_context(utterance, current_session_id, selected,
                                                    model=model, mode=mode,
                                                    search_results=search_results)
            except Exception as exc:
                error = str(exc)
            timing["context_ms"] = int((_t.time() - started) * 1000)
        timing["total_ms"] = int((_t.time() - t_start) * 1000)
        result = _finalize_branched(final_candidates, selected, set(), actions_log,
                                    timing, iterations, mode=mode)
        if error:
            result["error"] = error
        return result

    for it in range(max_iterations):
        active_branches = [b for b in branches if b["branch_id"] not in dropped]
        t0 = _t.time()
        try:
            action = select_action(utterance, active_branches, current_session_id=current_session_id,
                                   history=actions_log, search_results=search_results, model=model, mode=mode)
        except Exception as e:
            if verbose >= 1: print(f"   [iter#{it}] llm err: {str(e)[:80]}")
            return {"candidates": [], "branches": branches, "iterations": it,
                    "actions": actions_log, "elapsed": timing,
                    "error": str(e)}
        timing[f"iter{it}_ms"] = int((_t.time() - t0) * 1000)
        if action is None:
            actions_log.append(f"iter{it}: PARSE_FAIL")
            if verbose >= 1: print(f"   [iter#{it}] parse fail")
            continue
        # Defensive: LLM may emit list of actions; take first
        if isinstance(action, list):
            action = action[0] if action else {}
        if not isinstance(action, dict):
            actions_log.append(f"iter{it}: bad action shape: {type(action).__name__}")
            continue

        # Normalize legacy single actions into the same ordered batch path.
        single = action.get("action")
        if single:
            action = ({"done": True, "candidates": action.get("candidates", [])}
                      if single == "done" else {single: [action]})
        # Batch-mode detection: if no top-level "action" key but has "done"
        # or "expand"/"drop" lists → apply all ops in this iteration.
        # (Saves LLM round-trips when LLM wants to expand/drop several at once.)
        is_batch = "action" not in action and (
            "done" in action or "expand" in action or "drop" in action
            or "search_file" in action or "search_identifier" in action)
        if is_batch:
            ops_applied = 0
            needs_observation = False
            MAX_OPS = 8
            # Drops first
            for d in (action.get("drop") or [])[:MAX_OPS]:
                if not isinstance(d, dict): continue
                bid = d.get("branch_id"); reason = d.get("reason", "")
                if isinstance(bid, str) and any(b["branch_id"] == bid for b in branches):
                    dropped.add(bid); ops_applied += 1
                    actions_log.append(f"iter{it}: drop {bid} — {reason[:60]}")
                    if verbose >= 1: print(f"   [iter#{it}] drop {bid[:30]}: {reason[:60]}")
            for kind in ("search_file", "search_identifier"):
                for sf in (action.get(kind) or [])[:MAX_OPS]:
                    if not isinstance(sf, dict): continue
                    pattern = sf.get("identifier") or sf.get("pattern", "")
                    if not isinstance(pattern, str): continue
                    count = search(kind, pattern)
                    ops_applied += 1
                    needs_observation = True
                    actions_log.append(f"iter{it}: {kind} '{pattern}' -> {count} matches")
            # Then expands
            for e in (action.get("expand") or [])[:MAX_OPS]:
                if not isinstance(e, dict): continue
                bid = e.get("branch_id"); tgt = e.get("target"); et = e.get("type")
                branch = next((b for b in branches if b["branch_id"] == bid), None)
                if not branch or bid in dropped:
                    actions_log.append(f"iter{it}: expand FAIL — branch {bid} unavailable")
                    continue
                msg = _branch_expand_node(branch, tgt, et, conn, allowed_sessions=allowed)
                for fields in branch["_expanded_data"].values():
                    add_hits(fields.get("shared_file_tasks", []))
                    add_hits(fields.get("see_also", []))
                ops_applied += 1
                needs_observation = True
                actions_log.append(f"iter{it}: expand {bid}/{tgt}.{et} → {msg}")
                if verbose >= 1: print(f"   [iter#{it}] expand {bid[:24]}/{tgt}.{et} → {msg}")
            # Finally done with candidates if requested
            if action.get("done") and needs_observation:
                actions_log.append(f"iter{it}: done deferred until search/expand results are observed")
            if action.get("done") and not needs_observation:
                cands = action.get("candidates") or []
                actions_log.append(f"iter{it}: BATCH_DONE ({ops_applied} ops, {len(cands)} candidates)")
                if verbose >= 1: print(f"   [iter#{it}] DONE: {len(cands)} candidates ({ops_applied} ops)")
                return finish(cands, it + 1)
            if ops_applied == 0:
                actions_log.append(f"iter{it}: empty batch — forcing done")
                break
            continue

        actions_log.append(f"iter{it}: unknown action {single}")

    actions_log.append("max_iter: assemble from observed active branches")
    return finish([], max_iterations, all_active=True)
