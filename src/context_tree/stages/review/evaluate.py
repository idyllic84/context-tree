"""Independent review fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from . import processor as tree_review
from ..tree.state import TreeStateMachine

GOAL = 'Repair known structural faults while preserving correct branches; precision before mutation count.'


def review_session(wrong=False):
    csv = Task("t1", "CSV parser implementation", "g1", "goal", status="completed")
    auth = Task("t2", "OAuth PKCE login implementation", "g2", "goal", status="in_progress")
    tasks_csv, tasks_auth = [csv], [auth]
    if wrong:
        tasks_auth.append(Task("t3", "Handle empty CSV files in parse_csv; belongs to CSV parser", "g2", "goal"))
    return Session("review", "/p", "", [Goal("g1", "CSV import", tasks=tasks_csv),
                                            Goal("g2", "Authentication", tasks=tasks_auth)])


def review_cases():
    for wrong in (False, True):
        session = review_session(wrong)
        system, body = capture_prompt(tree_review._review_once, TreeStateMachine(session), verbose=0)
        yield Case("review", "misplaced-task" if wrong else "clean-tree", system, body,
                   {"session": session.to_dict()},
                   {"repair": {"t3": "g1"} if wrong else {},
                    "protected": {"t1": ["g1", "completed"], "t2": ["g2", "in_progress"]},
                    "clean": not wrong})


def evaluate(case, result):
    checks, metrics = ({}, {})
    gold = case.gold
    if not isinstance(result, dict):
        return ({'schema': False}, metrics)
    session = Session.from_dict(case.fixture['session'])
    sm = TreeStateMachine(session)
    key = 'tree_mutations' if case.stage == 'tree' else 'refinement_mutations'
    mutations = result.get(key)
    checks['mutation_schema'] = isinstance(mutations, list)
    if not checks['mutation_schema']:
        return (checks, metrics)
    units = [AtomicUnit.from_dict(u) for u in case.fixture.get('units', [])]
    warnings = sm.apply_mutations(mutations, units)
    checks['valid_mutations'] = not warnings
    metrics['invalid_mutations'] = len(warnings)
    for tid, gid in gold['repair'].items():
        checks[f'repair_{tid}'] = goal_of(sm, tid) == gid
    for tid, (gid, status) in gold['protected'].items():
        checks[f'preserve_{tid}'] = goal_of(sm, tid) == gid and sm._task_by_id[tid].status == status
    if gold['clean']:
        checks['no_unnecessary_mutations'] = not mutations
    metrics['repair_recall'] = ratio(sum((checks[f'repair_{tid}'] for tid in gold['repair'])), len(gold['repair']))
    metrics['false_changes'] = sum((not checks[f'preserve_{tid}'] for tid in gold['protected']))
    return (checks, metrics)


def cases():
    result = list(review_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["review"])


if __name__ == "__main__":
    main()
