from .processor import frame_session
from ...common.models import Session, Goal, Task, DialogueTurn, AtomicUnit
from ...common.stage_cli import main as stage_main


def example():
    unit = AtomicUnit("u1", "agent", "propose", "parse_csv uses csv", for_task_id="t1", acceptance="hard")
    turn = DialogueTurn(0, "", "parse_csv uses the standard library csv and keeps empty fields.", "Implement CSV import.", units=[unit],
                        agent_split={"head": "parse_csv uses the standard library csv and keeps empty fields.", "tail": "", "truncated_chars": 0})
    session = Session("example", "/example", "example", [Goal("g1", "CSV import", tasks=[Task("t1", "CSV parser", "g1", "goal", linked_unit_ids=["u1"])])], [turn])
    return {"session": session.to_dict()}


def run(payload, args):
    session = Session.from_dict(payload["session"])
    frame_session(session, verbose=0)
    return {"session": session.to_dict()}


def main():
    stage_main("framing", run, example)


if __name__ == "__main__":
    main()
