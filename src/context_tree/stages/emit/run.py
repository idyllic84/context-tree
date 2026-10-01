from .processor import convert_session
from ...common.models import Session
from ...common.stage_cli import main as stage_main


def example():
    from ..framing.run import example as upstream
    result = upstream()
    unit = result["session"]["turns"][0]["units"][0]
    unit["purpose_title"] = "parse_csv standard-library parser"
    unit["purpose_body"] = "Uses csv and preserves empty fields."
    return result


def run(payload, args):
    session = Session.from_dict(payload["session"])
    entities, edges = convert_session(session, date=payload.get("date", ""))
    return {"entities": entities, "edges": edges}


def main():
    stage_main("emit", run, example)


if __name__ == "__main__":
    main()
