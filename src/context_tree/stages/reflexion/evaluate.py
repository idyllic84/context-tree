"""Independent reflexion fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from . import processor as reflexion

GOAL = 'Identify contradicted/missing/misassigned claims with evidence; avoid false corrections.'


def audit_session(corrupt):
    raw = "For parse_csv: do not use pandas, keep empty fields, and set its timeout to 50 ms. For OAuth login: use PKCE."
    csv_rules = ["Use pandas", "Keep empty fields", "Use PKCE"] if corrupt else ["Do not use pandas", "Keep empty fields", "Timeout 50 ms"]
    auth_rules = [] if corrupt else ["Use PKCE"]
    return Session("audit", "/p", "", [Goal("g1", "Project", tasks=[
        Task("t1", "parse_csv", "g1", "goal", constraints=csv_rules),
        Task("t2", "OAuth login", "g1", "goal", constraints=auth_rules)])],
        [turn(0, raw, "Understood. I have not implemented anything yet.")])


def reflexion_cases():
    for corrupt in (True, False):
        session = audit_session(corrupt)
        system, body = capture_prompt(reflexion.review_session, session, verbose=0)
        yield Case("reflexion", "claim-errors" if corrupt else "supported-claims", system, body,
                   {"session": session.to_dict()},
                   {"remove": ["t0.c0"] if corrupt else [],
                    "move": {"t0.c2": 1} if corrupt else {},
                    "missing": [[0, "50"]] if corrupt else [],
                    "protected": ["t0.c1"] if corrupt else ["t0.c0", "t0.c1", "t0.c2", "t1.c0"]})


def evaluate(case, result):
    checks, metrics = ({}, {})
    gold = case.gold
    if not isinstance(result, dict):
        return ({'schema': False}, metrics)
    keys = ('hallucinations', 'missing', 'misassignments')
    checks['correction_schema'] = all((isinstance(result.get(k), list) for k in keys))
    if not checks['correction_schema']:
        return (checks, metrics)
    removed = [x for x in result['hallucinations'] if x.get('confidence', 0) >= reflexion.HALLUC_REMOVE_THRESHOLD]
    moved = [x for x in result['misassignments'] if x.get('confidence', 0) >= reflexion.MISASSIGN_THRESHOLD]
    added = [x for x in result['missing'] if x.get('confidence', 0) >= reflexion.MISSING_ADD_THRESHOLD]
    for cid in gold['remove']:
        checks[f'remove_{cid}'] = any((x.get('claim_id') == cid for x in removed))
    for cid, tid in gold['move'].items():
        checks[f'move_{cid}'] = any((x.get('claim_id') == cid and x.get('correct_task_index') == tid for x in moved))
    for tid, term in gold['missing']:
        checks[f'missing_{term}'] = any((x.get('task_index') == tid and term in x.get('text', '') for x in added))
    all_changes = removed + moved + added
    checks['evidence_present'] = all((bool(x.get('evidence', '').strip()) for x in all_changes))
    checks['preserve_supported_claims'] = not any((x.get('claim_id') in gold['protected'] for x in removed + moved))
    if not gold['remove'] and (not gold['move']) and (not gold['missing']):
        checks['no_false_corrections'] = not all_changes
    else:
        checks['no_unknown_claim_edits'] = all((x.get('claim_id') in gold['remove'] for x in removed)) and all((x.get('claim_id') in gold['move'] for x in moved))
    metrics['actionable_corrections'] = len(all_changes)
    metrics['protected_claim_false_edits'] = sum((x.get('claim_id') in gold['protected'] for x in removed + moved))
    metrics['evidence_requires_manual_review'] = True
    return (checks, metrics)


def cases():
    result = list(reflexion_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["reflexion"])


if __name__ == "__main__":
    main()
