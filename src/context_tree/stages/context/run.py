from .processor import assemble_context, _finalize_branched
from ...common.stage_cli import main as stage_main


def example():
    from .evaluate import cases
    return {"query": "Provide CSV import context", "branches": cases()[0].fixture["branches"], "mode": "agent"}


def run(payload, args):
    branches = payload["branches"]
    mode = payload.get("mode", "agent")
    candidates = assemble_context(payload["query"], payload.get("current_session_id"), branches,
                                   mode=mode, search_results=payload.get("search_results"))
    return _finalize_branched(candidates, branches, set(), [], {}, 0, mode=mode)


def main():
    stage_main("context", run, example)


if __name__ == "__main__":
    main()
