import json
import sqlite3
from .processor import index_identifiers, search_identifier
from .run import example


def checks():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE processing_state(session_id TEXT, task_tree_json TEXT)")
    session = example()["session"]
    conn.execute("INSERT INTO processing_state VALUES (?,?)", (session["session_id"], json.dumps(session)))
    try:
        count = index_identifiers(conn, session)
        first = search_identifier(conn, "parse_csv")
        index_identifiers(conn, session)
        return {"literal_found": count > 0 and bool(first),
                "task_provenance": first[0]["task_id"] == "t1",
                "case_sensitive": not search_identifier(conn, "Parse_Csv"),
                "replace_idempotent": search_identifier(conn, "parse_csv") == first}
    finally:
        conn.close()


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["index"])


if __name__ == "__main__":
    main()
