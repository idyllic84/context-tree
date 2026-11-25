"""Offline walk-through of the round-7 message flow (concept 5.1) with stubbed model calls:
pointing and objects -> candidates (recent, live, objects incl. an identifier typo) -> delivery (a second call over every
work when asked) -> records, mentions, dispatch -> memory after dispatch (constraint on the work, replacement) -> reply."""
from context_tree.ctm2 import pipeline as P
from context_tree.ctm2 import ref as REF, deliver as DV, remember as RM
from context_tree.ctm2 import lifecycle as L
from context_tree.ctm2.store import Store

H = 3600.0


def stub_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 64
        for ch in t: v[ord(ch) % 64] += 1.0
        out.append(v)
    return out


class Script:
    """Answers per role from queues the test fills; records each payload."""
    def __init__(self): self.q, self.seen = {}, []

    def __call__(self, system, payload, **kw):
        self.seen.append((kw.get('role'), payload))
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def setup():
    sc = Script()
    REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=stub_embed)
    return s, ctm, sc


def test_flow2_objects_typo_side_question_memory():
    s, ctm, sc = setup()
    # 1. new work naming a file; memory records a task constraint after dispatch
    sc.q['ref'] = [{'modes': ['new'], 'entities': [{'said': 'transport/retry_policy.py', 'resolved': 'transport/retry_policy.py', 'type': 'identifier', 'role': 'target'}]}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Retry policy', 'purpose': 'change the retry policy'}, 'session': 'new'}], }]
    sc.q['remember'] = [lambda p: {'constraints': [{'statement': 'only change the transport directory', 'kind': 'task', 'node': p['deliveries'][0]['node'], 'replaces': []}]}]
    r = ctm.on_message(0, 0.0, 'Change the retry policy in transport/retry_policy.py, only change the transport directory', recent=[], previous_reply='', working_dir='D:/r')
    x = r['node']
    assert r['dispatches'][0]['reused'] is False and 'only change the transport directory' in r['dispatches'][0]['context']
    c1 = [c for c in s.items('constraint', about=x, current_only=True)]
    assert len(c1) == 1
    # 2. another new work
    sc.q['ref'] = [{'modes': ['new'], 'entities': [{'said': 'deployment document', 'resolved': 'deployment document', 'type': 'artifact', 'role': 'target'}]}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'deployment document', 'purpose': 'write the deployment document'}}]}]
    r2 = ctm.on_message(1, 1 * H, 'Also write a deployment document', recent=[{'user': '..', 'agent': '..', 'node': x}], previous_reply='', working_dir='D:/r')
    y = r2['node']
    assert y != x and not s.items('constraint', about=y, current_only=True)
    # 3. a day later the user names the first file with a typo: the objects source finds the work; memory replaces the constraint
    sc.q['ref'] = [{'modes': ['named'], 'entities': [{'said': 'transport/retry_polcy.py', 'resolved': 'transport/retry_polcy.py', 'type': 'identifier', 'role': 'target'}]}]
    def pick(p):
        hit = [c for c in p['candidates'] if any('identifier' in x for x in c['sources'])]
        return {'deliveries': [{'part': 'all', 'to': 'existing', 'node': hit[0]['id']}]}
    sc.q['deliver'] = [pick]
    sc.q['remember'] = [lambda p: {'constraints': [{'statement': 'the transport and config directories may be changed', 'kind': 'task', 'node': p['deliveries'][0]['node']}]}]
    sc.q['replace'] = [lambda p: {'items': [{'new': 0, 'replaces': [c['id'] for c in p['new'][0]['similar'] if c['type'] == 'constraint'][:1]}]}]
    r3 = ctm.on_message(2, 26 * H, 'Set the timeout in transport/retry_polcy.py to 30 seconds; the config directory may be changed too', recent=[], previous_reply='', working_dir='D:/r')
    assert r3['node'] == x and r3['dispatches'][0]['reused'] is True
    assert [c['data']['statement'] for c in s.items('constraint', about=x, current_only=True)] == ['the transport and config directories may be changed']
    assert any('similar identifier' in t for t in dict(r3['understanding']['candidates'])[x])
    # 4. a side question about the document work: read-only, the work's status is untouched
    st = L.status(s, y)
    sc.q['ref'] = [{'modes': ['named'], 'entities': [{'said': 'deployment document', 'resolved': 'deployment document', 'type': 'artifact', 'role': 'target'}]}]
    sc.q['deliver'] = [lambda p: {'deliveries': [{'part': 'all', 'to': 'side', 'node': y}]}]
    r4 = ctm.on_message(3, 27 * H, 'How far is the deployment document now?', recent=[], previous_reply='', working_dir='D:/r')
    assert r4['queries'] and r4['dispatches'][0]['readonly'] and L.status(s, y) == st
    # 5. none fits: the second call sees every work
    sc.q['ref'] = [{'modes': ['past'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [], 'wider': 'none of the candidates'}]
    sc.q['deliver-wide'] = [lambda p: {'deliveries': [{'part': 'all', 'to': 'existing', 'node': p['all_works'][-1]['id']}]}]
    r5 = ctm.on_message(4, 28 * H, 'Go on with the one from last time too', recent=[], previous_reply='', working_dir='D:/r')
    assert r5['understanding']['wider'] and r5['node'] in (x, y)
    assert any(role == 'deliver-wide' and 'all_works' in p for role, p in sc.seen)


def test_flow2_ui_selection_and_mentions():
    s, ctm, sc = setup()
    sc.q['ref'] = [{'modes': ['new'], 'entities': [{'said': 'region-x', 'resolved': 'routing in region-x', 'type': 'object', 'role': 'target'}]}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Routing fix', 'purpose': 'fix the region-x routing'}}]}]
    x = ctm.on_message(0, 0.0, 'Fix the routing of region-x', recent=[], previous_reply='', working_dir='D:/r')['node']
    assert [m['data']['said'] for m in s.items('mention', about=x)] == ['region-x']
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [lambda p: {'deliveries': [{'part': 'all', 'to': 'existing', 'node': 'N999'}]}]
    r = ctm.on_message(1, H, 'Go on', recent=[], previous_reply='', working_dir='D:/r', ui_selection=x)
    assert r['node'] == x and r['dispatches'][0]['reused']
    assert [c['id'] for c in [p for r_, p in sc.seen if r_ == 'deliver'][-1]['candidates']] == [x]


def test_flow2_object_family_and_alternatives():
    s, ctm, sc = setup()
    sc.q['ref'] = [{'modes': ['new'], 'entities': [{'said': 'guide.md', 'resolved': 'guide.md', 'type': 'identifier', 'role': 'target'}]}] * 2
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Write the query guide', 'purpose': 'write the guide'}}]},
                       {'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Add a latency analysis', 'purpose': 'add a latency section'}}]}]
    a = ctm.on_message(0, 0.0, 'Write the query guide in guide.md', recent=[], previous_reply='', working_dir='D:/r')['node']
    b = ctm.on_message(1, H, 'Add a latency analysis section to guide.md', recent=[], previous_reply='', working_dir='D:/r')['node']
    sc.q['ref'] = [{'modes': ['named'], 'entities': [{'said': 'guide.md', 'resolved': 'guide.md', 'type': 'identifier', 'role': 'target'}]}]
    def pick(p):
        fam = p['object_groups'][0]['works']
        assert {w['id'] for w in fam} == {a, b}            # the whole family, not the most recent one only
        return {'deliveries': [{'part': 'all', 'to': 'existing', 'node': a, 'alternatives': [b]}]}
    sc.q['deliver'] = [pick]
    r = ctm.on_message(2, 30 * H, 'Group the query examples in guide.md by region', recent=[], previous_reply='', working_dir='D:/r')
    assert r['node'] == a and 'it may also be: Add a latency analysis' in r['relay']
    assert s.get('SEG2-0')['data']['alternatives'] == [b]


