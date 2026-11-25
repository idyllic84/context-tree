"""Structure judgment (block C, 2026-11-12): one level of the tree, triggered by delivery's signal (same_work_as, a next step
beside a root-level work) and, in maintenance, by levels that gained works since their last judgment. Model calls are stubbed."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree
from context_tree.ctm2 import maintain_store as MS, ui as UI, pipeline as P, ref as REF, deliver as DV, remember as RM

H = 3600.0


class Script:
    def __init__(self): self.q, self.seen = {}, []

    def __call__(self, system, payload, **kw):
        self.seen.append((kw.get('role'), payload))
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def _tree():
    s = Store(os.path.join(tempfile.mkdtemp(), 's.sqlite')); tree = StoreTree(s)
    ids = {}
    for i, name in enumerate('ABCE'):
        ids[name] = tree.add(name, f'work {name}', None, None, i, 100.0 + i, working_dir='D:/p')
    ids['F'] = tree.add('F', 'work F', None, None, 9, 109.0, working_dir='D:/q')
    return s, tree, ids


def test_group_and_level():
    s, tree, n = _tree()
    out = {'groups': [{'title': 'G', 'purpose': 'A and B together', 'children': [n['A'], n['B'], n['F']], 'why': 'parts of G'}],
           'attach': [{'node': n['C'], 'parent': n['A'], 'why': 'not offered: ignored'}]}
    ops = MS.structure(s, tree, 200.0, model='stub', working_dir='D:/p', ask_fn=lambda *a, **k: (out, {}))
    g = ops[0]['node']
    assert tree.nodes[g].title == 'G' and tree.nodes[g].parent is None and tree.nodes[g].working_dir == 'D:/p'
    assert tree.nodes[n['A']].parent == g and tree.nodes[n['B']].parent == g
    assert tree.nodes[n['F']].parent is None                      # another project's level: not touched
    assert tree.nodes[n['C']].parent is None and tree.nodes[n['E']].parent is None
    assert s.db.execute("select count(*) from events where item='ROOT' and kind='structure'").fetchone()[0] == 1
    print('PASS group_and_level')


def test_guards():
    s, tree, n = _tree()
    UI.rename(s, n['B'], 'B2', at=150.0)                         # the user edited B: it stays
    out = {'groups': [{'title': 'G', 'children': [n['A'], n['B']]}, {'title': 'H', 'children': [n['C'], n['E']]}]}
    ops = MS.structure(s, tree, 200.0, model='stub', working_dir='D:/p', ask_fn=lambda *a, **k: (out, {}))
    assert [o['title'] for o in ops] == ['H'] and tree.nodes[n['B']].parent is None   # G kept one movable work only
    # a judgment triggered by a new work changes only groups that involve it
    s, tree, n = _tree()
    out = {'groups': [{'title': 'G', 'children': [n['A'], n['B']]}, {'title': 'H', 'children': [n['C'], n['E']]}]}
    ops = MS.structure(s, tree, 200.0, model='stub', working_dir='D:/p', trigger='new_work', focus=[n['E']],
                       ask_fn=lambda *a, **k: (out, {}))
    assert [o['title'] for o in ops] == ['H'] and tree.nodes[n['A']].parent is None
    # titled like one of its works: that work becomes the larger one, no wrapper
    s, tree, n = _tree()
    out = {'groups': [{'title': 'A', 'children': [n['A'], n['B']]}]}
    ops = MS.structure(s, tree, 200.0, model='stub', working_dir='D:/p', ask_fn=lambda *a, **k: (out, {}))
    assert ops[0]['op'] == 'group_under' and tree.nodes[n['B']].parent == n['A'] and tree.nodes[n['A']].parent is None
    print('PASS guards')


def test_maintenance_trigger():
    s, tree, n = _tree()
    for t, k in ((20, 'A'), (21, 'B')):
        sid = s.add('segment', {'text': f'm{t}', 'to': 'existing'}, at=300.0 + t, source='user', turn=t); s.link(sid, 'about', n[k], at=300.0 + t, source='ctm')
    sc = Script(); old = MS.ask; MS.ask = sc
    try:
        sc.q['maintain4'] = [{'ops': []}]
        sc.q['goals'] = [lambda p: {'new_goals': [{'key': 'g1', 'title': 'G', 'purpose': 'long-term'}],
                                    'assign': [{'work': w['id'], 'goal': 'g1'} for w in p['works']]}]
        sc.q['structure'] = [lambda p: {'groups': [{'title': 'T', 'children': [w['id'] for w in p['works']][:2], 'why': 'x'}]}]
        ops, _ = MS.maintain_store(s, tree, 400.0, model='stub')
        maint = [p for r, p in sc.seen if r == 'maintain4'][0]
        g = [x for x in tree.nodes.values() if x.kind == 'goal']
        assert len(g) == 1 and all(g[0].id in [n[k]] + tree.ancestors(n[k]) for k in 'ABCEF') and s.get(g[0].id)['data'].get('summarized')
        st = [p for r, p in sc.seen if r == 'structure']          # the goal's level got new works: parts of one task are grouped
        assert len(st) == 1 and st[0]['level']['parent']['id'] == g[0].id and any(o['op'] == 'group' for o in ops)
        sc.q['maintain4'] = [{'ops': []}]
        sid = s.add('segment', {'text': 'm30', 'to': 'existing'}, at=500.0, source='user', turn=30); s.link(sid, 'about', n['C'], at=500.0, source='ctm')
        MS.maintain_store(s, tree, 600.0, model='stub')
        assert len([p for r, p in sc.seen if r == 'structure']) == 1 and len([p for r, p in sc.seen if r == 'goals']) == 1
    finally:
        MS.ask = old
    print('PASS maintenance_trigger')


def test_assign_goals():
    s, tree, n = _tree()
    g0 = tree.add('Existing goal', 'a long-term goal', None, None, 0, 50.0, kind='goal'); g1 = tree.add('Duplicate goal', 'the same one', None, None, 0, 51.0, kind='goal')
    UI.rename(s, n['E'], 'E2', at=60.0)                          # the user edited E: it stays where it is
    out = {'assign': [{'work': n['A'], 'goal': g0}, {'work': n['B'], 'goal': 'g1'}, {'work': n['C'], 'goal': 'g1'}, {'work': n['E'], 'goal': g0},
                      {'work': n['F'], 'goal': 'nope'}],
           'new_goals': [{'key': 'g1', 'title': 'New goal', 'purpose': 'long-term'}], 'merge_goals': [[g0, g1]]}
    ops = MS.assign_goals(s, tree, 100.0, model='stub', ask_fn=lambda *a, **k: (out, {}))
    new = [o['node'] for o in ops if o['op'] == 'new_goal'][0]
    assert tree.nodes[n['A']].parent == g0 and tree.nodes[n['B']].parent == new == tree.nodes[n['C']].parent
    assert tree.nodes[n['E']].parent is None and tree.nodes[n['F']].parent is None and tree.nodes[new].kind == 'goal'
    assert g1 not in tree.nodes and tree.resolve(g1) == g0
    print('PASS assign_goals')


def test_delivery_signal():
    sc = Script()
    REF.ask = DV.ask = RM.ask = sc
    old = MS.ask; MS.ask = sc
    try:
        s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[float(len(t) % 7), 1.0] for t in ts])
        sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
        sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Interface design', 'purpose': 'design the interface',
                                                                               'goal': {'title': 'Public interface', 'purpose': 'provide a stable public interface', 'stated': False}}}]}]
        a = ctm.on_message(0, 0.0, 'Design the interface first', recent=[], previous_reply='', working_dir='D:/r')['node']
        g = ctm.tree.nodes[a].parent
        assert ctm.tree.nodes[g].kind == 'goal' and s.get(g)['data'].get('summarized')
        sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
        sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Implement the interface', 'purpose': 'implement it as designed', 'goal': g, 'same_work_as': [a]}}]}]
        sc.q['structure'] = [lambda p: {'groups': [{'title': 'New interface', 'purpose': 'design and implement the new interface', 'children': p['focus'], 'why': 'design and implementation'}]}]
        r = ctm.on_message(1, 1 * H, 'Implement it with this design', recent=[{'user': '..', 'agent': '..', 'node': a}], previous_reply='', working_dir='D:/r')
        b = r['node']
        st = [p for role, p in sc.seen if role == 'structure']
        assert st and st[0]['trigger'] == 'new_work' and set(st[0]['focus']) == {a, b} and st[0]['level']['parent']['id'] == g
        t = ctm.tree.nodes[a].parent
        assert t != g and ctm.tree.nodes[b].parent == t and ctm.tree.nodes[t].parent == g and ctm.tree.nodes[t].title == 'New interface'
        # a new work without a goal: the goal judgment places it
        sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
        sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Write the weekly report', 'purpose': 'Write the weekly report'}}]}]
        sc.q['goals'] = [lambda p: {'assign': [{'work': p['works'][0]['id'], 'goal': g}]}]
        r = ctm.on_message(2, 2 * H, 'Write a weekly report', recent=[], previous_reply='', working_dir='D:/r')
        assert [p for role, p in sc.seen if role == 'goals'] and ctm.tree.nodes[r['node']].parent == g
        assert s.get(b)['data'].get('raised_during') == a              # the work being done when it was raised
        assert [p for role, p in sc.seen if role == 'goals'][-1]['works'][0]['raised_during'] == 'Implement the interface'
    finally:
        MS.ask = old
    print('PASS delivery_signal')


def test_moved_task_executor_told():
    from context_tree.ctm2 import context as C, execution as X
    s, tree, n = _tree()
    c = s.add('constraint', {'statement': 'only change the transport directory', 'kind': 'task'}, at=50.0, source='user', turn=1); s.link(c, 'about', n['B'], at=50.0, source='ctm')
    rid = s.add('run', {'mode': 'session', 'status': 'active', 'state': 'idle'}, at=60.0, source='ctm'); s.link(rid, 'serves', n['A'], at=60.0, source='ctm')
    sid = s.add('segment', {'text': 'm', 'to': 'existing'}, at=300.0, source='user', turn=20); s.link(sid, 'about', n['A'], at=300.0, source='ctm')
    sc = Script(); old = MS.ask; MS.ask = sc
    try:
        sc.q['maintain4'] = [{'ops': [{'op': 'set_parent', 'node': n['A'], 'parent': n['B'], 'why': 'A is part of B'}]}]
        MS.maintain_store(s, tree, 400.0, model='stub')
    finally:
        MS.ask = old
    assert tree.nodes[n['A']].parent == n['B']
    tid = s.add('turn', {'role': 'user', 'text': 'Go on'}, at=500.0, source='user', turn=30)
    text, _ = C.forward_text(s, n['A'], run=rid, turn=30, at=500.0)
    assert 'Changes in the meantime' in text and 'Now applies: only change the transport directory' in text
    print('PASS moved_task_executor_told')


def test_new_work_inherits_siblings_constraints():
    """Concept 3.5 for a new work: a sibling's constraint CTM judges to apply to the new work reaches its executor, marked as
    CTM's judgment; the sibling's other constraints do not (pipeline with the model calls stubbed)."""
    from context_tree.ctm2.store import Store
    from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM, scope as SC
    q = {}
    def stub(system, payload, **kw):
        lst = q.get(kw.get('role')) or []
        out = lst.pop(0) if lst else {}
        return (out(payload) if callable(out) else out), {}
    REF.ask = DV.ask = RM.ask = SC.ask = MS.ask = stub
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    q['ref'] = [{'modes': ['new'], 'entities': []}]
    q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Outline the course', 'purpose': 'outline',
                                                                       'goal': {'title': 'Make a course', 'purpose': 'course'}}}]}]
    q['remember'] = [lambda p: {'constraints': [{'statement': 'each lesson covers only the core concepts, a few hundred words', 'kind': 'task', 'node': p['deliveries'][0]['node']},
                                                {'statement': 'the outline lists three levels of headings first', 'kind': 'task', 'node': p['deliveries'][0]['node']}]}]
    a = ctm.on_message(1, 3600.0, 'Outline the course; each lesson covers only the core concepts in a few hundred words; the outline lists three levels of headings first', recent=[], previous_reply='', working_dir='D:/c')['node']
    whole = next(r['id'] for r in s.items('constraint') if 'core concepts' in r['data']['statement'])
    goal = s.parent(a)
    q['ref'] = [{'modes': ['new'], 'entities': []}]
    q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Write the text of lesson one', 'purpose': 'lesson text', 'goal': goal}}]}]
    q['inherit-new'] = [{'analysis': '', 'applies': [whole], 'why': 'a requirement for the texts of the whole course'}]
    r = ctm.on_message(2, 7200.0, 'Write the text of the first lesson', recent=[], previous_reply='', working_dir='D:/c')
    b = r['node']
    assert goal and b != a and s.parent(b) == s.parent(a) == goal, (b, s.parent(b), s.parent(a), goal)
    ctx = next(d['context'] for d in r['dispatches'] if d.get('context') and d.get('task') == b)   # what the new executor got
    sec = ctx.split('## Constraints and decisions in force')[1].split(chr(10) + '## ')[0]
    assert 'CTM judges it applies here too' in sec and 'each lesson covers only the core concepts' in sec and 'the outline lists three levels of headings first' not in sec, sec
    print('PASS new_work_inherits_siblings_constraints')


def test_inherited_constraint_on_page_and_dropped():
    """The work's page lists a sibling's constraint CTM gave it, with where it came from; the user can say it does not apply,
    which removes only the reference."""
    from context_tree.ctm2.store import Store
    from context_tree.ctm2.tree import StoreTree
    from context_tree.ctm2 import root as R, views as V, ui as UI, context as C
    s = Store(); R.ensure_root(s); t = StoreTree(s)
    g = t.add('Make a course', 'course', None, None, 0, 0.0, kind='goal')
    a = t.add('Outline the course', 'outline', g, None, 1, 1.0); b = t.add('Write the text of lesson one', 'lesson text', g, None, 2, 2.0)
    c = s.add('constraint', {'statement': 'a few hundred words per lesson', 'kind': 'task'}, at=1.5, source='user', turn=1); s.link(c, 'about', a, at=1.5, source='ctm')
    s.link(b, 'uses', c, at=2.0, source='ctm', data={'inferred': True})
    page = V.node_page(s, b)
    assert [x['id'] for x in page['inherited_constraints']] == [c] and page['inherited_constraints'][0]['from_title'] == 'Outline the course'
    UI.drop_inherited_constraint(s, b, c, at=3.0)
    assert V.node_page(s, b)['inherited_constraints'] == [] and s.about(c) == [a]
    assert 'a few hundred words per lesson' not in C.initial_context(s, b, turn=3, at=4.0, message='write the lesson text').split('## Constraints and decisions in force')[1].split(chr(10) + '## ')[0]
    print('PASS inherited_constraint_on_page_and_dropped')


if __name__ == '__main__':
    test_group_and_level(); test_guards(); test_maintenance_trigger(); test_assign_goals(); test_delivery_signal(); test_moved_task_executor_told()
    test_new_work_inherits_siblings_constraints()
    test_inherited_constraint_on_page_and_dropped()
