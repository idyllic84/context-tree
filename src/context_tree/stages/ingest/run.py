import json
import tempfile
from pathlib import Path
from .processor import parse_turns
from ...common.models import Session
from ...common.stage_cli import main as stage_main


def example():
    return {"session_id": "example", "messages": [
        {"type": "user", "uuid": "example-user", "cwd": "/example", "message": {"content": "Implement parse_csv without pandas."}},
        {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "I propose using the standard library csv."}]}}
    ]}


def run(payload, args):
    if "file_path" in payload:
        turns, project = parse_turns(str(Path(payload["file_path"]).expanduser()))
    else:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text("\n".join(json.dumps(m) for m in payload["messages"]) + "\n", encoding="utf-8")
            turns, project = parse_turns(str(path))
    session = Session(payload.get("session_id", "input"), project, payload.get("display_name", "input"),
                      turns=[t for t in turns if t.complete], pending_turns=[t for t in turns if not t.complete])
    return {"session": session.to_dict()}


def main():
    stage_main("ingest", run, example)


if __name__ == "__main__":
    main()
