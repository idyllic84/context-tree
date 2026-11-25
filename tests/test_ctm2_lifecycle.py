"""Offline tests for task lifecycle (no model calls)."""
from context_tree.ctm2 import lifecycle as L
from context_tree.ctm2.store import Store


def tasks():
    s = Store()
    p = s.add('task', {'title': 'deliver X', 'status': 'pending'}, at=0, source='ctm')
    a = s.add('task', {'title': 'fix X', 'status': 'pending'}, at=1, source='user')
    b = s.add('task', {'title': 'PR for X', 'status': 'pending'}, at=2, source='user')
    s.set_parent(a, p, at=1, source='ctm'); s.set_parent(b, p, at=2, source='ctm')
    return s, p, a, b


def test_serial_dependency_makes_successor_ready_and_folds_up():
    s, p, a, b = tasks()
    L.add_dep(s, a, b, at=3, source='ctm')
    assert L.status(s, b) == 'pending'
    assert L.set_status(s, a, 'running', at=4, source='ctm')
    s.add('progress', {'done': 'fixed', 'open': [], 'verified': 'traced'}, at=5, source='ctm')
    s.link(s.items('progress')[-1]['id'], 'about', a, at=5, source='ctm')
    assert L.set_status(s, a, 'reported_done', at=6, source='executor')
    assert L.status(s, b) == 'ready'
    results_parent = s.items('result', about=p)
    results_succ = s.items('result', about=b)
    assert results_parent and results_succ and 'fixed' in results_parent[0]['data']['statement']


def test_invalid_transition_is_rejected_and_logged():
    s, p, a, b = tasks()
    assert not L.set_status(s, a, 'verified', at=1, source='ctm')      # pending -> verified is not allowed
    assert any(e['kind'] == 'status_rejected' for e in s.events_of(a))


def test_reopening_a_finished_predecessor_marks_successor_for_recheck():
    s, p, a, b = tasks()
    L.add_dep(s, a, b, at=3, source='ctm')
    L.set_status(s, a, 'running', at=4, source='ctm'); L.set_status(s, a, 'reported_done', at=5, source='executor')
    assert L.set_status(s, a, 'reopened', at=6, source='user', reason='the result was overturned')
    assert any(e['kind'] == 'needs_recheck' for e in s.events_of(b))


def test_parent_is_not_completed_automatically():
    s, p, a, b = tasks()
    for t in (a, b):
        L.set_status(s, t, 'running', at=4, source='ctm'); L.set_status(s, t, 'reported_done', at=5, source='executor')
    assert L.status(s, p) == 'pending'                  # no stored status change: completion is judged on demand
    assert L.children_finished(s, p) is True and L.is_done(s, p)
    L.ask = None
    from context_tree.ctm2 import model as M
    orig = M.ask
    M.ask = lambda system, payload, **kw: ({'verdict': 'gap', 'missing': 'no tests yet', 'why': ''}, {})
    try:
        assert L.parent_completion(s, p, at=6, model='stub')['verdict'] == 'gap'   # children done, purpose not yet covered
    finally:
        M.ask = orig


def test_parent_with_unfinished_child_is_not_done():
    s, p, a, b = tasks()
    L.set_status(s, a, 'running', at=4, source='ctm'); L.set_status(s, a, 'reported_done', at=5, source='executor')
    assert L.children_finished(s, p) is False and L.parent_completion(s, p, at=6, model='stub')['verdict'] == 'not_done'


def test_alternative_dependency():
    s, p, a, b = tasks()
    c = s.add('task', {'title': 'use either', 'status': 'pending'}, at=3, source='user')
    L.add_dep(s, a, c, at=3, source='ctm', kind='alternative'); L.add_dep(s, b, c, at=3, source='ctm', kind='alternative')
    L.set_status(s, b, 'running', at=4, source='ctm'); L.set_status(s, b, 'reported_done', at=5, source='executor')
    assert L.status(s, c) == 'ready'


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
