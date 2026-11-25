'A message that names a time ("last time", "the first version") gets the work\'s earlier attempts in what the executor receives;\nthe executor resolves which one the user means (concept 4). Model calls are stubbed.'
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM, lifecycle as L

H = 3600.0


class Script:
    def __init__(self): self.q = {}
    def __call__(self, system, payload, **kw):
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def test_time_reference_brings_attempts():
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Tune parameters', 'purpose': 'tune the parameters'}}]}]
    x = ctm.on_message(0, 0.0, 'Tune the parameters a bit', recent=[], previous_reply='', working_dir='D:/r')['node']
    for k, (done, failed) in enumerate([('first version: threshold 0.5', []), ('second version: threshold 0.7', ['threshold 0.9 too aggressive'])]):
        ctm.on_reply(k + 1, (k + 1) * H, x, 'Tune parameters', 'ok', tools=[], progress={'done': done, 'changed': [], 'verified': 'self-reported', 'open': [], 'failed': failed})
    sc.q['ref'] = [{'modes': ['time'], 'entities': [], 'time_refs': [{'phrase': 'the first version', 'hours_ago': None}]}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'existing', 'node': x}]}]
    r = ctm.on_message(5, 5 * H, "Go back to the first version's approach", recent=[], previous_reply='', working_dir='D:/r')
    sent = r['dispatches'][0].get('forward') or r['dispatches'][0].get('context')
    assert 'Earlier executions of this work' in sent and 'first version: threshold 0.5' in sent and 'threshold 0.9 too aggressive' in sent and '"the first version"' in sent
    # no time named: nothing extra
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'existing', 'node': x}]}]
    r = ctm.on_message(6, 6 * H, 'Go on', recent=[], previous_reply='', working_dir='D:/r')
    sent = r['dispatches'][0].get('forward') or r['dispatches'][0].get('context')
    assert 'Earlier executions of this work' not in sent
    print('PASS time_reference_brings_attempts')


def test_open_items_become_numbered_pending():
    """S2/S8: what a reply leaves for the user becomes numbered pending items of the work, shown as referable displays; the next
    reply of the same work supersedes them, and the delivery sees them among the open pending items."""
    from context_tree.ctm2 import relay
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    if True:
        s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
        sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
        sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Plan', 'purpose': 'settle the plan'}}]}]
        x = ctm.on_message(0, 0.0, 'Come up with a plan', recent=[], previous_reply='', working_dir='D:/r')['node']
        ctm.on_reply(1, H, x, 'Come up with a plan', 'ok', tools=[], progress={'done': 'gave two plans', 'open': ['choose A or B', 'whether to keep the old interface'], 'failed': []})
        opens = [q for q in relay.open_pending(s, H + 1, x) if q['data'].get('kind') == 'open_item']
        shown = [d for d in relay.recent_displays(s, H + 1) if d['kind'] == 'pending']
        assert [q['data']['what'] for q in opens] == ['choose A or B', 'whether to keep the old interface']
        assert [(d['no'], d['task']) for d in shown] == [(1, x), (2, x)]
        ctm.on_reply(2, 2 * H, x, 'Go on', 'ok', tools=[], progress={'done': 'did it as A', 'open': ['whether to open a PR'], 'failed': []})
        opens = [q['data']['what'] for q in relay.open_pending(s, 2 * H + 1, x) if q['data'].get('kind') == 'open_item']
        assert opens == ['whether to open a PR']


