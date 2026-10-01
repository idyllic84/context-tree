from .processor import _natural_branches
from ...common.models import Session, Goal, Task
from ...common.stage_cli import main as stage_main


def example():
    session = Session("example", "/example", "example", [Goal("g1", "CSV", tasks=[
        Task("t1", "Parse CSV", "g1", "goal"), Task("t2", "Validate CSV", "g1", "goal")])])
    return {"sessions": {session.session_id: session.to_dict()}, "hits": [
        {"session_id": "example", "node_id": "t1", "kind": "task", "text": "Parse CSV", "sim": 0.9},
        {"session_id": "example", "node_id": "t2", "kind": "task", "text": "Validate CSV", "sim": 0.8}]}


def run(payload, args):
    return {"branches": _natural_branches(payload["hits"], payload["sessions"])}


def main():
    stage_main("branches", run, example)


if __name__ == "__main__":
    main()
