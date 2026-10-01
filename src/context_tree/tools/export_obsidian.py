"""Export companion-c db to an Obsidian vault for visualization.

Layout:
  vault/
    goals/<session_short>__<goal_id>__<slug>.md
    tasks/<session_short>__<task_id>__<slug>.md
    files/<file_slug>.md       # back-index: which tasks touched this file
    sessions/<session_short>.md # session overview

Wiki-links connect:
  goal → its tasks
  task → parent task + subtasks (recursive)
  task → file pages
  task ↔ task across sessions (same cluster — computed by embedding cosine on demand)

Open the vault in Obsidian, the graph view is the forest visualization.

Usage:
  python3 tools/export_obsidian.py --out ~/Desktop/companion-vault
  python3 tools/export_obsidian.py --out ./vault --db companion-c.db
"""
import sys, os, json, argparse, re, struct, sqlite3
from pathlib import Path


import context_tree.common.store as store
def slug(text: str, maxlen: int = 50) -> str:
    """Filesystem-safe slug from text."""
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", (text or "").lower())[:maxlen].strip("-")
    return s or "unnamed"


def short(sid: str) -> str:
    return slug(sid or "session", maxlen=80)


def node_key(sid: str, node_id: str, name: str) -> str:
    return f"{short(sid)}__{slug(node_id, 80)}__{slug(name)}"


def write_page(out_dir: Path, folder: str, filename: str, lines: list[str]):
    root = out_dir.resolve()
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if Path(filename).name != filename or not target.resolve().is_relative_to(root):
        raise ValueError("Export path escapes the selected vault")
    target.write_text("\n".join(lines), encoding="utf-8")


def load_emb(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))


def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = sum(x*x for x in a) ** 0.5
    nb = sum(x*x for x in b) ** 0.5
    return dot / (na * nb) if na * nb > 0 else 0.0