def test_flow2_questioned_decision_and_decision_objects():
    s, ctm, sc = setup()
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Investigate latency', 'purpose': 'find the cause of the latency'}}]}]
    sc.q['remember'] = [lambda p: {'decisions': [{'statement': 'the agent thinks the latency comes from the network; the user questions its grounds', 'type': 'questioned', 'node': p['deliveries'][0]['node']},
                                                 {'statement': 'use the segmented cache plan', 'type': 'decision', 'node': p['deliveries'][0]['node']}]}]
    r = ctm.on_message(0, 0.0, 'How do you know it is the network? Go with the segmented cache first', recent=[], previous_reply='', working_dir='D:/r')
    x = r['node']
    from context_tree.ctm2 import context as C
    text = C.initial_context(s, x, turn=1, at=H, message='Go on')
    doubted = text.split('## Conclusions the user questioned, not yet verified (verify before use)')[1].split('## ')[0]
    assert 'latency comes from the network' in doubted and 'latency comes from the network' not in text.split('## Replaced or rejected approaches (do not use again)')[1].split('## ')[0]
    assert 'use the segmented cache plan' in text.split('## Constraints and decisions in force')[1].split('## ')[0]
    from context_tree.ctm2 import candidates as CA
    hits = CA.object_hits(s, {'entities': [{'said': 'the cache plan we settled', 'resolved': 'use the segmented cache plan', 'type': 'artifact', 'role': 'target'}]}, embed=stub_embed)
    assert any(o['kind'] == 'decision' and x in o['works'] for o, _, _ in hits[:3])


