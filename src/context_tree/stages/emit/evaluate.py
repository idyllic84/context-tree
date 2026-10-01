from types import SimpleNamespace
from .run import example, run


def checks():
    result = run(example(), SimpleNamespace())
    contents = [e for e in result["entities"] if e["type"] == "agent_content"]
    return {"one_agent_content": len(contents) == 1,
            "stable_unit_identity": contents[0]["id"] == "example:agent_content:u1",
            "acceptance_preserved": contents[0]["metadata_extra"]["subtype"] == "decision_taken",
            "identifier_preserved": "parse_csv" in contents[0]["title"]}


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["emit"])


if __name__ == "__main__":
    main()
