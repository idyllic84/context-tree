"""Memory scope and what new works build on: global rules, object rules with and without a project directory, `uses` of
research, works and recent queries, and the polarity the replacement step sees. Model calls are stubbed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM, maintain_store as MS, scope as SC

H = 3600.0


class Script:
    def __init__(self): self.q = {}

    def __call__(self, system, payload, **kw):
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def test_global_rule_replaced_without_target():
    """A message delivered to no work can still change a global rule: the replacement check sees the root's rules."""
    from context_tree.ctm2 import root as R
    from context_tree.ctm2.tree import StoreTree
    s = Store(); R.ensure_root(s); t = StoreTree(s)
    cid = s.add('constraint', {'statement': "Function names start with 'a_'", 'kind': 'global'}, at=1.0, source='user', turn=1)
    s.link(cid, 'about', 'ROOT', at=1.0, source='ctm')
    cur = RM.current_items(s, t, [], 2.0, '')
    assert [r['id'] for r in cur] == [cid]
    print('PASS global_rule_replaced_without_target')


def test_object_rule_with_project_is_an_object_rule():
    """An object rule stated in a project directory lives with its object (indexed for ctm.md), not on a work or the root."""
    from context_tree.ctm2 import root as R
    from context_tree.ctm2.tree import StoreTree
    s = Store(); R.ensure_root(s); t = StoreTree(s)
    out = {'constraints': [{'statement': 'Every section in ctm.md has a date', 'kind': 'object', 'scope': 'ctm.md'}]}
    RM.write(s, t, out, turn=2, at=2.0, working_dir='D:/proj', model='stub', current_ids=set())
    c2 = [x for x in s.items('constraint', current_only=True) if 'ctm.md' in x['data']['statement']][0]
    assert c2['data']['kind'] == 'object' and s.about(c2['id']) != ['ROOT']
    print('PASS object_rule_with_project_is_an_object_rule')


def test_new_work_uses_research_and_work():
    """deliver V8 uses: a new work that builds on a research item and on another work gets their conclusions in its context."""
    from context_tree.ctm2 import context as C
    sc = Script()
    REF.ask = DV.ask = RM.ask = MS.ask = SC.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[float(len(t) % 7), 1.0] for t in ts])
    rid = s.add('research', {'title': 'Dividend stock day-trading research', 'status': 'done', 'doc': None, 'summary': 'on days the market drops, dividend stocks often rise'}, at=1.0, source='ctm', turn=1)
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Backtest data', 'purpose': 'prepare the data'}}]}]
    a = ctm.on_message(1, 1 * H, 'Prepare the backtest data', recent=[], previous_reply='', working_dir='D:/s')['node']
    ctm.on_reply(1, 1 * H + 1, a, '..', 'the data is in D:/s/data', tools=[], progress={'done': 'daily data downloaded to D:/s/data', 'open': [], 'failed': []})
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Write the backtest script', 'purpose': 'backtest the day-trading strategy', 'uses': [rid, a]}}]}]
    r = ctm.on_message(2, 2 * H, 'Write the backtest following the research', recent=[], previous_reply='', working_dir='D:/s')
    b = r['node']
    used = {d for (d,) in s.db.execute("select dst from edges where src=? and rel='uses'", (b,))}
    assert used == {rid, a}, used
    ctx = next(d['context'] for d in r['dispatches'] if d.get('context'))
    assert 'Dividend stock day-trading research' in ctx and 'daily data downloaded to D:/s/data' in ctx
    print('PASS new_work_uses_research_and_work')


def test_object_rule_without_project_kept_on_its_work():
    """An object rule with no project directory stays on the work it was said for (concept 3.5: an object without files yet);
    its subtree inherits it and unrelated works do not."""
    from context_tree.ctm2 import root as R
    from context_tree.ctm2.tree import StoreTree
    s = Store(); R.ensure_root(s); t = StoreTree(s)
    w = t.add('Plan the course website', 'plan the website', None, None, 1, 1.0)
    out = {'constraints': [{'statement': 'the website does not show a certain brand', 'kind': 'object', 'scope': 'the course website', 'node': w}]}
    RM.write(s, t, out, turn=2, at=2.0, working_dir='', model='stub', current_ids=set())
    c = s.items('constraint', current_only=True)[0]
    assert c['data']['kind'] == 'task' and c['data'].get('stated_kind') == 'object' and s.about(c['id']) == [w], (c, s.about(c['id']))
    print('PASS object_rule_without_project_kept_on_its_work')


def test_new_work_uses_recent_query():
    """A work created after the user asked questions names the query it builds on; its executor gets the answer (concept 5.3
    item 5). The delivery is given the recent queries with every prompt version (an identity check once dropped them)."""
    sc = Script()
    REF.ask = DV.ask = RM.ask = MS.ask = SC.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[float(len(t) % 7), 1.0] for t in ts])
    if True:
        q = s.add('query', {'question': 'Is there a Redis connection in the project', 'answered': True, 'answer': 'The Redis connection is in app/cache.py, used for the task queue'}, at=1 * H, source='ctm', turn=1)
        s.link(q, 'about', 'ROOT', at=1 * H, source='ctm')
        seen = {}
        def deliver_out(p):
            seen['queries'] = p.get('recent_queries')
            return {'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Add retries to the task queue', 'purpose': 'retries', 'uses': [q]}}]}
        sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
        sc.q['deliver'] = [deliver_out]
        r = ctm.on_message(2, 2 * H, 'Then add retries to the task queue', recent=[], previous_reply='', working_dir='D:/p')
    assert seen['queries'] and seen['queries'][0]['id'] == q
    ctx = next(d['context'] for d in r['dispatches'] if d.get('context'))
    assert 'The Redis connection is in app/cache.py' in ctx, ctx[-800:]
    print('PASS new_work_uses_recent_query')


def test_replacement_step_sees_the_polarity_of_new_items():
    """A rejected approach is shown as rejected to the replacement step, as the current items are; otherwise it reads as a new
    requirement contradicting the rule the user just restated."""
    from context_tree.ctm2 import remember as RM2
    from context_tree.ctm2.store import Store as S2
    st = S2(); cid = st.add('constraint', {'statement': 'leave all the old paths unchanged', 'kind': 'task'}, at=1.0, source='user', turn=1)
    seen = {}
    def fake(system, payload, **kw):
        seen.update(payload); return {'items': [{'new': 0, 'replaces': []}]}, {}
    old = RM2.ask; RM2.ask = fake
    try:
        RM2.check_replacements(st, {'decisions': [{'statement': 'keep only one path unchanged', 'type': 'rejected'}]}, current=[st.get(cid)],
                               embed=lambda ts: [[1.0, 0.0] for _ in ts], model='stub')
    finally:
        RM2.ask = old
    assert seen['new'][0]['type'] == 'decision (rejected)', seen['new'][0]
    print('PASS replacement_step_sees_the_polarity_of_new_items')


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