def test_reused_session_gets_turns_from_other_works():
    """S3: back in work A's session after talking to work B, the forward carries B's turns after A's last one (the session did
    not see them), and not A's own."""
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}] * 2 + [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Change interfaces', 'purpose': 'change interface A'}}]},
                       {'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'settle the plan', 'purpose': 'Settle plan B'}}]}]
    a = ctm.on_message(0, 0.0, 'Change interface A', recent=[], previous_reply='', working_dir='D:/r')['node']
    ctm.on_reply(0, 10.0, a, 'Change interface A', 'A is changed', tools=[], progress={'done': 'A is changed', 'open': [], 'failed': []})
    b = ctm.on_message(1, 20.0, 'plan B uses a cache', recent=[], previous_reply='', working_dir='D:/r')['node']
    ctm.on_reply(1, 30.0, b, 'plan B uses a cache', 'OK, use an LRU cache', tools=[], progress={'done': 'settled on an LRU cache', 'open': [], 'failed': []})
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'existing', 'node': a, 'session': 'continue'}]}]
    r = ctm.on_message(2, 40.0, 'Add the cache to interface A as just now', recent=[], previous_reply='', working_dir='D:/r')
    d = r['dispatches'][0]
    assert d.get('reused') and 'plan B uses a cache' in d['forward'] and 'Change interface A' not in d['forward'], d.get('forward')
    # a question about A answered from memory: the next forward to A carries the answer the user saw
    from context_tree.ctm2 import query as Q
    s.link(s.add('query', {'question': "What is A's timeout", 'answer': 'timeout 30 seconds', 'answered': True}, at=50.0, source='ctm', turn=3), 'about', a, at=50.0, source='ctm')
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'existing', 'node': a, 'session': 'continue'}]}]
    r = ctm.on_message(4, 60.0, 'Then make it 60 seconds', recent=[], previous_reply='', working_dir='D:/r')
    assert 'timeout 30 seconds' in r['dispatches'][0]['forward'], r['dispatches'][0]['forward']


def test_execution_view_lists_runs_with_replies():
    """The executions panel lists a run after its executor replied (a column shared by items and edges once broke it live)."""
    from context_tree.ctm2 import execution as X
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Change the configuration', 'purpose': 'Change the configuration'}}]}]
    r = ctm.on_message(0, 0.0, 'change the configuration', recent=[], previous_reply='', working_dir='D:/r')
    ctm.on_reply(0, 10.0, r['node'], 'change the configuration', 'changed', tools=[], run=r['dispatches'][0]['run'], progress={'done': 'changed', 'open': [], 'failed': []})
    v = X.execution_view(s)
    assert [x['task'] for x in v] == [r['node']], v


def test_words_to_ctm_itself_are_recorded_not_dispatched():
    """S15: 'remember ...' is CTM's own business: recorded by the memory call, sent to no executor; when it is about one work,
    the rule is placed there (its session gets it with the next forward)."""
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Change interfaces', 'purpose': 'Change interfaces'}}]}]
    a = ctm.on_message(0, 0.0, 'Change interface A', recent=[], previous_reply='', working_dir='D:/r')['node']
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'memory', 'node': None}]}]
    sc.q['remember'] = [{'constraints': [{'statement': 'Do not commit ctm.md', 'kind': 'global', 'validity': 'long_term', 'node': 'ROOT'}]}]
    r = ctm.on_message(1, 10.0, 'Remember globally: do not commit ctm.md', recent=[], previous_reply='', working_dir='D:/r')
    assert not r['dispatches'], r['dispatches']
    assert any(c['data'].get('statement') == 'Do not commit ctm.md' for c in s.items('constraint', about='ROOT', at=11.0)), 'recorded at the root'
    assert 'constraint (global): Do not commit ctm.md' in ctm.memory_note(1), ctm.memory_note(1)     # the conversation shows what was recorded
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'memory', 'node': a}]}]
    sc.q['remember'] = [lambda p: {'constraints': [{'statement': 'Comments of interface A in Chinese', 'kind': 'task', 'validity': 'long_term', 'node': a}]}]
    r2 = ctm.on_message(2, 20.0, 'From now on all comments in this task are in Chinese', recent=[], previous_reply='', working_dir='D:/r')
    assert not r2['dispatches'] and r2['node'] == a, (r2['dispatches'], r2['node'])
    print('PASS words_to_ctm_itself_are_recorded_not_dispatched')


if __name__ == '__main__':
    test_time_reference_brings_attempts()
    test_open_items_become_numbered_pending(); print('PASS open_items_become_numbered_pending')
    test_reused_session_gets_turns_from_other_works(); print('PASS reused_session_gets_turns_from_other_works')
    test_execution_view_lists_runs_with_replies(); print('PASS execution_view_lists_runs_with_replies')
    test_words_to_ctm_itself_are_recorded_not_dispatched()