def export(out_dir: Path, db_name: str | None = None,
           similarity_threshold: float = 0.55):
    database = Path(db_name).expanduser().resolve() if db_name else store.DB_PATH
    if not database.is_file():
        raise FileNotFoundError(f"Database does not exist: {database}")
    print(f"db: {database}")

    out_dir = out_dir.expanduser().resolve()
    (out_dir / "goals").mkdir(parents=True, exist_ok=True)
    (out_dir / "tasks").mkdir(exist_ok=True)
    (out_dir / "files").mkdir(exist_ok=True)
    (out_dir / "sessions").mkdir(exist_ok=True)

    conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)

    # 1. Load all sessions (tree json)
    sessions = {}
    rows = conn.execute("SELECT session_id, task_tree_json FROM processing_state "
                         "WHERE task_tree_json IS NOT NULL").fetchall()
    for sid, tj in rows:
        try: sessions[sid] = json.loads(tj)
        except: continue
    print(f"sessions: {len(sessions)}")

    # 2. Build cross-session "see also" via task_index embeddings
    print("computing cross-session similarity edges...")
    task_rows = conn.execute(
        "SELECT session_id, task_id, name, embedding FROM task_index"
    ).fetchall()
    task_embs = []
    for r in task_rows:
        if r[3]:
            task_embs.append({
                "sid": r[0], "tid": r[1], "name": r[2], "emb": load_emb(r[3]),
                "node_key": node_key(r[0], r[1], r[2]),
            })
    similar_for: dict[str, list[tuple[float, str, str]]] = {}  # node_key → [(sim, other_key, other_name)]
    for i, a in enumerate(task_embs):
        for j, b in enumerate(task_embs):
            if i >= j: continue
            if a["sid"] == b["sid"]: continue  # only cross-session
            s = cosine(a["emb"], b["emb"])
            if s >= similarity_threshold:
                similar_for.setdefault(a["node_key"], []).append((s, b["node_key"], b["name"]))
                similar_for.setdefault(b["node_key"], []).append((s, a["node_key"], a["name"]))
    for k in similar_for:
        similar_for[k].sort(key=lambda x: -x[0])
        similar_for[k] = similar_for[k][:5]
    print(f"  {len(similar_for)} tasks have cross-session similar matches")

    # 3. Load file edges per task (via agent_content)
    print("indexing file edges...")
    file_to_tasks: dict[str, list[dict]] = {}  # file_path → [{sid, tid, task_name, relations}]
    task_to_files: dict[tuple[str, str], list[dict]] = {}  # (sid, tid) → [{path, relations}]
    file_rows = conn.execute("""
        SELECT json_extract(ac.metadata, '$.source_task_id') AS tid,
               json_extract(ac.metadata, '$.session') AS sess,
               e.target_id, e.relation
        FROM nodes ac JOIN edges e ON e.source_id = ac.id
        WHERE ac.type = 'agent_content'
    """).fetchall()
    seen_pair: dict[tuple, set] = {}
    for tid, sess, target, rel in file_rows:
        if not tid or not sess: continue
        path = target.split(":", 1)[-1] if ":" in target else target
        # Skip non-file targets
        if not path or "/" not in path: continue
        key = (sess, tid, path)
        seen_pair.setdefault(key, set()).add(rel)
    for (sess, tid, path), rels in seen_pair.items():
        rels_list = sorted(rels)
        task_to_files.setdefault((sess, tid), []).append({"path": path, "relations": rels_list})
        # Lookup task name from indexed tree
        tname = ""
        if sess in sessions:
            for g in sessions[sess].get("goals", []):
                tname = _find_task_name(g, tid) or tname
        file_to_tasks.setdefault(path, []).append({
            "sid": sess, "tid": tid, "name": tname, "relations": rels_list,
        })
    print(f"  {len(file_to_tasks)} files, {sum(len(v) for v in task_to_files.values())} task↔file edges")

    # Build task time map from task_index
    print("loading task time bounds...")
    task_times: dict[tuple[str, str], tuple[str, str]] = {}
    for r in conn.execute("SELECT session_id, task_id, first_at, last_at FROM task_index").fetchall():
        task_times[(r[0], r[1])] = (r[2] or "", r[3] or "")
    goal_times: dict[tuple[str, str], tuple[str, str]] = {}
    for r in conn.execute("SELECT session_id, goal_id, first_at, last_at FROM goal_index").fetchall():
        goal_times[(r[0], r[1])] = (r[2] or "", r[3] or "")

    # 5. Emit per-goal + per-task pages (with session metadata propagation)
    n_goals, n_tasks = 0, 0
    for sid, sess in sessions.items():
        branches_seen = {sig.split(":", 1)[1]
                         for turn in sess.get("turns", [])
                         for sig in turn.get("meta_signals", [])
                         if sig.startswith("branch_changed:")}
        sm = {
            "project_path": sess.get("project_path"),
            "display_name": sess.get("display_name"),
            "branches_seen": sorted(branches_seen) if branches_seen else None,
        }
        # Re-write session page with branches if found
        write_session_md(out_dir, sid, sess, branches=sm["branches_seen"])
        for g in sess.get("goals", []):
            write_goal_md(out_dir, sid, g, session_meta=sm, time_bounds=goal_times.get((sid, g['id']), ("", "")))
            n_goals += 1
            for t in g.get("tasks", []):
                write_task_md_recursive(out_dir, sid, g, t, parent_id=None,
                                        task_to_files=task_to_files,
                                        similar_for=similar_for,
                                        session_meta=sm,
                                        task_times=task_times)
                n_tasks += _count_tree(t)

    # 6. Emit file back-index
    for path, refs in file_to_tasks.items():
        write_file_md(out_dir, path, refs)

    # 7. Emit vault index
    write_index(out_dir, sessions, n_goals, n_tasks, len(file_to_tasks))
    conn.close()

    print(f"\n✅ vault written to {out_dir}")
    print(f"   {len(sessions)} sessions / {n_goals} goals / {n_tasks} tasks / {len(file_to_tasks)} files")
    print("   Open the output directory as an Obsidian vault.")


def _find_task_name(node: dict, target_tid: str) -> str | None:
    if node.get("id") == target_tid:
        return node.get("name") or node.get("intent")
    for s in (node.get("subtasks") or []) + (node.get("tasks") or []):
        r = _find_task_name(s, target_tid)
        if r: return r
    return None


