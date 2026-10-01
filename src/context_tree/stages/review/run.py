from .processor import review_and_refine
from ..tree.state import TreeStateMachine
from ...common.models import Session
from ...common.stage_cli import main as stage_main


def example():
    from .evaluate import cases
    return {"session": cases()[1].fixture["session"], "max_iterations": 1}


def run(payload, args):
    session = Session.from_dict(payload["session"])
    sm = TreeStateMachine(session)
    count = review_and_refine(sm, verbose=0, max_iterations=payload.get("max_iterations", 1))
    session.goals = sm.goals
    return {"session": session.to_dict(), "mutation_count": count, "mutations": sm.mutation_log}


def main():
    stage_main("review", run, example)


if __name__ == "__main__":
    main()
