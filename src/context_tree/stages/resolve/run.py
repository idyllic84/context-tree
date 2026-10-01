from .processor import resolve
from ...common import store
from ...common.stage_cli import main as stage_main


def example():
    return {"entities": [{"id": "example:path", "type": "file", "title": "/example/parser.py", "confidence": 0.95}]}


def run(payload, args):
    if not args.db:
        raise ValueError("resolve requires an explicit --db; use a disposable database")
    with store.connect() as conn:
        entities, embeddings = resolve(conn, payload["entities"], verbose=0)
    return {"entities": entities, "embeddings": [{"id": key, "vector": vector} for key, vector in embeddings]}


def main():
    stage_main("resolve", run, example)


if __name__ == "__main__":
    main()
