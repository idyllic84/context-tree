"""Offline tests for the planner (proposals, approval, conditional gate) and query handling (memory vs read-only)."""
from context_tree.ctm2 import planner as PL
from context_tree.ctm2 import query as Q
from context_tree.ctm2 import lifecycle as L
from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree


def test_planner_proposals_approval_and_gate():
    s = Store(); t = StoreTree(s)
    task = t.add('Feature X', 'finish X', None, None, 0, 0.0)
    PL.ask = lambda system, payload, **kw: ({'subtasks': [
        {'key': 's1', 'title': 'Design', 'output': 'design document', 'done_criteria': 'the document is complete', 'budget': 2, 'depends': [], 'authorized_by_user': False},
        {'key': 's2', 'title': 'Implement', 'output': 'code', 'depends': [{'on': 's1', 'type': 'serial'}], 'authorized_by_user': False},
        {'key': 's3', 'title': 'Open a PR', 'output': 'PR', 'depends': [{'on': 's2', 'type': 'conditional', 'condition': 'the tests pass'}], 'authorized_by_user': True}]}, {})
    keys, _ = PL.plan(s, t, task, request='Design first, then implement, open a PR once the tests pass', at=1.0, turn=1, model='stub')
    s1, s2, s3 = keys['s1'], keys['s2'], keys['s3']
    assert L.status(s, s1) == 'proposed' and L.status(s, s3) == 'pending'          # PR was authorized in the user's words
    PL.approve(s, [s1, s2], at=2.0)
    assert L.status(s, s1) == 'ready' and L.status(s, s2) == 'pending'
    for st in ('running', 'reported_done'): L.set_status(s, s1, st, at=3.0, source='executor')
    assert L.status(s, s2) == 'ready'
    for st in ('running', 'reported_done'): L.set_status(s, s2, st, at=4.0, source='executor')
    assert L.status(s, s3) == 'pending'                 # gated on "tests passed"
    L.condition_met(s, s2, s3, at=5.0, note='14 tests passed')
    assert L.status(s, s3) == 'ready'


def test_query_from_memory_or_readonly():
    s = Store(); t = StoreTree(s); s.add('root', {}, at=0, source='ctm', id='ROOT')
    n = t.add('sample rate', 'set the sample rate', None, None, 0, 0.0)
    Q.answer = lambda store, node, at, qs, **kw: ([{'q': 0, 'answer': '16k', 'basis': ['turn 3'], 'found': True}], {})
    Q.ask = lambda system, payload, **kw: ({'kind': 'record', 'from_memory': True, 'needs_change': False}, {})
    qid, res = Q.handle(s, question='How was the sample rate decided', node=n, at=1.0, turn=1, model='stub')
    assert res['from_memory'] and s.about(qid) == [n] and not s.items('run')
    # a record exists, but the question is about a file's current content: read-only execution, the record is only a clue
    Q.ask = lambda system, payload, **kw: ({'kind': 'current_state', 'from_memory': False, 'readonly_plan': 'read the file', 'needs_change': False}, {})
    qid, res = Q.handle(s, question='Is it 16k in the configuration file now', node=n, at=1.5, turn=1, model='stub')
    assert not res['from_memory'] and res['partial'] == '16k' and s.items('run')[-1]['data']['mode'] == 'readonly'
    Q.answer = lambda store, node, at, qs, **kw: ([{'q': 0, 'answer': 'not in memory', 'found': False}], {})
    Q.ask = lambda system, payload, **kw: ({'from_memory': False, 'readonly_plan': 'read the log', 'needs_change': False}, {})
    qid, res = Q.handle(s, question='Why does the alert fire', node=None, at=2.0, turn=2, model='stub')
    assert not res['from_memory'] and s.about(qid) == ['ROOT'] and s.items('run')[-1]['data']['mode'] == 'readonly'
    Q.ask = lambda system, payload, **kw: ({'from_memory': False, 'readonly_plan': 'restart the service and see', 'needs_change': True}, {})
    qid, res = Q.handle(s, question='Does it still fire after a restart', node=n, at=3.0, turn=3, model='stub')
    assert res.get('ask') and len(s.items('run')) == 2
    assert len(Q.panel(s)) == 4


def test_pipeline_calls_planner_and_dispatches_only_executable_subtasks():
    from context_tree.ctm2 import pipeline as P, ui as UI, root as R, ref as REF, deliver as DV, remember as RM, maintain_store as MS, scope as SC
    def script(outs):
        def ask(system, payload, **kw):
            q = outs.get(kw.get('role')) or []
            return (q.pop(0) if q else {}), {}
        return ask
    REF.ask = DV.ask = RM.ask = MS.ask = SC.ask = script({
        'ref': [{'modes': ['new'], 'entities': []}],
        'deliver': [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Feature X', 'purpose': 'finish X', 'plan': True}}]}]})
    PL.ask = lambda system, payload, **kw: ({'subtasks': [
        {'key': 's1', 'title': 'Design', 'output': 'design document', 'depends': [], 'authorized_by_user': True},
        {'key': 's2', 'title': 'Implement', 'output': 'code', 'depends': [{'on': 's1', 'type': 'serial'}], 'authorized_by_user': True},
        {'key': 's3', 'title': 'Remove old code', 'output': 'deletion', 'depends': [], 'authorized_by_user': False}]}, {})
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    r = ctm.on_message(0, 0.0, 'Finish feature X: design first, then implement', recent=[], previous_reply='', working_dir='D:/r')
    titles = [s.get(d['task'])['data']['title'] for d in r['dispatches']]
    assert titles == ['Design'] and 'Proposed subtask, waiting for approval: Remove old code' in r['relay'], (titles, r['relay'])
    # root entries are versioned on user edit
    e = R.add_understanding(s, 'Prefers minimal changes', evidence=[3], confidence='medium', at=1.0)
    e2 = UI.edit_root_item(s, e, 'Prefers minimal changes, but large changes are fine when refactoring', at=2.0)
    assert [x['id'] for x in s.items('user_understanding', current_only=True)] == [e2]


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
