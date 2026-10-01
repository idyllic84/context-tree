"""Common JSON transport for independently runnable stages."""
import argparse
import contextlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

from . import llm, store


def main(stage, run, example):
    parser = argparse.ArgumentParser(description=f"Run only the {stage} stage")
    parser.add_argument("--input", type=Path, help="Stage JSON input; stdin when omitted")
    parser.add_argument("--output", type=Path, help="JSON output; stdout when omitted")
    parser.add_argument("--example", action="store_true", help="Print synthetic input without running")
    parser.add_argument("--db", help="Explicit database for index/recall operations")
    parser.add_argument("--cache-dir")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--request-limit", type=int, default=20)
    parser.add_argument("--allow-network", action="store_true", help="Allow explicit paid model/API requests")
    args = parser.parse_args()
    if args.output and not args.output.parent.is_dir():
        parser.error("Output parent directory must exist")
    if args.request_limit < 0:
        parser.error("Request limit must be nonnegative")
    if args.example:
        result = example()
    else:
        payload = json.loads(args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read())
        if not isinstance(payload, dict):
            parser.error("Stage input must be a JSON object")
        store.configure_paths(args.db, args.cache_dir)
        role = "retrieve" if stage == "select" else stage
        efforts = [f"{role}={args.effort}"] if args.effort else []
        overrides = [f"{role}={args.model}"] if args.model and role in llm.STAGES else []
        llm.configure_stages(overrides=overrides, efforts=efforts)
        llm.REQUEST_COUNT = 0
        llm.REQUEST_LIMIT = args.request_limit
        with contextlib.ExitStack() as stack:
            if not args.allow_network:
                stack.enter_context(patch.object(llm._SESSION, "request", side_effect=RuntimeError(
                    "Network is disabled; add --allow-network after reviewing the input")))
                stack.enter_context(patch.object(llm, "get_token", side_effect=RuntimeError(
                    "Network is disabled; add --allow-network for this model-backed operation")))
            with contextlib.redirect_stdout(sys.stderr):
                result = run(payload, args)
    text = json.dumps(result, ensure_ascii=False, indent=2, default=lambda value: sorted(value) if isinstance(value, set) else str(value)) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
