"""Persist task embeddings and literal symbol occurrences."""
import json
import re
import sqlite3
import struct
from ...common import llm as copilot_api
from ...common.scope import _project_session_filter

def _ensure_indexes(conn):
    """Create goal_index / task_index tables if absent. Stores name+intent
    embeddings and time bounds for tree-match retrieval. ALTER for legacy DBs."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goal_index (
            session_id TEXT,
            goal_id TEXT,
            intent TEXT,
            status TEXT,
            task_count INTEGER,
            first_at TEXT,
            last_at TEXT,
            embedding BLOB,
            PRIMARY KEY (session_id, goal_id)
        )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS task_index (
            session_id TEXT,
            task_id TEXT,
            parent_goal_id TEXT,
            name TEXT,
            status TEXT,
            depth INTEGER,
            first_at TEXT,
            last_at TEXT,
            embedding BLOB,
            PRIMARY KEY (session_id, task_id)
        );
    """)
    for tbl in ("goal_index", "task_index"):
        for col in ("first_at", "last_at"):
            try: conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError: pass


_NAME = r"[A-Za-z_][A-Za-z0-9_]*"


_LITERAL_RE = re.compile(rf"(?<![A-Za-z0-9_]){_NAME}(?:\.{_NAME})*(?![A-Za-z0-9_])")


_PATH_RE = re.compile(r"(?<![\w])(?:[./~A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.[A-Za-z][A-Za-z0-9]*(?:/[A-Za-z0-9_./-]*)?")


def _identifier_occurrences(text: str) -> list[tuple[str, int, int]]:
    """Exact spellings and raw-text offsets; plain words require call/backticks."""
    quoted = [(m.start(1), m.end(1)) for m in re.finditer(r"`([^`\n]+)`", text)]
    found = set()
    for m in _LITERAL_RE.finditer(text):
        name = m.group()
        if ("_" in name or "." in name or re.search(r"[a-z][A-Z]|[A-Z]{2}[a-z]", name)
                or re.match(r"\s*\(", text[m.end():])
                or any(a <= m.start() and m.end() <= b for a, b in quoted)):
            found.add((name, m.start(), m.end()))
            # Qualified names retain the full spelling and literal components.
            if "." in name:
                for part in re.finditer(_NAME, name):
                    found.add((part.group(), m.start() + part.start(), m.start() + part.end()))
    for m in _PATH_RE.finditer(text):
        found.add((m.group(), m.start(), m.end()))
    return sorted(found, key=lambda x: (x[1], x[2], x[0]))


def _ensure_identifier_index(conn):
    # Do not commitscript here: indexing participates in the caller's transaction.
    conn.execute("""CREATE TABLE IF NOT EXISTS identifier_occurrences (
        session_id TEXT NOT NULL, project_path TEXT NOT NULL,
        turn_id INTEGER NOT NULL, speaker TEXT NOT NULL,
        identifier TEXT COLLATE BINARY NOT NULL,
        start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
        unit_id TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT '',
        snippet TEXT NOT NULL, timestamp TEXT NOT NULL,
        PRIMARY KEY (session_id, turn_id, speaker, start_offset, end_offset, unit_id, task_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS identifier_lookup ON identifier_occurrences(identifier, session_id)")


def index_identifiers(conn, session, replace: bool = True) -> int:
    """Index raw dialogue with existing, speaker-specific unit/task provenance.

    Accepts Session or its dictionary. Empty unit/task IDs mean unknown, never a
    fabricated task. Unit attribution is turn/speaker-level if extraction omitted
    the literal, narrowed to matching unit text when possible. No commit or API.
    """
    data = session.to_dict() if hasattr(session, "to_dict") else session
    sid = data["session_id"]
    _ensure_identifier_index(conn)
    unit_tasks = {}

    def walk(task):
        refs = set(task.get("linked_unit_ids") or [])
        if task.get("source_unit_id"):
            refs.add(task["source_unit_id"])
        for uid in refs:
            unit_tasks.setdefault(uid, set()).add(task["id"])
        for sub in task.get("subtasks", []):
            walk(sub)

    for goal in data.get("goals", []):
        for task in goal.get("tasks", []):
            walk(task)
    if replace:
        conn.execute("DELETE FROM identifier_occurrences WHERE session_id=?", (sid,))
    count = 0
    for turn in data.get("turns", []):
        for speaker in ("human", "agent"):
            raw = turn.get(speaker + "_raw") or ""
            units = [u for u in turn.get("units", []) if u.get("speaker") == speaker]
            for name, start, end in _identifier_occurrences(raw):
                exact = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
                matching = [u for u in units if exact.search(u.get("text", ""))]
                attributed = matching or (units if len(units) == 1 else [])
                for unit in attributed or [{"id": ""}]:
                    uid = unit["id"]
                    for tid in sorted(unit_tasks.get(uid) or {""}):
                        cur = conn.execute("""INSERT OR IGNORE INTO identifier_occurrences
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (sid, data.get("project_path") or "", turn["turn_id"], speaker,
                             name, start, end, uid, tid, raw[max(0, start-100):end+150],
                             turn.get("timestamp") or ""))
                        count += cur.rowcount
    return count


