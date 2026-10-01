from .processor import extract_session
from ...common.models import Session, AtomicUnit
from ...common.stage_cli import main as stage_main


def example():
    from .evaluate import cases
    case = cases()[0]
    return {"session": Session("example", "/example", "example").to_dict() | {"turns": case.fixture["turns"]},
            "prior_units": case.fixture["prior"]}


def run(payload, args):
    session = Session.from_dict(payload["session"])
    prior = [AtomicUnit.from_dict(u) for u in payload.get("prior_units", [])]
    units, _ = extract_session(session.turns, prior_units=prior, verbose=0)
    return {"session": session.to_dict(), "unit_count": len(units)}


def main():
    stage_main("extract", run, example)


if __name__ == "__main__":
    main()
