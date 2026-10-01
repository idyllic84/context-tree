from .processor import select_action
from ...common.stage_cli import main as stage_main


def example():
    from .evaluate import cases
    return {"query": "Which CSV library was rejected?", "branches": cases()[0].fixture["branches"], "mode": "agent"}


def run(payload, args):
    action = select_action(payload["query"], payload["branches"],
                           current_session_id=payload.get("current_session_id"),
                           history=payload.get("history"), search_results=payload.get("search_results"),
                           mode=payload.get("mode", "agent"))
    if not isinstance(action, dict):
        raise ValueError("Selection did not return an action object")
    return {"action": action}


def main():
    stage_main("select", run, example)


if __name__ == "__main__":
    main()
