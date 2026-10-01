"""Independent select fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from ..branches.processor import _natural_branches
from ...common import context_view

GOAL = 'Choose a valid next retrieval action from the given state; do not score downstream answers.'


def selection_branches():
    csv = Task("t1", "CSV import", "g1", "goal", status="in_progress", constraints=["Preserve empty fields"])
    csv.abandoned_alternatives = [{"approach": "pandas", "reason": "Startup latency", "corrected_to": "standard library csv"}]
    auth = Task("t1", "OAuth login", "g1", "goal", status="in_progress")
    sessions = [Session("csv-session", "/p", "", [Goal("g1", "CSV", tasks=[csv])]),
                Session("auth-session", "/p", "", [Goal("g1", "Auth", tasks=[auth])])]
    lits = [{"session_id": s.session_id, "node_id": "t1", "kind": "task", "text": s.goals[0].tasks[0].name, "sim": 0.8} for s in sessions]
    branches = _natural_branches(lits, {s.session_id: s.to_dict() for s in sessions})
    for b in branches:
        title = "parse_csv uses standard library csv and preserves empty fields" if b["session_id"] == "csv-session" else "OAuth uses PKCE"
        b["_expanded_data"] = {"t1": {"evidence": [{"title": title, "subtype": "decision_taken"}],
                                          "constraints": b["_flat"]["t1"].get("constraints", [])}}
        b["_expanded"] = {"t1": {"evidence", "constraints"}}
    return branches


def selection_cases():
    for name, query, mode in [
        ("missing-evidence", "Which library was rejected for CSV import? Check the historical alternatives before deciding.", "expand"),
        ("sufficient-evidence", "Which function and library implement CSV import, and what must it preserve?", "ready"),
        ("irrelevant-branches", "Any history of implementing satellite orbit calculation?", "empty"),
    ]:
        branches = selection_branches()
        system = context_view.BRANCH_RETRIEVE_PROMPT + context_view.AGENT_VOICE
        body = context_view._format_branched_state(query, None, branches, [])
        yield Case("select", name, system, body, {"branches": branches},
                   {"state": mode, "relevant": ["csv-session/t1"] if mode != "empty" else [],
                    "irrelevant": ["auth-session/t1"] if mode != "empty" else ["csv-session/t1", "auth-session/t1"]}, 2048)


def evaluate(case, result):
    checks, metrics = ({}, {})
    gold = case.gold
    if not isinstance(result, dict):
        return ({'schema': False}, metrics)
    actions = action_lists(result)
    expands, drops = (actions.get('expand', []), actions.get('drop', []))
    searches = actions.get('search_file', []) + actions.get('search_identifier', [])
    done = actions.get('done', False)
    relevant = set(gold['relevant'])
    checks['action_schema'] = all((isinstance(actions.get(k, []), list) for k in ('expand', 'drop', 'search_file', 'search_identifier')))
    checks['no_relevant_branch_dropped'] = not any((x.get('branch_id') in relevant for x in drops))
    checks['no_irrelevant_expansion'] = not any((x.get('branch_id') in gold['irrelevant'] for x in expands))
    checks['valid_expand_targets'] = all((x.get('branch_id') in relevant and x.get('target', '').split('/')[-1] in ('g1', 't1') for x in expands))
    if done:
        chosen = {bid for candidate in actions.get('candidates', []) for bid in candidate.get('branch_ids', [])}
        checks['done_selects_relevant_branches'] = chosen == relevant
    if gold['state'] == 'expand':
        checks['fetch_missing_evidence'] = any((x.get('branch_id') == 'csv-session/t1' and x.get('target', '').split('/')[-1] == 't1' and (x.get('type') == 'abandoned') for x in expands))
        checks['no_premature_done'] = not done
    elif gold['state'] == 'ready':
        checks['appropriate_next_action'] = bool(done or drops) and (not expands) and (not searches)
    else:
        checks['appropriate_next_action'] = bool(done or drops or searches) and (not expands)
    metrics['unnecessary_expansions'] = len(expands) if gold['state'] != 'expand' else sum((x.get('type') != 'abandoned' for x in expands))
    metrics['search_actions'] = len(searches)
    metrics['next_action_only'] = True
    return (checks, metrics)


def cases():
    result = list(selection_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["select"])


if __name__ == "__main__":
    main()