def _count_tree(t: dict) -> int:
    n = 1
    for s in t.get("subtasks", []): n += _count_tree(s)
    return n


def write_session_md(out_dir: Path, sid: str, sess: dict, branches: list[str] | None = None):
    fname = f"{short(sid)}.md"
    n_g = len(sess.get("goals", []))
    n_t = sum(_count_tree(t) for g in sess.get("goals", []) for t in g.get("tasks", []))
    lines = [
        "---", f"session_id: {sid}", f"display: {sess.get('display_name', '')}",
        f"project: {sess.get('project_path', '')}",
    ]
    if branches:
        lines.append(f"branches: {','.join(branches)}")
    lines.extend(["---", "",
        f"# Session {short(sid)}", "", f"**{n_g} goals · {n_t} tasks**",
    ])
    if sess.get("project_path"):
        lines.append(f"_project_: `{sess['project_path']}`")
    if branches:
        lines.append(f"_branches seen_: {', '.join('`'+b+'`' for b in branches)}")
    lines.extend(["", "## Goals"])
    for g in sess.get("goals", []):
        link = node_key(sid, g['id'], g.get('intent', 'unnamed'))
        lines.append(f"- [[goals/{link}|{g['id']} {g.get('intent','')[:80]}]] [{g.get('status','')}]")
    write_page(out_dir, "sessions", fname, lines)


def write_goal_md(out_dir: Path, sid: str, g: dict, session_meta: dict | None = None,
                   time_bounds: tuple[str, str] = ("", "")):
    fname = node_key(sid, g['id'], g.get('intent', 'unnamed')) + '.md'
    first_at, last_at = time_bounds
    lines = [
        "---", f"type: goal", f"session: {sid}", f"goal_id: {g['id']}",
        f"status: {g.get('status','')}",
    ]
    if first_at: lines.append(f"first_at: {first_at}")
    if last_at: lines.append(f"last_at: {last_at}")
    lines.extend(["---", "",
        f"# {g['id']} {g.get('intent', '')}",
        f"_session_: [[sessions/{short(sid)}|{short(sid)}]]",
        f"_status_: **{g.get('status','')}**"
        + (f"  · _active_: {first_at} → {last_at}" if first_at else ""),
        "",
    ])
    if g.get("constraints"):
        lines.append("## Constraints")
        for c in g["constraints"]: lines.append(f"- {c}")
        lines.append("")
    if g.get("tasks"):
        lines.append("## Top-level tasks")
        for t in g["tasks"]:
            link = node_key(sid, t['id'], t.get('name', ''))
            lines.append(f"- [[tasks/{link}|{t['id']} {t.get('name','')[:70]}]] [{t.get('status','')}]")
    write_page(out_dir, "goals", fname, lines)


