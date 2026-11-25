"""Conditional dependencies (concept 3.4): the progress summary of the predecessor's reply judges the waiting conditions,
only when there are such conditions (otherwise the summary call is unchanged). Model calls are stubbed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import pipeline as P, lifecycle as L


def test_condition_judged_with_the_summary():
    s = Store(); ctm = P.CTM(s, model='stub')
    a = ctm.tree.add('Implement', 'Implement the feature', None, None, 0, 0.0); b = ctm.tree.add('Open a PR', 'Open a PR once the tests pass', None, None, 1, 1.0)
    L.set_status(s, a, 'running', at=1.0, source='ctm'); L.set_status(s, b, 'pending', at=1.0, source='ctm')
    L.add_dep(s, a, b, at=2.0, source='planner', kind='conditional', condition='all tests pass')
    c = ctm.tree.add('Other', 'unrelated work', None, None, 2, 2.0)
    seen = []
    def stub(user, reply, tools, *, model, prompt=None, effort='low', conditions=None):
        seen.append(conditions)
        out = {'done': 'Ran the tests, all passed', 'changed': [], 'verified': 'traced', 'open': [], 'failed': []}
        if conditions: out['conditions_met'] = [{'successor': conditions[0]['successor'], 'met': True, 'why': 'all tests pass'}]
        return out, {}
    old = P.summarize; P.summarize = stub
    try:
        ctm.on_reply(3, 10.0, a, 'run the tests', 'all tests pass', tools=[])
        assert seen[-1] and seen[-1][0]['successor'] == b and seen[-1][0]['condition'] == 'all tests pass'
        assert L.status(s, b) == 'pending'                       # the predecessor is not finished yet
        L.set_status(s, a, 'reported_done', at=11.0, source='ctm')
        assert L.status(s, b) == 'ready'
        ctm.on_reply(4, 12.0, c, 'Do something else', 'Done', tools=[])
        assert not seen[-1]                                       # no waiting condition: the summary input is unchanged
    finally:
        P.summarize = old
    print('PASS condition_judged_with_the_summary')


def test_condition_not_met_keeps_waiting():
    s = Store(); ctm = P.CTM(s, model='stub')
    a = ctm.tree.add('Implement', 'Implement the feature', None, None, 0, 0.0); b = ctm.tree.add('Open a PR', 'Open a PR once the tests pass', None, None, 1, 1.0)
    L.set_status(s, a, 'running', at=1.0, source='ctm'); L.set_status(s, b, 'pending', at=1.0, source='ctm')
    L.add_dep(s, a, b, at=2.0, source='planner', kind='conditional', condition='all tests pass')
    old = P.summarize
    P.summarize = lambda *x, **k: ({'done': '2 tests failed', 'conditions_met': [{'successor': b, 'met': False}]}, {})
    try:
        ctm.on_reply(3, 10.0, a, 'run the tests', '2 failed', tools=[])
        L.set_status(s, a, 'reported_done', at=11.0, source='ctm')
        assert L.status(s, b) == 'pending'
    finally:
        P.summarize = old
    print('PASS condition_not_met_keeps_waiting')


if __name__ == '__main__':
    test_condition_judged_with_the_summary(); test_condition_not_met_keeps_waiting()