def test_flow2_working_directory_of_new_work():
    """CTM decides where a new work runs: a directory the message names, else the work it is part of, else the project the
    user's words point to among known directories (LLM), else none (the pilot gives it a scratch directory)."""
    import tempfile, os
    s, ctm, sc = setup()
    P.ask = sc
    repo = tempfile.mkdtemp().replace(os.sep, '/'); other = tempfile.mkdtemp().replace(os.sep, '/')
    a = ctm.tree.add('Change the retries in repository A', 'change the retries', None, None, 0, 0.0, working_dir=repo)
    # part of an existing work: its directory
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Add tests', 'purpose': 'add tests for the retries', 'parent': a}}]}]
    r1 = ctm.on_message(1, 1 * H, 'Also add a test for the retries', recent=[], previous_reply='', working_dir='', dispatch=False)
    assert ctm.tree.nodes[r1['node']].working_dir == repo
    # the message names an existing directory
    sc.q['ref'] = [{'modes': ['new'], 'entities': [{'said': other, 'resolved': other, 'type': 'identifier', 'role': 'target'}]}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'New project', 'purpose': 'start a new project in another directory'}}]}]
    r2 = ctm.on_message(2, 2 * H, f'In {other}, start a new project', recent=[], previous_reply='', working_dir='', dispatch=False)
    assert ctm.tree.nodes[r2['node']].working_dir == other
    # a new top-level work: the project is judged from the user's words among the known directories
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}, {'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': "Change A's logging", 'purpose': 'add logging'}}]},
                       {'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Write the weekly report', 'purpose': "write this week's report"}}]}]
    sc.q['workdir'] = [lambda p: {'dir': next(d['dir'] for d in p['directories'] if d['dir'] == repo)}, {'dir': None}]
    r3 = ctm.on_message(3, 3 * H, 'Add some logging in repository A', recent=[], previous_reply='', working_dir='', dispatch=False)
    assert ctm.tree.nodes[r3['node']].working_dir == repo
    r4 = ctm.on_message(4, 4 * H, "Write this week's report for me", recent=[], previous_reply='', working_dir='', dispatch=False)
    assert ctm.tree.nodes[r4['node']].working_dir == ''



if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
