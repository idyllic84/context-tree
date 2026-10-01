"""Independent context fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from ..select.evaluate import selection_branches
from ...common import context_view

GOAL = 'Assemble only necessary supplied facts, preserving scope and source IDs within a size budget.'


def context_cases():
    branches = selection_branches()
    csv = next(b for b in branches if b["session_id"] == "csv-session")
    csv["_expanded_data"]["t1"]["abandoned"] = csv["_flat"]["t1"]["abandoned_alternatives"]
    system = context_view.BRANCH_RETRIEVE_PROMPT + context_view.AGENT_VOICE
    suffix = "\nAll required evidence is supplied. Assemble the final context candidates; do not search or expand."
    yield Case("context", "compact-with-rejected-option", system,
               context_view._format_branched_state("Return CSV context: chosen function/library, rejected library, and required field handling.", None, branches, []) + suffix,
               {"branches": branches},
               {"required_branches": ["csv-session/t1"], "facts": {"csv-session/t1": ["parse_csv", "csv", "pandas", "empty", "ABANDONED"]},
                "forbidden": ["PKCE", "OAuth"], "max_chars": 650, "max_lines": 6}, 2048)
    branches = selection_branches()
    auth = next(b for b in branches if b["session_id"] == "auth-session")
    auth["anchor_name"] = "CSV import for the cloud service"
    auth["breadcrumb"] = ["Cloud CSV import"]
    auth["_flat"]["g1"]["intent"] = "Cloud CSV import"
    auth["_flat"]["t1"]["name"] = auth["anchor_name"]
    for node in auth["nodes"]:
        node["name"] = auth["anchor_name"] if node["id"] == "t1" else "Cloud CSV import"
    for member in auth["lit_members"]:
        member["name"] = auth["anchor_name"]
    auth["_expanded_data"]["t1"] = {"evidence": [{"title": "parse_cloud_csv uses pandas; cloud service only", "subtype": "decision_taken"}],
                                      "constraints": ["pandas allowed only in cloud service"]}
    yield Case("context", "separate-same-topic-contexts", system,
               context_view._format_branched_state("Provide two independent context options for local CSV import and cloud CSV import. Their implementations differ; do not merge their rules.", None, branches, []) + suffix,
               {"branches": branches},
               {"required_branches": ["csv-session/t1", "auth-session/t1"],
                "facts": {"csv-session/t1": ["parse_csv", "empty"], "auth-session/t1": ["parse_cloud_csv", "pandas", "cloud"]},
                "separate": True, "forbidden": ["PKCE"], "max_chars": 1100, "max_lines": 12}, 2048)


def evaluate(case, result):
    checks, metrics = ({}, {})
    gold = case.gold
    if not isinstance(result, dict):
        return ({'schema': False}, metrics)
    actions = action_lists(result)
    entries = actions.get('candidates', [])
    checks['done_without_tools'] = bool(actions.get('done')) and (not any((actions.get(k) for k in ('expand', 'search_file', 'search_identifier'))))
    selected = {bid for c in entries for bid in c.get('branch_ids', [])}
    checks['selected_contexts'] = selected == set(gold['required_branches'])
    if gold.get('separate'):
        checks['independent_contexts'] = len(entries) == 2 and all((len(c.get('branch_ids', [])) == 1 for c in entries))
    for bid, patterns in gold['facts'].items():
        summary = '\n'.join((c.get('summary', '') for c in entries if bid in c.get('branch_ids', [])))
        checks[f'facts_{bid}'] = matches(summary, patterns)
        checks[f'citation_{bid}'] = any((bid in c.get('cited', []) for c in entries if bid in c.get('branch_ids', [])))
    text = '\n'.join((c.get('summary', '') for c in entries))
    checks['exclude_irrelevant_facts'] = not any((word in text for word in gold['forbidden']))
    checks['context_budget'] = len(text) <= gold['max_chars'] and len(text.splitlines()) <= gold['max_lines']
    checks['tagged_facts'] = bool(entries) and all((re.match('^(CONSTRAINT|DECISION|ABANDONED|RECENT|WARNING|FILE):', line.strip()) for line in text.splitlines() if line.strip()))
    metrics['context_chars'] = len(text)
    metrics['context_lines'] = len(text.splitlines())
    return (checks, metrics)


def cases():
    result = list(context_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["context"])


if __name__ == "__main__":
    main()
