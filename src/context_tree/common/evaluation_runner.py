"""Serial harness for stage-owned cases and scorers; no end-to-end ranking."""
import argparse
import contextlib
import hashlib
import importlib
import json
import statistics
import time
from pathlib import Path
from unittest.mock import patch

from . import llm
from .evaluation import parse_json

MODEL_STAGES = ("extract", "tree", "review", "reflexion", "framing", "select", "context")
LOCAL_STAGES = ("ingest", "emit", "resolve", "index", "recall", "branches")
DEFAULT_MODELS = ("gemini-3.6-flash:minimal", "gpt-5.6-sol-fast:low", "gpt-6.1-sol:medium", "grok-4.6:low", "grok-4.7:low")


def load(stage):
    return importlib.import_module(f"context_tree.stages.{stage}.evaluate")


def offline(stages):
    results = {}
    with patch.object(llm._SESSION, "request", side_effect=AssertionError("Offline evaluation attempted network")):
        for stage in stages:
            module = load(stage)
            if stage in LOCAL_STAGES:
                checks = module.checks()
                if not checks or not all(checks.values()):
                    raise AssertionError(f"{stage}: {checks}")
                results[stage] = {"checks": len(checks), "passed": True}
            else:
                cases = module.cases()
                if len({c.name for c in cases}) != len(cases):
                    raise AssertionError(f"Duplicate cases in {stage}")
                for case in cases:
                    json.dumps(case.snapshot())
                    checks, _ = module.evaluate(case, {})
                    if not checks or all(checks.values()):
                        raise AssertionError(f"Empty output passed {stage}/{case.name}")
                results[stage] = {"fixtures": len(cases), "empty_output_rejected": True}
    return results


def main(default_stages=None):
    parser = argparse.ArgumentParser(description="Evaluate stage-specific intermediate outputs")
    parser.add_argument("--stages", nargs="+", choices=MODEL_STAGES + LOCAL_STAGES,
                        default=default_stages or list(MODEL_STAGES))
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--request-limit", type=int, default=120)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--offline-check", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    if args.offline_check or all(stage in LOCAL_STAGES for stage in args.stages):
        print(json.dumps(offline(args.stages), indent=2))
        return
    if not args.allow_network:
        parser.error("Model evaluation requires --allow-network; use --offline-check for local validation")
    if args.runs < 1 or args.request_limit < 1:
        parser.error("Runs and request limit must be positive")
    if not args.output or not args.output.parent.is_dir():
        parser.error("Provide --output in an existing directory")
    modules = {stage: load(stage) for stage in args.stages if stage in MODEL_STAGES}
    cases = [case for module in modules.values() for case in module.cases()]
    package = Path(__file__).resolve().parents[1]
    source_bytes = b"".join(str(p.relative_to(package)).encode() + p.read_bytes()
                            for p in sorted(package.rglob("*.py")))
    snapshots = json.dumps([case.snapshot() for case in cases], sort_keys=True, ensure_ascii=False).encode()
    protocol = hashlib.sha256(source_bytes + snapshots).hexdigest()
    data = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {"requests": 0, "rows": [], "cases": {}}
    llm.REQUEST_COUNT = data["requests"]
    llm.REQUEST_LIMIT = args.request_limit
    for case in cases:
        data["cases"][case.digest()] = case.snapshot()

    def save():
        data["requests"] = llm.REQUEST_COUNT
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    try:
        for index, case in enumerate(cases):
            for run in range(args.runs):
                shift = (index + run) % len(args.models)
                for spec in args.models[shift:] + args.models[:shift]:
                    if llm.REQUEST_COUNT >= args.request_limit:
                        raise llm.RequestBudgetExceeded("Evaluation request budget reached")
                    model, _, effort = spec.partition(":")
                    started, before, metric_start = time.perf_counter(), llm.REQUEST_COUNT, len(llm.CALL_METRICS)
                    row = {"stage": case.stage, "case": case.name, "model": model, "effort": effort,
                           "protocol": protocol, "input_hash": case.digest(), "run": run + 1}
                    try:
                        text = llm.chat_content(case.system, case.body, model=model,
                            stage="retrieve" if case.stage == "select" else case.stage,
                            reasoning_effort=effort or None, max_output_tokens=case.output_limit, timeout=90)
                        row["raw_response"] = text
                        result = parse_json(text)
                        checks, metrics = modules[case.stage].evaluate(case, result)
                        row.update(result=result, checks=checks, stage_metrics=metrics,
                                   passed=bool(checks) and all(checks.values()))
                    except Exception as exc:
                        row.update(passed=False, error=str(exc)[:400], checks={"valid_response": False})
                    row.update(seconds=round(time.perf_counter()-started, 3), requests=llm.REQUEST_COUNT-before,
                               calls=llm.CALL_METRICS[metric_start:])
                    data["rows"].append(row)
                    save()
                    print(json.dumps({k: row.get(k) for k in ("stage", "case", "model", "passed", "seconds", "error")}), flush=True)
    except llm.RequestBudgetExceeded as exc:
        print(str(exc))
    finally:
        save()
    for stage in modules:
        for spec in args.models:
            model, _, effort = spec.partition(":")
            rows = [r for r in data["rows"] if r["protocol"] == protocol and r["stage"] == stage
                    and r["model"] == model and r["effort"] == effort]
            if rows:
                print(stage, spec, f"gates={sum(r['passed'] for r in rows)}/{len(rows)}",
                      f"median={statistics.median(r['seconds'] for r in rows):.2f}s")
