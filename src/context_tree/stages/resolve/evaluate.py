import sqlite3
from .processor import resolve


def checks():
    conn = sqlite3.connect(":memory:")
    entities = [{"id": "device:/example/a.py", "title": "/example/a.py", "type": "file", "confidence": 0.95}]
    try:
        result, embeddings = resolve(conn, entities, verbose=0)
        return {"path_identity_preserved": result == entities, "path_bypasses_models": embeddings == []}
    finally:
        conn.close()


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["resolve"])


if __name__ == "__main__":
    main()
