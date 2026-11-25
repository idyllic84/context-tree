"""Maintenance moves messages to the work they belong to (block C, PROMPT_V6)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree
from context_tree.ctm2 import maintain_store as MS, ui as UI


def _setup():
    s = Store(os.path.join(tempfile.mkdtemp(), 'm.sqlite')); tree = StoreTree(s)
    a = tree.add('A', 'work A', None, None, 1, 100.0); b = tree.add('B', 'work B', None, None, 2, 101.0)
    segs = {}
    for t in (1, 2, 3, 4):
        segs[t] = s.add('segment', {'text': f'm{t}', 'to': 'existing'}, at=100.0 + t, source='user', turn=t); s.link(segs[t], 'about', a, at=100.0 + t, source='ctm')
    c = s.add('constraint', {'statement': 'only for m3', 'kind': 'task'}, at=103.5, source='user', turn=3); s.link(c, 'about', a, at=103.5, source='ctm')
    return s, tree, a, b, segs, c


def test_move_and_split():
    s, tree, a, b, segs, c = _setup()
    out = MS.apply_ops(s, tree, [{'op': 'move_messages', 'turns': [3], 'to': b, 'why': 'x'}], 200.0)
    assert out and out[0]['moved'] == [3]
    assert s.about(segs[3], 201.0) == [b] and s.about(c, 201.0) == [b] and s.about(segs[1], 201.0) == [a]
    out = MS.apply_ops(s, tree, [{'op': 'split', 'node': a, 'turns': [4], 'title': 'C', 'purpose': 'work C', 'parent': None, 'why': 'y'}], 300.0)
    new = out[0]['to']
    assert new in tree.nodes and tree.nodes[new].title == 'C' and s.about(segs[4], 301.0) == [new]
    print('PASS move_and_split')


def test_user_reattached_segment_stays():
    s, tree, a, b, segs, c = _setup()
    UI.reattach_segment(s, segs[2], b, at=150.0)
    out = MS.apply_ops(s, tree, [{'op': 'move_messages', 'turns': [2], 'to': a, 'why': 'z'}], 200.0)
    assert not out and s.about(segs[2], 201.0) == [b]
    print('PASS user_reattached_segment_stays')


if __name__ == '__main__':
    test_move_and_split(); test_user_reattached_segment_stays()
