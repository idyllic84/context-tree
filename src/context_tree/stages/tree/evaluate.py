"""Independent tree fixtures and local quality metrics."""
import copy
import json
import re
from ...common.evaluation import Case, turn, fact, capture_prompt, matches, ratio, goal_of, is_under, constraint_path, action_lists
from ...common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from . import processor as build_tree
from .state import TreeStateMachine

GOAL = 'Correct task hierarchy, ownership and constraint scope; no invalid references or unrelated merges.'


def tree_case(name, session, units, gold):
    sm = TreeStateMachine(copy.deepcopy(session))
    system, body = capture_prompt(build_tree.build_tree_for_batch, sm, copy.deepcopy(units), verbose=0)
    return Case("tree", name, system, body,
                {"session": session.to_dict(), "units": [u.to_dict() for u in units]}, gold)


def tree_cases():
    units = [AtomicUnit("u1", "human", "instruct", "Implement CSV import"),
             AtomicUnit("u2", "human", "constrain", "For CSV import only: do not use pandas"),
             AtomicUnit("u3", "agent", "propose", "parse_csv uses standard library csv"),
             AtomicUnit("u4", "human", "affirm", "Agreed", target="u3"),
             AtomicUnit("u5", "human", "instruct", "Add empty-file handling as a subtask of CSV import"),
             AtomicUnit("u6", "human", "instruct", "Separately implement OAuth login; not part of CSV")]
    yield tree_case("new-independent-goals", Session("fixture", "/p", ""), units,
                    {"new_sources": ["u1", "u5", "u6"], "same_goal": [["u1", "u5"]],
                     "different_goal": [["u1", "u6"]], "subtask": [["u5", "u1"]],
                     "accepted": ["u3"], "constraints": [["u1", "pandas", "u6"]]})
    old = [AtomicUnit("u10", "agent", "propose", "parse_csv uses csv", for_task_id="t1"),
           AtomicUnit("u11", "agent", "propose", "refresh_token retries twice", for_task_id="t2")]
    session = Session("fixture", "/p", "", [
        Goal("g1", "CSV import", tasks=[Task("t1", "parse_csv implementation", "g1", "goal", linked_unit_ids=["u10"])]),
        Goal("g2", "Authentication", tasks=[Task("t2", "refresh_token implementation", "g2", "goal", linked_unit_ids=["u11"])])],
        [turn(0, "", "", units=old)])
    units = [AtomicUnit("u20", "human", "instruct", "Add empty-file handling under existing parse_csv task t1"),
             AtomicUnit("u21", "human", "constrain", "Only this empty-file subtask: error text maximum 128 bytes"),
             AtomicUnit("u22", "agent", "propose", "EmptyCsvError implements this empty-file handling"),
             AtomicUnit("u23", "human", "reject", "Authentication retries must be one, not two", target="u11", correction="refresh_token retries once")]
    yield tree_case("existing-scope-and-old-feedback", session, units,
                    {"new_sources": ["u20"], "under_task": [["u20", "t1"]],
                     "scope_on_new": ["u20", "128"], "rejected": ["u11"],
                     "preserve_goals": ["g1", "g2"], "max_goals": 2,
                     "unit_owner": [["u22", "u20"]]})


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
    source = {u: sm._source_to_task.get(u) for u in gold['new_sources']}
    checks['instruction_coverage'] = all(source.values())
    owner = lambda uid: goal_of(sm, source[uid].id) if source.get(uid) else None
    for a, b in gold.get('same_goal', []):
        checks[f'same_goal_{a}_{b}'] = owner(a) is not None and owner(a) == owner(b)
    for a, b in gold.get('different_goal', []):
        checks[f'different_goal_{a}_{b}'] = owner(a) is not None and owner(b) is not None and (owner(a) != owner(b))
    for child, parent in gold.get('subtask', []):
        checks[f'subtask_{child}'] = bool(source.get(child) and source.get(parent) and is_under(sm, source[child].id, source[parent].id) and (source[child].id != source[parent].id))
    for uid, parent in gold.get('under_task', []):
        checks[f'under_{uid}'] = bool(source.get(uid) and is_under(sm, source[uid].id, parent))
    for uid in gold.get('accepted', []):
        checks[f'accepted_{uid}'] = sm._unit_by_id[uid].acceptance == 'hard'
    for uid in gold.get('rejected', []):
        checks[f'rejected_{uid}'] = sm._unit_by_id[uid].acceptance == 'rejected'
    for uid, term, excluded in gold.get('constraints', []):
        checks[f'scope_{uid}'] = bool(source.get(uid) and term in constraint_path(sm, source[uid].id) and source.get(excluded) and (term not in constraint_path(sm, source[excluded].id)))
    if 'scope_on_new' in gold:
        uid, term = gold['scope_on_new']
        task = source.get(uid)
        checks['narrow_scope'] = bool(task and term in ' '.join(task.constraints) and all((term not in ' '.join(g.constraints) for g in sm.goals)) and (term not in ' '.join(sm._task_by_id['t1'].constraints)) and (term not in ' '.join(sm._task_by_id['t2'].constraints)))
    for uid, source_id in gold.get('unit_owner', []):
        checks[f'owner_{uid}'] = bool(source.get(source_id) and sm._unit_by_id[uid].for_task_id == source[source_id].id)
    for gid in gold.get('preserve_goals', []):
        checks[f'preserve_{gid}'] = gid in sm._goal_by_id
    if 'max_goals' in gold:
        checks['no_duplicate_goals'] = len(sm.goals) <= gold['max_goals']
    metrics['structural_checks'] = ratio(sum(checks.values()), len(checks))
    return (checks, metrics)


def cases():
    result = list(tree_cases())
    for case in result:
        case.goal = GOAL
    return result


def main():
    from ...common.evaluation_runner import main as evaluate_main
    evaluate_main(default_stages=["tree"])


if __name__ == "__main__":
    main()