def write_task_md_recursive(out_dir, sid, g, t, parent_id, task_to_files, similar_for,
                              session_meta=None, task_times=None):
    fname = node_key(sid, t['id'], t.get('name', '')) + '.md'
    current_key = node_key(sid, t['id'], t.get('name', ''))
    goal_link = node_key(sid, g['id'], g.get('intent', 'unnamed'))
    first_at, last_at = (task_times or {}).get((sid, t['id']), ("", ""))
    lines = [
        "---", f"type: task", f"session: {sid}", f"goal_id: {g['id']}",
        f"task_id: {t['id']}", f"status: {t.get('status','')}",
        f"parent: {parent_id or g['id']}",
    ]
    if first_at: lines.append(f"first_at: {first_at}")
    if last_at: lines.append(f"last_at: {last_at}")
    lines.extend(["---", "",
        f"# {t['id']} {t.get('name', '')}",
        f"**status:** {t.get('status','')}"
        + (f"  · _active_: {first_at} → {last_at}" if first_at else ""),
        f"_session_: [[sessions/{short(sid)}|{short(sid)}]]",
        f"_goal_: [[goals/{goal_link}|{g.get('intent','')[:60]}]]",
    ])
    if parent_id:
        plink = node_key(sid, parent_id, _find_task_name(g, parent_id) or '')
        # parent name unknown here unless looked up; skip pretty title
        lines.append(f"_parent_: [[tasks/{plink}|{parent_id}]]")
    lines.append("")

    if t.get("outcome"):
        lines.append("## Outcome")
        lines.append(t["outcome"])
        lines.append("")
    if t.get("constraints") or t.get("soft_constraints"):
        lines.append("## Constraints")
        for c in t.get("constraints", []):
            lines.append(f"- (hard) {c}")
        for c in t.get("soft_constraints", []):
            lines.append(f"- (soft) {c}")
        lines.append("")
    if t.get("abandoned_alternatives"):
        lines.append("## Abandoned (don't repeat)")
        for ab in t["abandoned_alternatives"]:
            corr = ab.get("corrected_to") or ""
            lines.append(f"- ❌ {ab.get('approach','')[:120]}"
                         + (f" → ✓ {corr[:80]}" if corr else ""))
        lines.append("")
    if t.get("subtasks"):
        lines.append("## Subtasks")
        for st in t["subtasks"]:
            slink = node_key(sid, st['id'], st.get('name', ''))
            lines.append(f"- [[tasks/{slink}|{st['id']} {st.get('name','')[:70]}]] [{st.get('status','')}]")
        lines.append("")
    files = task_to_files.get((sid, t['id']), [])
    if files:
        lines.append("## Files")
        for f in files:
            slug_f = slug(f["path"].split("/")[-1])
            lines.append(f"- [[files/{slug_f}|{f['path'].split('/')[-1]}]] ({'+'.join(f['relations'])})")
        lines.append("")
    sims = similar_for.get(current_key, [])
    if sims:
        lines.append("## See also (cross-session similar)")
        for s, k, n in sims:
            lines.append(f"- [[tasks/{k}|{n[:70]}]] (sim={s:.2f})")
        lines.append("")

    write_page(out_dir, "tasks", fname, lines)

    # Recurse
    for st in t.get("subtasks", []):
        write_task_md_recursive(out_dir, sid, g, st, t['id'], task_to_files, similar_for,
                                  session_meta=session_meta, task_times=task_times)


def write_file_md(out_dir: Path, path: str, refs: list[dict]):
    fname = f"{slug(path.split('/')[-1])}.md"
    lines = [
        "---", f"type: file", f"path: {path}", "---", "",
        f"# {path.split('/')[-1]}",
        f"_path_: `{path}`", "",
        f"## Tasks that touched this ({len(refs)})", "",
    ]
    refs_sorted = sorted(refs, key=lambda r: r.get("name", ""))
    for r in refs_sorted:
        link = node_key(r['sid'], r['tid'], r.get('name', 'unnamed'))
        rels = "+".join(r["relations"])
        lines.append(f"- [[tasks/{link}|{short(r['sid'])}/{r['tid']} {r.get('name','')[:60]}]] ({rels})")
    write_page(out_dir, "files", fname, lines)


def write_index(out_dir: Path, sessions, n_goals, n_tasks, n_files):
    lines = [
        f"# Companion Vault",
        "",
        f"**{len(sessions)} sessions · {n_goals} goals · {n_tasks} tasks · {n_files} files**",
        "",
        "## Sessions",
    ]
    for sid, sess in sorted(sessions.items()):
        lines.append(f"- [[sessions/{short(sid)}|{short(sid)} — {sess.get('display_name','')}]]")
    lines.append("")
    lines.append("## How to explore")
    lines.append("- Open Graph view (left sidebar) to see the full forest")
    lines.append("- Click a session to see its goals; goal pages link to tasks")
    lines.append("- File pages list all tasks that touched a given file")
    lines.append("- Tasks have 'See also' for cross-session similar work")
    write_page(out_dir, "", "INDEX.md", lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--db", default=None, help="path to an existing database (read-only)")
    p.add_argument("--similarity", type=float, default=0.55,
                   help="cross-session 'see also' link threshold")
    args = p.parse_args()
    export(Path(args.out), db_name=args.db, similarity_threshold=args.similarity)


if __name__ == "__main__":
    main()
