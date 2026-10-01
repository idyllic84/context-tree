from .processor import index_session, index_identifiers
from ...common import store
from ...common.models import Session, Goal, Task, DialogueTurn, AtomicUnit
from ...common.stage_cli import main as stage_main
import json


def example():
    unit = AtomicUnit("u1", "human", "instruct", "Use parse_csv", for_task_id="t1")
    session = Session("example", "/example", "example", [Goal("g1", "CSV", tasks=[Task("t1", "CSV import", "g1", "goal", linked_unit_ids=["u1"])])],
                      [DialogueTurn(0, "2026-01-01", "", "Use parse_csv", units=[unit])])
    return {"session": session.to_dict(), "identifiers_only": True}


def run(payload, args):
    if not args.db:
        raise ValueError("index requires an explicit --db")
    session = Session.from_dict(payload["session"])
    with store.connect() as conn:
        count = index_identifiers(conn, session)
        goals, tasks = (0, 0) if payload.get("identifiers_only") else index_session(conn, session.session_id, session.goals, session.turns)
        store.mark_processed(conn, session.session_id, 0, tree_json=json.dumps(session.to_dict()), schema_version=store.CACHE_VERSION)
    return {"identifier_occurrences": count, "goals": goals, "tasks": tasks, "database": str(store.DB_PATH)}


def main():
    stage_main("index", run, example)


if __name__ == "__main__":
    main()
