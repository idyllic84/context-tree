"""The planner in the live flow (concept 3.4, S5): a staged deliverable is split into subtasks; authorized ones run now,
the rest are proposals; an approval starts the executable ones, not the whole work. Model calls are stubbed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM, planner as PL, lifecycle as L

H = 3600.0


class Script:
    def __init__(self): self.q = {}
    def __call__(self, system, payload, **kw):
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def test_plan_authorized_runs_rest_waits_for_approval():
    sc = Script(); REF.ask = DV.ask = RM.ask = PL.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Export feature', 'purpose': 'Build the export feature', 'plan': True}}]}]
    sc.q['planner'] = [{'subtasks': [{'key': 's1', 'title': 'Design the export format', 'output': 'design document', 'authorized_by_user': True},
                                     {'key': 's2', 'title': 'Implement the export', 'output': 'code', 'depends': [{'on': 's1', 'type': 'serial'}]}]}]
    r = ctm.on_message(0, 0.0, 'Finish the export feature: design the format first, then implement it', recent=[], previous_reply='', working_dir='D:/r')
    x = r['node']
    pl = r['planned'][0]
    assert pl['task'] == x and [c['title'] for c in pl['subtasks']] == ['Design the export format', 'Implement the export']
    s1, s2 = [c['id'] for c in pl['subtasks']]
    assert [d['task'] for d in r['dispatches']] == [s1]                       # only the authorized step runs
    assert L.status(s, s2) == 'proposed'
    # the user approves in the conversation; the first step finishes; the second becomes executable and runs
    L.set_status(s, s1, 'reported_done', at=1 * H, source='ctm')
    sc.q['ref'] = [{'modes': ['display'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'control', 'node': x, 'control': 'approve'}]}]
    r2 = ctm.on_message(1, 2 * H, 'OK, go with this plan', recent=[], previous_reply='', working_dir='D:/r')
    assert L.status(s, s2) in ('ready', 'running') and [d['task'] for d in r2['dispatches']] == [s2]
    print('PASS plan_authorized_runs_rest_waits_for_approval')


if __name__ == '__main__':
    test_plan_authorized_runs_rest_waits_for_approval()
