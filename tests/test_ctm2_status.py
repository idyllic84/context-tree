"""Maintenance V11 (concept 3.4 status): works left in progress for a while are listed for the status review with what failed
and what was verified; a work judged ended gets its status and its result folds up to the parent. Model calls are stubbed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree
from context_tree.ctm2 import maintain_store as MS, lifecycle as L, root as R

H = 3600.0


def test_status_review_lists_left_works_and_ends_them():
    s = Store(); R.ensure_root(s); t = StoreTree(s)
    g1 = t.add('Transcribe files', 'Transcribe files', None, None, 0, 0.0, kind='goal')
    g2 = t.add('Write the weekly report', 'Write the weekly report', None, None, 0, 0.0, kind='goal')
    a = t.add('Transcribe three files', 'Transcribe three files', g1, None, 1, 1 * H)
    b = t.add("Write this week's report", "Write this week's report", g2, None, 2, 20 * H)
    L.set_status(s, a, 'running', at=1 * H, source='ctm'); L.set_status(s, b, 'running', at=20 * H, source='ctm')
    p = s.add('progress', {'done': 'The three files are transcribed', 'open': [], 'failed': ['the first edit was not applied to the file'], 'verified': 'ran the check script'},
              at=1 * H + 60, source='ctm', turn=1)
    s.link(p, 'about', a, at=1 * H + 60, source='ctm')
    s.event('ROOT', 'maintenance', at=10 * H, source='maintenance', data={})     # the last run: A's records are older
    seg = s.add('segment', {'text': 'Finish the weekly report'}, at=20 * H, source='user', turn=2)
    s.link(seg, 'about', b, at=20 * H, source='ctm')
    seen = {}

    def stub(system, payload, **kw):
        if kw.get('role') != 'maintain4': return {}, {}              # the structure look-back finds nothing to change here
        seen['system'], seen['payload'] = system, payload
        return {'analysis': '', 'ops': [{'op': 'set_status', 'node': a, 'status': 'reported_done', 'evidence_turns': [1],
                                         'why': 'after the transcription the user moved on to the weekly report and did not come back for a long time'}]}, {}
    old_ask = MS.ask
    try:
        MS.ask = stub
        MS.maintain_store(s, t, 21 * H, model='stub')
    finally:
        MS.ask = old_ask
    review = seen['payload'].get('status_review') or []
    assert [c['id'] for c in review] == [a], review                      # the work left for 20 hours, not the active one
    assert review[0]['latest_results'][0]['failed'] == ['the first edit was not applied to the file'] and review[0]['latest_results'][0]['verified']
    assert L.status(s, a) == 'reported_done'
    assert any('The three files are transcribed' in r['data'].get('statement', '') for r in s.items('result', about=g1))   # folded up to the goal
    print('PASS status_review_lists_left_works_and_ends_them')


def test_reclassify_guidance():
    """Imported guidance that is really a hard requirement becomes a constraint on the same work; the guidance is replaced by it."""
    s = Store(); R.ensure_root(s); t = StoreTree(s)
    w = t.add('Remove redundant checks', 'clean up', None, None, 1, 1.0)
    g1 = s.add('guidance', {'statement': 'Confirm with the user before deleting other similar redundant checks'}, at=1.5, source='user', turn=1); s.link(g1, 'about', w, at=1.5, source='ctm')
    g2 = s.add('guidance', {'statement': 'You can follow the earlier clean-ups'}, at=1.6, source='user', turn=1); s.link(g2, 'about', w, at=1.6, source='ctm')
    old = MS.ask
    try:
        MS.ask = lambda system, payload, **kw: ({'items': [{'id': g1, 'class': 'constraint'}, {'id': g2, 'class': 'guidance'}]}, {})
        res = MS.reclassify_guidance(s, [{'id': g1, 'statement': '..'}, {'id': g2, 'statement': '..'}], model='stub', apply=True, at=2.0)
    finally:
        MS.ask = old
    assert res == {g1: 'constraint', g2: 'guidance'}
    cons = s.items('constraint', current_only=True)
    assert len(cons) == 1 and cons[0]['data']['from_guidance'] == g1 and s.about(cons[0]['id']) == [w]
    assert [g['id'] for g in s.items('guidance', current_only=True)] == [g2]
    print('PASS reclassify_guidance')


if __name__ == '__main__':
    test_status_review_lists_left_works_and_ends_them()
    test_reclassify_guidance()
