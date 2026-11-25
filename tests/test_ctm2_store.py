"""Offline tests for the ctm2 memory store (no model calls)."""
from context_tree.ctm2.store import Store


def test_parent_as_known_at_a_time():
    s = Store()
    g = s.add('goal', {'title': 'G'}, at=1, source='user')
    a = s.add('task', {'title': 'A'}, at=2, source='ctm')
    b = s.add('task', {'title': 'B'}, at=3, source='ctm')
    s.set_parent(a, g, at=2, source='ctm')
    s.set_parent(a, b, at=5, source='maintenance', reason='serves B')
    assert s.parent(a, at=4) == g
    assert s.parent(a, at=6) == b
    assert s.parent(a) == b
    assert [e['kind'] for e in s.events_of(a)] == ['move', 'move']


def test_replacement_keeps_history_and_current_view():
    s = Store()
    t = s.add('task', {'title': 'T'}, at=1, source='ctm')
    c1 = s.add('constraint', {'statement': 'limit 2000h/day', 'kind': 'task'}, at=2, source='user', turn=10)
    s.link(c1, 'about', t, at=2, source='ctm')
    c2 = s.add('constraint', {'statement': 'limit 20GB/day', 'kind': 'task'}, at=8, source='user', turn=40)
    s.link(c2, 'about', t, at=8, source='ctm')
    s.replace(c1, c2, at=8, source='ctm')
    at7 = [c['id'] for c in s.items('constraint', about=t, at=7, current_only=True)]
    at9 = [c['id'] for c in s.items('constraint', about=t, at=9, current_only=True)]
    assert at7 == [c1] and at9 == [c2]
    assert s.get(c1)['replaced_by'] == c2
    assert len(s.items('constraint', about=t, at=9)) == 2      # history still there


def test_merge_moves_children_and_segments():
    s = Store()
    a = s.add('task', {'title': 'A'}, at=1, source='ctm')
    d = s.add('task', {'title': 'A again'}, at=2, source='ctm')
    c = s.add('task', {'title': 'child of dup'}, at=3, source='ctm')
    s.set_parent(c, d, at=3, source='ctm')
    seg = s.add('segment', {'text': 'msg'}, at=3, source='user', turn=3)
    s.link(seg, 'about', d, at=3, source='ctm')
    s.merge(a, d, at=4, source='maintenance')
    assert s.resolve(d) == a
    assert s.parent(c) == a
    assert s.about(seg) == [a]
    assert d not in [n['id'] for n in s.work_nodes()]
    assert d in [n['id'] for n in s.work_nodes(at=3.5)]


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
