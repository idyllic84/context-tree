from .processor import review_session
from ...common.models import Session
from ...common.stage_cli import main as stage_main


def example():
    from .evaluate import cases
    return {"session": cases()[0].fixture["session"]}


def run(payload, args):
    session = Session.from_dict(payload["session"])
    corrections = review_session(session, verbose=0)
    return {"session": session.to_dict(), "corrections": corrections}


def main():
    stage_main("reflexion", run, example)


if __name__ == "__main__":
    main()
