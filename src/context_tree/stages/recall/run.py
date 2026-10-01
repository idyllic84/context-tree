import sqlite3
from .processor import _flat_node_recall, _search_file_entities
from ..index.processor import search_identifier
from ...common import store
from ...common.scope import _project_session_filter
from ...common.stage_cli import main as stage_main


def example():
    return {"query": "parse_csv", "identifier": "parse_csv", "project_path": "/example"}


def run(payload, args):
    if not args.db:
        raise ValueError("recall requires an explicit existing --db")
    conn = sqlite3.connect(store.DB_PATH.as_uri() + "?mode=ro", uri=True)
    try:
        scope = _project_session_filter(conn, payload.get("project_path"))
        if payload.get("identifier"):
            return {"occurrences": search_identifier(conn, payload["identifier"], allowed_sessions=scope)}
        if payload.get("file"):
            return {"files": _search_file_entities(conn, payload["file"], allowed_sessions=scope)}
        hits = _flat_node_recall(conn, payload["query"], top_n=payload.get("top_n", 15),
                                query_embedding=payload.get("query_embedding"), allowed_sessions=scope)
        return {"hits": [{k: v for k, v in hit.items() if k != "_emb"} for hit in hits]}
    finally:
        conn.close()


def main():
    stage_main("recall", run, example)


if __name__ == "__main__":
    main()
