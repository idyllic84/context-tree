"""SQLite knowledge graph store + embedding search."""

import json
import sqlite3
import struct
import os
import tempfile
from pathlib import Path

from context_tree.common.config import data_dir

BRAIN_DIR = data_dir()
DB_PATH = BRAIN_DIR / "context-tree.db"
CACHE_VERSION = 2


def configure_paths(db_path: str | None = None, cache_dir: str | None = None):
    global DB_PATH, CACHE_DIR, BRAIN_DIR
    BRAIN_DIR = data_dir()
    DB_PATH = Path(db_path).expanduser().resolve() if db_path else BRAIN_DIR / "context-tree.db"
    CACHE_DIR = (Path(cache_dir).expanduser().resolve() if cache_dir else
                 DB_PATH.parent / (DB_PATH.stem + "-cache" if db_path else "cache"))


def connect() -> sqlite3.Connection:
    """Open or create the companion database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL,
            content TEXT, metadata TEXT, valid_from TEXT, invalid_from TEXT,
            embedding BLOB,
            confidence REAL DEFAULT 0.5,
            source_unit_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            expired_at TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL, target_id TEXT NOT NULL,
            relation TEXT NOT NULL, explanation TEXT,
            valid_from TEXT, invalid_from TEXT, session_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_id, target_id, relation)
        );
        CREATE TABLE IF NOT EXISTS processing_state (
            session_id TEXT PRIMARY KEY, session_path TEXT DEFAULT '',
            message_count INTEGER DEFAULT 0,
            processed_at TEXT DEFAULT (datetime('now')),
            task_tree_json TEXT
        );
    """)
    # Migrate older DBs: add columns if missing
    cols = {row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()}
    if "confidence" not in cols:
        conn.execute("ALTER TABLE nodes ADD COLUMN confidence REAL DEFAULT 0.5")
    if "source_unit_id" not in cols:
        conn.execute("ALTER TABLE nodes ADD COLUMN source_unit_id TEXT")
    if "expired_at" not in cols:
        conn.execute("ALTER TABLE nodes ADD COLUMN expired_at TEXT")
    pcols = {row[1] for row in conn.execute("PRAGMA table_info(processing_state)").fetchall()}
    if "last_processed_uuid" not in pcols:
        conn.execute("ALTER TABLE processing_state ADD COLUMN last_processed_uuid TEXT DEFAULT ''")
    if "schema_version" not in pcols:
        conn.execute("ALTER TABLE processing_state ADD COLUMN schema_version INTEGER DEFAULT 0")
    conn.commit()
    return conn


def slugify(title: str) -> str:
    slug = "-".join(
        "".join(c if c.isalnum() else "-" for c in title.lower()).split("-")
    )
    return slug[:80].strip("-") or "unknown"


# ─── Node CRUD ───

def upsert_node(conn, *, id: str, type: str, title: str, content: str = None,
                metadata: dict = None, valid_from: str = None,
                confidence: float | None = None, source_unit_id: str | None = None):
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    conf = confidence if confidence is not None else 0.5
    conn.execute(
        """INSERT INTO nodes (id, type, title, content, metadata, valid_from, confidence, source_unit_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             title = excluded.title,
             content = COALESCE(excluded.content, nodes.content),
             metadata = COALESCE(excluded.metadata, nodes.metadata),
             confidence = MAX(excluded.confidence, nodes.confidence),
             source_unit_id = COALESCE(excluded.source_unit_id, nodes.source_unit_id),
             updated_at = datetime('now')""",
        (id, type, title, content, meta_json, valid_from, conf, source_unit_id)
    )


def invalidate_node(conn, node_id: str, invalid_from: str | None = None):
    """Mark a node as expired (bi-temporal: invalid in real world + expired in system).

    Per spec §5: do NOT update content; only set invalid_from + expired_at to now.
    The new replacement node should be inserted separately and linked via
    superseded_by edge.
    """
    invalid_from = invalid_from or "datetime('now')"
    if invalid_from == "datetime('now')":
        conn.execute(
            "UPDATE nodes SET invalid_from = datetime('now'), expired_at = datetime('now') WHERE id = ? AND expired_at IS NULL",
            (node_id,)
        )
    else:
        conn.execute(
            "UPDATE nodes SET invalid_from = ?, expired_at = datetime('now') WHERE id = ? AND expired_at IS NULL",
            (invalid_from, node_id)
        )


