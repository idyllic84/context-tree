import sqlite3
import struct
from .processor import _flat_node_recall
from ..index.processor import _ensure_indexes


def checks():
    conn = sqlite3.connect(":memory:")
    _ensure_indexes(conn)
    for tid, vector in (("t1", [1., 0.]), ("t2", [0., 1.])):
        conn.execute("INSERT INTO task_index VALUES (?,?,?,?,?,?,?,?,?)",
                     ("session", tid, "g1", tid, "pending", 0, "", "", struct.pack("2f", *vector)))
    try:
        hits = _flat_node_recall(conn, "query", query_embedding=[1., 0.], top_n=1)
        return {"nearest_node": len(hits) == 1 and hits[0]["node_id"] == "t1",
                "empty_scope_is_empty": not _flat_node_recall(conn, "query", query_embedding=[1., 0.], allowed_sessions=set())}
    finally:
        conn.close()


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["recall"])


if __name__ == "__main__":
    main()
