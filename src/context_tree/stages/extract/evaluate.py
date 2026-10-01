"""Independent extract fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from . import processor as extract_units

GOAL = 'Preserve explicit facts, speech acts and earlier-response targets; throughput after correctness.'


def extraction_cases():
    turns = [
        turn(0, "实现 parse_csv。不要使用 pandas，空字段必须保留。",
             "建议 parse_csv 使用标准库 csv，保留空字段。"),
        turn(1, "同意这个方案。另起独立任务，给登录模块实现 refresh_token。",
             "建议 refresh_token 最多重试 2 次。", "建议 parse_csv 使用标准库 csv，保留空字段。"),
        turn(2, "不行，refresh_token 只能重试 1 次；CSV 方案不变。",
             "将 refresh_token 重试上限改为 1 次。", "建议 refresh_token 最多重试 2 次。"),
    ]
    required = [
        fact(0, "human", ["instruct"], ["parse_csv"]),
        fact(0, "human", ["constrain"], ["pandas", "不要|不得|不使用|不引入|禁止|不能|不允许"]),
        fact(0, "human", ["constrain"], ["空字段|空值|空列", "保留"]),
        fact(0, "agent", ["propose"], ["parse_csv", "csv"]),
        fact(1, "human", ["instruct"], ["refresh_token"]),
        fact(1, "agent", ["propose"], ["refresh_token", "2|两|二"]),
        fact(2, "human", ["reject", "constrain"], ["refresh_token", "1|一"]),
        fact(2, "human", ["affirm", "reject", "constrain", "report"], ["CSV|csv", "不变|保持|维持|不修改"]),
        fact(2, "agent", ["report", "explain", "propose"], ["refresh_token", "1|一"]),
    ]
    yield Case("extract", "cn-feedback-and-topic-switch", extract_units.SYSTEM_PROMPT,
               extract_units._compose_body(turns, [], 1),
               {"turns": [t.to_dict() for t in turns], "prior": [], "next_id": 1},
               {"facts": required, "feedback": [[1, "affirm", 0], [2, "reject", 1]]})
    prior = [AtomicUnit("u40", "agent", "propose", "Use fast_cache for import_data.")]
    turns = [turn(10, "Reject fast_cache; use safe_cache instead. Keep the audit flag enabled only for import_data; do not change export_data.",
                  "I propose safe_cache for import_data and will leave export_data unchanged.", prior[0].text)]
    yield Case("extract", "en-cross-batch-feedback", extract_units.SYSTEM_PROMPT,
               extract_units._compose_body(turns, prior, 41),
               {"turns": [t.to_dict() for t in turns], "prior": [u.to_dict() for u in prior], "next_id": 41},
               {"facts": [fact(10, "human", ["reject", "instruct"], ["fast_cache", "safe_cache"]),
                          fact(10, "human", ["constrain", "instruct", "reject"], ["audit", "import_data", "only"]),
                          fact(10, "human", ["constrain", "instruct", "reject"], ["export_data", "unchanged|not change|no change|do not modify|leave"]),
                          fact(10, "agent", ["propose"], ["safe_cache", "import_data"])],
                "feedback": [[10, "reject", "u40"]]})


def evaluate(case, result):
    checks, metrics = ({}, {})
    gold = case.gold
    if not isinstance(result, dict):
        return ({'schema': False}, metrics)
    turns = [DialogueTurn.from_dict(t) for t in case.fixture['turns']]
    prior = [AtomicUnit.from_dict(u) for u in case.fixture['prior']]
    try:
        extract_units._normalize_batch(copy.deepcopy(result), turns, prior, case.fixture['next_id'])
        checks['schema_and_temporal_references'] = True
    except (ValueError, TypeError, KeyError):
        checks['schema_and_temporal_references'] = False
    rows = {r.get('turn_id'): r for r in result.get('turns', []) if isinstance(r, dict)}
    hits = 0
    for i, expected in enumerate(gold['facts']):
        units = rows.get(expected['turn'], {}).get('units', [])
        hit = any((u.get('speaker') == expected['speaker'] and u.get('act') in expected['acts'] and matches((u.get('text') or '') + ' ' + (u.get('correction') or ''), expected['patterns']) for u in units))
        checks[f'fact_{i}'] = hit
        hits += hit
    targets = {u['id']: t['turn_id'] for t in rows.values() for u in t.get('units', []) if u.get('speaker') == 'agent'}
    targets.update({u.id: u.id for u in prior})
    for tid, act, target_turn in gold['feedback']:
        checks[f'feedback_{tid}'] = any((u.get('act') == act and targets.get(u.get('target')) == target_turn for u in rows.get(tid, {}).get('units', [])))
    metrics['explicit_fact_recall'] = ratio(hits, len(gold['facts']))
    metrics['feedback_accuracy'] = ratio(sum((v for k, v in checks.items() if k.startswith('feedback_'))), len(gold['feedback']))
    return (checks, metrics)


def cases():
    result = list(extraction_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["extract"])


if __name__ == "__main__":
    main()