def query_at(conn, point_in_time: str | None = None) -> list[dict]:
    """Return nodes that the system considered valid at `point_in_time` (ingestion time).

    point_in_time format: ISO 8601 ("2026-04-15" or "2026-04-15T12:00:00").
    None → current snapshot (everything not yet expired).
    """
    if point_in_time is None:
        rows = conn.execute(
            "SELECT id, type, title, content, confidence, valid_from, invalid_from "
            "FROM nodes WHERE expired_at IS NULL "
            "AND type NOT IN ('session', 'file', 'directory') ORDER BY confidence DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, type, title, content, confidence, valid_from, invalid_from "
            "FROM nodes WHERE created_at <= ? AND (expired_at IS NULL OR expired_at > ?) "
            "AND type NOT IN ('session', 'file', 'directory') ORDER BY confidence DESC",
            (point_in_time, point_in_time)
        ).fetchall()
    return [{"id": r[0], "type": r[1], "title": r[2], "content": r[3],
             "confidence": r[4], "valid_from": r[5], "invalid_from": r[6]}
            for r in rows]


def upsert_edge(conn, *, source_id: str, target_id: str, relation: str,
                explanation: str = None, valid_from: str = None, session_id: str = None):
    try:
        conn.execute(
            """INSERT INTO edges (source_id, target_id, relation, explanation, valid_from, session_id)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                 explanation = COALESCE(excluded.explanation, edges.explanation)""",
            (source_id, target_id, relation, explanation, valid_from, session_id)
        )
    except sqlite3.IntegrityError:
        pass  # FK constraint — skip silently


def get_node(conn, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, type, title, content, metadata, valid_from, invalid_from, confidence, source_unit_id FROM nodes WHERE id = ?",
        (node_id,)
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "type": row[1], "title": row[2], "content": row[3],
            "metadata": json.loads(row[4]) if row[4] else {},
            "valid_from": row[5], "invalid_from": row[6],
            "confidence": row[7], "source_unit_id": row[8]}


def get_neighbors(conn, node_id: str, include_files: bool = True) -> list[tuple[dict, dict]]:
    """Get 1-hop neighbors. Returns [(node, edge), ...].

    include_files: when True (default), file-type neighbors are returned —
    decisions↔files via references/creates/modifies/mentioned_in edges carry
    high-signal file path context for agent. Earlier code blocked this.
    """
    where = "WHERE n.type != 'session'"
    if not include_files:
        where = "WHERE n.type NOT IN ('session', 'file', 'directory')"
    rows = conn.execute(f"""
        SELECT n.id, n.type, n.title, n.content, n.metadata,
               e.source_id, e.target_id, e.relation, e.explanation
        FROM edges e
        JOIN nodes n ON (n.id = e.target_id AND e.source_id = ?)
                     OR (n.id = e.source_id AND e.target_id = ?)
        {where}
        LIMIT 50
    """, (node_id, node_id)).fetchall()

    results = []
    for r in rows:
        node = {"id": r[0], "type": r[1], "title": r[2], "content": r[3],
                "metadata": json.loads(r[4]) if r[4] else {}}
        edge = {"source_id": r[5], "target_id": r[6], "relation": r[7], "explanation": r[8]}
        results.append((node, edge))
    return results


# ─── Embedding ───

def store_embedding(conn, node_id: str, embedding: list[float]):
    blob = struct.pack(f"{len(embedding)}f", *embedding)
    conn.execute("UPDATE nodes SET embedding = ? WHERE id = ?", (blob, node_id))


def _load_embedding(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))


def cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x*y for x, y in zip(a, b))
    na = sum(x*x for x in a) ** 0.5
    nb = sum(x*x for x in b) ** 0.5
    return dot / (na * nb) if na * nb > 0 else 0


def search_by_embedding(conn, query_emb: list[float], top_k: int = 5,
                        min_score: float = 0.4,
                        min_confidence: float = 0.0) -> list[tuple[dict, float]]:
    """Search nodes by cosine similarity, ranked by score × confidence.

    Returns [(node_dict, blended_score), ...].
    blended_score = cosine × (0.5 + 0.5 × confidence) so low-confidence nodes get
    pushed down without being dropped entirely.
    """
    rows = conn.execute(
        "SELECT id, type, title, content, metadata, embedding, confidence, source_unit_id "
        "FROM nodes WHERE embedding IS NOT NULL AND type NOT IN ('session', 'file', 'directory') "
        "AND COALESCE(confidence, 0.5) >= ?",
        (min_confidence,)
    ).fetchall()

    scored = []
    for row in rows:
        emb = _load_embedding(row[5])
        score = cosine_sim(query_emb, emb)
        if score > min_score:
            confidence = row[6] if row[6] is not None else 0.5
            blended = score * (0.5 + 0.5 * confidence)
            node = {"id": row[0], "type": row[1], "title": row[2], "content": row[3],
                    "metadata": json.loads(row[4]) if row[4] else {},
                    "confidence": confidence, "source_unit_id": row[7]}
            scored.append((node, blended))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ─── Processing State ───

CACHE_DIR = DB_PATH.parent / "cache"


def get_processing_state(conn, session_id: str) -> dict | None:
    row = conn.execute(
        "SELECT session_id, message_count, last_processed_uuid, task_tree_json, schema_version FROM processing_state WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    if not row:
        return None
    return {"session_id": row[0], "message_count": row[1],
            "last_processed_uuid": row[2] or "",
            "task_tree_json": row[3], "schema_version": row[4]}


def save_checkpoint(conn, session_id: str, chunk_index: int, tree_json: str):
    conn.execute(
        "INSERT INTO processing_state (session_id, task_tree_json) VALUES (?, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET task_tree_json=excluded.task_tree_json",
        (session_id, tree_json)
    )


def mark_processed(conn, session_id: str, message_count: int, session_path: str = "",
                   last_processed_uuid: str = "", tree_json: str | None = None,
                   schema_version: int | None = None):
    conn.execute(
        "INSERT INTO processing_state "
        "(session_id, session_path, message_count, last_processed_uuid, task_tree_json, schema_version) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
        "session_path=excluded.session_path, message_count=excluded.message_count, "
        "last_processed_uuid=excluded.last_processed_uuid, "
        "task_tree_json=COALESCE(excluded.task_tree_json,processing_state.task_tree_json), "
        "schema_version=COALESCE(excluded.schema_version,processing_state.schema_version), "
        "processed_at=datetime('now')",
        (session_id, session_path, message_count, last_processed_uuid, tree_json, schema_version)
    )


# ─── Atomized turn cache (file-backed) ───

def _cache_path(session_id: str):
    if not session_id or Path(session_id).name != session_id:
        raise ValueError("Invalid session id")
    return CACHE_DIR / f"{session_id}.json"


def load_cached_turns(session_id: str) -> list[dict]:
    path = _cache_path(session_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        raise ValueError("Legacy turn cache: rebuild explicitly into a separate database/cache")
    return data["turns"]


def save_cached_turns(session_id: str, turns_dicts: list[dict]) -> None:
    path = _cache_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
            temporary = Path(handle.name)
            json.dump({"version": CACHE_VERSION, "turns": turns_dicts}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


# ─── Stats ───

def stats(conn) -> dict:
    nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    with_emb = conn.execute("SELECT COUNT(*) FROM nodes WHERE embedding IS NOT NULL").fetchone()[0]
    by_type = dict(conn.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type ORDER BY COUNT(*) DESC").fetchall())
    return {"nodes": nodes, "edges": edges, "with_embedding": with_emb, "by_type": by_type}
