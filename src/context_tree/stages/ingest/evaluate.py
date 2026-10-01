from types import SimpleNamespace
from .run import example, run


def checks():
    payload = example()
    payload["messages"].insert(1, {"type": "assistant", "message": {"content": [{"type": "text", "text": "Planning."}]}})
    session = run(payload, SimpleNamespace())["session"]
    return {"one_turn": len(session["turns"]) == 1,
            "assistant_text_accumulates": session["turns"][0]["agent_raw"].startswith("Planning."),
            "trailing_response_complete": session["turns"][0]["complete"],
            "no_pending_after_end_turn": not session["pending_turns"]}


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["ingest"])


if __name__ == "__main__":
    main()
