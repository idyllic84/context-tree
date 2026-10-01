from .processor import batch_units_for_l2, build_tree_for_batch
from .state import TreeStateMachine
from ...common.models import Session, DialogueTurn, AtomicUnit
from ...common.stage_cli import main as stage_main


def example():
    from .evaluate import cases
    case = cases()[0]
    return {"session": case.fixture["session"], "units": case.fixture["units"]}


def run(payload, args):
    session = Session.from_dict(payload["session"])
    if "initial_session" in payload:
        initial = Session.from_dict(payload["initial_session"])
    elif "units" in payload:
        initial = session
    else:
        initial = Session.from_dict({**session.to_dict(), "turns": []})
    sm = TreeStateMachine(initial)
    if "units" in payload:
        units = [AtomicUnit.from_dict(u) for u in payload["units"]]
        next_turn = max((t.turn_id for t in initial.turns), default=-1) + 1
        turns = [DialogueTurn(next_turn, "", "", "", units=units)]
    else:
        turns = session.turns
    for units, batch in batch_units_for_l2(turns):
        build_tree_for_batch(sm, units, batch_turns=batch, verbose=0)
    result = sm.to_session(session.session_id, session.project_path, session.display_name,
                           initial.turns + turns)
    result.pending_turns = session.pending_turns
    return {"session": result.to_dict(), "mutations": sm.mutation_log, "warnings": sm.warnings}


def main():
    stage_main("tree", run, example)


if __name__ == "__main__":
    main()
