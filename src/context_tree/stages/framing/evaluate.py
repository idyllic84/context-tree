"""Independent framing fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from . import processor as framing_pass

GOAL = 'Faithful compact per-unit content, identifiers and acceptance; no cross-unit mixing.'


def framing_cases():
    fixtures = [
        ("accepted-identifiers", "CSV import", [
            {"unit_id": "u1", "act": "propose", "acceptance": "hard", "is_large": False,
             "head": "parse_csv uses the standard library csv, preserves empty fields, and rejects files larger than 8 MiB.", "tail": "", "truncated_chars": 0},
            {"unit_id": "u2", "act": "explain", "acceptance": "hard", "is_large": False,
             "head": "An empty CSV file returns EmptyCsvError instead of IndexError.", "tail": "", "truncated_chars": 0}],
         {"u1": {"patterns": ["parse_csv", "csv", "empty|空字段|空值", "8\\s*MiB"], "subtype": "decision_taken"},
          "u2": {"patterns": ["EmptyCsvError", "IndexError", "empty|空"], "subtype": "rationale_accepted"}}),
        ("rejected-and-narrow-scope", "Cache tuning", [
            {"unit_id": "u31", "act": "propose", "acceptance": "rejected", "is_large": False,
             "head": "fast_cache stores tokens on disk. This proposal was rejected: tokens must never be written to disk.", "tail": "", "truncated_chars": 0},
            {"unit_id": "u32", "act": "propose", "acceptance": "unclaimed", "is_large": False,
             "head": "Proposal only: set import_data timeout to 250 ms. export_data stays unchanged. No approval yet.", "tail": "", "truncated_chars": 0}],
         {"u31": {"patterns": ["fast_cache", "reject|禁止|拒绝", "disk|磁盘"], "subtype": "decision_rejected"},
          "u32": {"patterns": ["import_data", "250\\s*ms", "export_data", "unchanged|不变", "propos|unapprov|not.*approv|no.*approv|建议|提案|未.*审批|未.*批准"],
                  "subtype": "unclaimed_proposal_small"}}),
    ]
    for name, title, items, gold in fixtures:
        body = framing_pass._format_task_block(Task("t1", title, "g1", "goal"), Goal("g1", title), items, [])
        yield Case("framing", name, framing_pass.SYSTEM_PROMPT, body, {"items": items},
                   {"units": gold, "title_limit": 80, "body_limit": 300, "forbidden": ["Redis", "PostgreSQL", "AES-256"]})


def evaluate(case, result):
    checks, metrics = ({}, {})
    gold = case.gold
    if not isinstance(result, dict):
        return ({'schema': False}, metrics)
    items = result.get('framings', [])
    entries = {e.get('unit_id'): e for e in items if isinstance(e, dict)}
    checks['unit_coverage'] = set(entries) == set(gold['units']) and len(entries) == len(items)
    fact_hits = fact_count = 0
    for uid, expected in gold['units'].items():
        e = entries.get(uid, {})
        title, body = (e.get('purpose_title', ''), e.get('purpose_body', ''))
        content = title + ' ' + body
        checks[f'subtype_{uid}'] = e.get('subtype') == expected['subtype']
        checks[f'length_{uid}'] = bool(title and body) and len(title) <= gold['title_limit'] and (len(body) <= gold['body_limit'])
        for i, pattern in enumerate(expected['patterns']):
            hit = bool(re.search(pattern, content, re.IGNORECASE))
            checks[f'fact_{uid}_{i}'] = hit
            fact_hits += hit
            fact_count += 1
    combined = json.dumps(items, ensure_ascii=False)
    checks['no_known_fabrications'] = not any((word in combined for word in gold['forbidden']))
    metrics['salient_fact_recall'] = ratio(fact_hits, fact_count)
    metrics['content_chars'] = sum((len(e.get('purpose_title', '')) + len(e.get('purpose_body', '')) for e in entries.values()))
    source = ' '.join((item['head'] + ' ' + item['tail'] for item in case.fixture['items']))
    metrics['unexpected_language_switch'] = not bool(re.search('[一-鿿]', source)) and bool(re.search('[一-鿿]', combined))
    metrics['faithfulness_requires_manual_review'] = True
    return (checks, metrics)


def cases():
    result = list(framing_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["framing"])


if __name__ == "__main__":
    main()