def backfill_identifiers(conn, project_path: str | None = None,
                         session_ids: set[str] | None = None, replace: bool = True) -> int:
    """Explicit offline backfill from processing_state; caller owns commit/sync."""
    allowed = _project_session_filter(conn, project_path)
    total = 0
    for sid, payload in conn.execute(
            "SELECT session_id, task_tree_json FROM processing_state WHERE task_tree_json IS NOT NULL"):
        if allowed is not None and sid not in allowed:
            continue
        if session_ids is not None and sid not in session_ids:
            continue
        try:
            session = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(session, dict):
            continue
        session["session_id"] = sid
        total += index_identifiers(conn, session, replace=replace)
    return total


def search_identifier(conn, identifier: str, limit: int = 20,
                      project_path: str | None = None,
                      allowed_sessions: set[str] | None = None) -> list[dict]:
    """Case-sensitive exact lookup; safe before explicit index/backfill setup."""
    scope = _project_session_filter(conn, project_path)
    if scope is not None:
        allowed_sessions = scope if allowed_sessions is None else scope & allowed_sessions
    if allowed_sessions == set() or not identifier or limit <= 0:
        return []
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='identifier_occurrences'").fetchone():
        return []
    rows = conn.execute("""SELECT session_id, turn_id, speaker, identifier,
        start_offset, end_offset, unit_id, task_id, snippet, timestamp
        FROM identifier_occurrences WHERE identifier = ? COLLATE BINARY
        ORDER BY timestamp DESC, session_id, turn_id, speaker, start_offset, unit_id, task_id""",
        (identifier,))
    out = []
    for row in rows:
        if allowed_sessions is not None and row[0] not in allowed_sessions:
            continue
        out.append(dict(zip(("session", "turn_id", "speaker", "identifier", "start_offset",
                             "end_offset", "unit_id", "task_id", "snippet", "timestamp"), row)))
        if len(out) >= limit:
            break
    return out


def _build_unit_ts_map(turns) -> dict[str, str]:
    """unit_id → date (YYYY-MM-DD) using parent turn's user-message timestamp."""
    m: dict[str, str] = {}
    for t in turns:
        ts = (t.timestamp or "")[:10]
        if not ts: continue
        for u in t.units:
            m[u.id] = ts
    return m


def _agg_time(unit_ids: list[str], ts_map: dict[str, str]) -> tuple[str, str]:
    """Returns (first_at, last_at) for a list of unit ids. Empty if none resolvable."""
    ts_list = sorted(ts_map[uid] for uid in unit_ids if uid in ts_map)
    if not ts_list: return ("", "")
    return (ts_list[0], ts_list[-1])


def index_session(conn, session_id: str, goals: list, turns: list = None) -> tuple[int, int]:
    """Populate goal_index + task_index for given session's goals.
    `turns` (optional, recommended): used to derive task/goal first_at/last_at
    from linked unit timestamps (date-level). Without it, time fields stay empty.
    Returns (n_goals, n_tasks) indexed."""
    _ensure_indexes(conn)
    conn.execute("DELETE FROM goal_index WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM task_index WHERE session_id = ?", (session_id,))

    ts_map = _build_unit_ts_map(turns or [])

    goal_texts = []
    goal_meta = []  # (id, intent, status, task_count, first_at, last_at)
    task_texts = []
    task_meta = []  # (id, parent_goal_id, name, status, depth, first_at, last_at)

    def walk_tasks(t, parent_goal_id, depth, goal_uids: list):
        first, last = _agg_time(t.linked_unit_ids, ts_map)
        task_texts.append(t.name)
        task_meta.append((t.id, parent_goal_id, t.name, t.status, depth, first, last))
        goal_uids.extend(t.linked_unit_ids)
        for s in t.subtasks:
            walk_tasks(s, parent_goal_id, depth+1, goal_uids)

    for g in goals:
        goal_texts.append(g.intent)
        n_tasks = 0
        def count(t):
            nonlocal n_tasks
            n_tasks += 1
            for s in t.subtasks: count(s)
        for t in g.tasks: count(t)

        goal_uids: list[str] = []
        for t in g.tasks:
            walk_tasks(t, g.id, 0, goal_uids)
        g_first, g_last = _agg_time(goal_uids, ts_map)
        goal_meta.append((g.id, g.intent, g.status, n_tasks, g_first, g_last))

    if goal_texts:
        goal_embs = copilot_api.embeddings(goal_texts)
        for (gid, intent, status, count, first, last), emb in zip(goal_meta, goal_embs):
            blob = struct.pack(f"{len(emb)}f", *emb)
            conn.execute(
                "INSERT INTO goal_index "
                "(session_id, goal_id, intent, status, task_count, first_at, last_at, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, gid, intent, status, count, first, last, blob))
    if task_texts:
        task_embs = copilot_api.embeddings(task_texts)
        for (tid, pgid, name, status, depth, first, last), emb in zip(task_meta, task_embs):
            blob = struct.pack(f"{len(emb)}f", *emb)
            conn.execute(
                "INSERT INTO task_index "
                "(session_id, task_id, parent_goal_id, name, status, depth, first_at, last_at, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, tid, pgid, name, status, depth, first, last, blob))
    return len(goal_texts), len(task_texts)
