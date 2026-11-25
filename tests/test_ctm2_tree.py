"""Offline tests for the ctm2 replay tree (no model calls)."""
from context_tree.ctm2.maintain_store import _creates_cycle
from context_tree.ctm2.tree import Tree


def build():
    t = Tree()
    a = t.add('A', 'goal a', None, None, 0, 0.0)
    b = t.add('B', 'step of a', a, None, 1, 10.0)
    c = t.add('C', 'another step of a', a, b, 2, 20.0)
    d = t.add('D', 'unrelated', None, None, 3, 30.0)
    return t, a, b, c, d


def test_merge_moves_children_and_aliases():
    t, a, b, c, d = build()
    e = t.add('E', 'child of d', d, None, 4, 40.0)
    t.merge(a, d)
    assert d not in t.nodes and t.resolve(d) == a
    assert t.nodes[e].parent == a
    assert t.nodes[a].last_time == 40.0 or t.nodes[a].last_time == 30.0


def test_ids_stay_unique_after_merge():
    t, a, b, c, d = build()
    t.merge(a, d)
    new = t.add('F', '', None, None, 5, 50.0)
    assert new not in (a, b, c, d) and new in t.nodes


def test_outline_around_keeps_candidate_chain_and_siblings():
    t, a, b, c, d = build()
    ids = [o['id'] for o in t.outline_around([b], 60.0, max_tops=1)]
    assert d in ids            # most recently active top-level node
    assert a in ids and b in ids and c in ids   # candidate, its ancestor and its sibling


def test_cycle_check():
    t, a, b, c, d = build()
    assert _creates_cycle(t, a, b)
    assert not _creates_cycle(t, d, a)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
