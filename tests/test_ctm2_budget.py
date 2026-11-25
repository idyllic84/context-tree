"""Control layer budget (concept 5.2 item 4): an executor that keeps stopping without doing anything, keeps being continued,
or repeats the same error is stopped and escalated. Progress is observed (tool use), not judged."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import execution as X


def _run():
    s = Store(); r = s.add('run', {'mode': 'session', 'status': 'active', 'state': 'busy'}, at=0.0, source='ctm')
    return s, r


def test_no_progress_and_too_many():
    s, r = _run()
    for t in (1.0, 2.0):
        s.event(r, 'auto_continue', at=t, source='ctm'); assert X.budget_check(s, r, at=t) is None
    s.event(r, 'auto_continue', at=3.0, source='ctm')
    assert X.budget_check(s, r, at=3.0)['reason'] == 'no_progress'
    # the executor works between continues (tool use): not stalled, but the total since the user's message is capped
    s, r = _run()
    for k in range(1, X.MAX_AUTO_CONTINUE):
        s.event(r, 'activity', at=float(k), source='executor'); s.event(r, 'auto_continue', at=float(k), source='ctm')
        assert X.budget_check(s, r, at=float(k)) is None
    k = X.MAX_AUTO_CONTINUE
    s.event(r, 'activity', at=float(k), source='executor'); s.event(r, 'auto_continue', at=float(k), source='ctm')
    assert X.budget_check(s, r, at=float(k))['reason'] == 'too_many_continues'
    # the user's new message to the executor starts the count again
    m = s.add('segment', {'text': 'Go on, change it the way I said'}, at=20.0, source='user'); X.forward(s, run_id=r, item_id=m, at=20.0, why="the user's new message")
    s.event(r, 'auto_continue', at=21.0, source='ctm')
    assert X.budget_check(s, r, at=21.0) is None
    print('PASS no_progress_and_too_many')


def test_repeated_error():
    s, r = _run()
    assert X.budget_check(s, r, at=1.0, error='E1: timeout') is None
    assert X.budget_check(s, r, at=2.0, error='E1: timeout')['reason'] == 'repeated_error'
    print('PASS repeated_error')


if __name__ == '__main__':
    test_no_progress_and_too_many(); test_repeated_error()
