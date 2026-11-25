"""Offline walk-through of the CTM pipeline with stubbed model calls (no network).

Checks that the mechanism chains are wired end to end: pointing -> delivery -> dispatch (new executor with an initial context,
or forwarding to the active session) -> memory after dispatch -> reply (run evidence, file versions, progress, control-layer
stop, pending item, display) -> short approval of a displayed item -> correction (object rule + rejected approach) -> a new
executor whose initial context carries files, rejected approaches and decisions -> pause / abandon -> UI edits ->
maintenance operations (lift constraint, inheritance log, user-edited protection).
"""
from context_tree.ctm2 import pipeline as P
from context_tree.ctm2 import maintain_store as M
from context_tree.ctm2 import ui as UI
from context_tree.ctm2 import lifecycle as L
from context_tree.ctm2 import execution as X
from context_tree.ctm2 import ref as REF, deliver as DV, remember as RM, scope as SC
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
    """Answers per role from queues the test fills; other roles get {}."""
    def __init__(self): self.q, self.seen = {}, []

    def __call__(self, system, payload, **kw):
        self.seen.append((kw.get('role'), payload))
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def setup():
    sc = Script()
    REF.ask = DV.ask = RM.ask = M.ask = SC.ask = P.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=stub_embed)
    return s, ctm, sc


def say(ctm, sc, turn, at, text, deliveries, memory=None, replace=None, **kw):
    """One user message: the delivery's and the memory call's outputs as the model would give them."""
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': deliveries}]
    sc.q['remember'] = [memory or {}]
    sc.q['replace'] = [replace] if replace else []
    return ctm.on_message(turn, at, text, recent=[], previous_reply='', working_dir=kw.pop('working_dir', 'D:/r'), **kw)


def test_walkthrough():
    s, ctm, sc = setup()
    # 1. new work -> new executor with the user's words as the goal; the constraint is remembered after dispatch
    r = say(ctm, sc, 0, 0.0, 'Implement feature X, only change the transport directory', [{'part': 'all', 'to': 'new', 'new': {'title': 'Feature X', 'purpose': 'implement X'}}],
            memory=lambda p: {'constraints': [{'statement': 'only change the transport directory', 'kind': 'task', 'node': p['deliveries'][0]['node']}]})
    n = r['node']; d = r['dispatches'][0]
    assert not d['reused'] and 'Implement feature X, only change the transport directory' in d['context'].split('## The goal')[1]
    assert [c['data']['statement'] for c in s.items('constraint', about=n, current_only=True)] == ['only change the transport directory']
    assert L.status(s, n) == 'running'
    # 2. executor stops asking for a decision; it edited a file
    P.K.classify_stop = lambda contract, tail, **kw: ({'type': 'decision', 'action': 'escalate', 'why': 'Plan A or B?'}, {})
    log = ctm.on_reply(0, 10.0, n, 'Implement feature X', 'I changed a.py. Plan A or B?', tools=[{'name': 'Edit', 'path': 'D:/r/transport/a.py'}],
                       progress={'done': 'changed a.py', 'open': ['choose A or B']}, run=d['run'], classify=True, working_dir='D:/r')
    assert log['to_ctm']['kind'] == 'decision' and L.status(s, n) == 'blocked' and log['files']
    disp = P.relay.recent_displays(s, 11.0)
    assert disp and disp[-1]['kind'] == 'pending' and disp[-1]['task'] == n
    # 3. short approval of the displayed item: the answer goes back to the waiting executor
    r = say(ctm, sc, 1, 20.0, 'OK, use A', [{'part': 'all', 'to': 'control', 'node': n, 'control': 'approve', 'answers_pending': [disp[-1]['no']]}],
            memory={'decisions': [{'statement': 'use plan A', 'type': 'decision', 'node': n}]})
    assert L.status(s, n) == 'running' and not P.relay.open_pending(s, 21.0, n)
    assert 'OK, use A' in r['controls'][0]['forward']
    # 4. correction: object rule + rejected approach; the active session receives the user's words
    r = say(ctm, sc, 2, 30.0, 'No, transport must not expose a sample rate parameter', [{'part': 'all', 'to': 'existing', 'node': n}],
            memory={'constraints': [{'statement': 'transport must not expose a sample rate parameter', 'kind': 'object', 'scope': 'transport', 'validity': 'long_term'}],
                    'decisions': [{'statement': 'add a sample rate parameter to the transport interface', 'type': 'rejected', 'node': n}]})
    d2 = r['dispatches'][0]
    assert d2['reused'] and d2['run'] == d['run'] and 'must not expose a sample rate parameter' in d2['forward']
    assert s.db.execute("select count(*) from items where type='object'").fetchone()[0] >= 1           # indexed under its object
    assert not any(p['data']['kind'] == 'write_object_constraint' for p in s.items('pending'))   # no writing task for executors
    # 5. five hours later the task continues in the same session (sessions do not end by time)
    r = say(ctm, sc, 3, 30.0 + 5 * H, 'Go on with X', [{'part': 'all', 'to': 'existing', 'node': n}])
    d3 = r['dispatches'][0]
    assert d3['reused'] and d3['run'] == d['run'] and 'Go on with X' in d3['forward']
    other = ctm.tree.add('other', 'o', None, None, 3, 30.0 + 5 * H); orun, _, _ = X.executor_for(s, other, at=30.0 + 5 * H, turn=3)
    assert X.sweep(s, at=30.0 + 9 * H) == [] and s.get(orun)['data']['status'] == 'active'
    assert other in ctm.running_nodes(at=30.0 + 5 * H) and other not in ctm.running_nodes(at=30.0 + 9 * H)   # idle: no longer "running"
    # 5b. the session's context is full and the user declines compaction: a new executor gets files, rejected approaches, decisions
    s.patch(d['run'], {'compact': 'declined'}, at=31.0 + 5 * H, source='user')
    r = say(ctm, sc, 30, 32.0 + 5 * H, 'Go on with X', [{'part': 'all', 'to': 'existing', 'node': n}])
    d3 = r['dispatches'][0]
    assert not d3['reused'] and d3['run'] != d['run'] and s.get(d['run'])['data']['status'] == 'ended'
    ctx = d3['context']
    assert 'D:/r/transport/a.py' in ctx and 'rejected: add a sample rate parameter to the transport interface' in ctx and 'use plan A' in ctx and 'Go on with X' in ctx.split('## The goal')[1]
    assert 'changed a.py' in ctx                                  # brief progress with time
    assert 'must not expose a sample rate parameter' not in ctx.split('## The goal')[0].split('## Latest exchanges of this task and the works above it')[0]   # object rules come from ctm.md
    # 6. pause, then abandon: the executor is stopped, its session stays; reopening continues it
    r = say(ctm, sc, 4, 40.0 + 5 * H, 'Hold on for now', [{'part': 'all', 'to': 'control', 'node': n, 'control': 'pause'}])
    assert L.status(s, n) == 'paused' and not r['dispatches']
    r = say(ctm, sc, 5, 50.0 + 5 * H, 'Drop this', [{'part': 'all', 'to': 'control', 'node': n, 'control': 'abandon'}])
    sess = X.active_run(s, n)
    assert L.status(s, n) == 'abandoned' and sess and sess['data'].get('state') == 'idle'
    r = say(ctm, sc, 6, 60.0 + 5 * H, 'Go on with it after all', [{'part': 'all', 'to': 'control', 'node': n, 'control': 'reopen'}])
    r = say(ctm, sc, 7, 61.0 + 5 * H, 'Go on', [{'part': 'all', 'to': 'existing', 'node': n}])
    assert r['dispatches'][0]['reused'] and r['dispatches'][0]['run'] == sess['id'] and L.status(s, n) == 'running'


def test_ui_edits_and_maintenance_ops():
    s = Store(); ctm = P.CTM(s, model='stub')
    t = ctm.tree
    a = t.add('A', 'deliver A', None, None, 0, 0.0); b = t.add('B step', 'b', None, None, 1, 1.0); c = t.add('C step', 'c', None, None, 2, 2.0)
    con = s.add('constraint', {'statement': 'Chinese comments for the whole feature', 'kind': 'task'}, at=2, source='user', turn=2)
    s.link(con, 'about', b, at=2, source='ctm')
    ops = M.apply_ops(s, t, [{'op': 'create_parent', 'title': 'Feature', 'purpose': 'deliver feature', 'children': [b, c], 'why': 'same purpose'}], 10.0)
    p = ops[0]['created']
    M.apply_ops(s, t, [{'op': 'lift_constraint', 'constraint': con, 'to': p, 'why': 'the user said the whole feature'}], 11.0)
    assert s.about(con) == [p]
    # c gained the lifted constraint through inheritance
    inherit_c = {r['id'] for n in [c] + s.ancestors(c) for r in s.items('constraint', about=n, current_only=True)}
    assert con in inherit_c
    # UI: the user moves c under a; maintenance may not move it back without later user evidence
    UI.move(s, c, a, at=20.0)
    res = M.apply_ops(s, t, [{'op': 'set_parent', 'node': c, 'parent': p, 'why': 'x'}], 30.0)
    assert res[0].get('proposal') and s.parent(c) == a
    # UI: abandon stops an executor and cancels pending items
    run, _, _ = X.executor_for(s, a, at=31.0, turn=3)
    pid = s.add('pending', {'kind': 'decision', 'what': 'q', 'status': 'open'}, at=31.0, source='executor'); s.link(pid, 'about', a, at=31.0, source='ctm')
    UI.set_status(s, a, 'abandoned', at=32.0)
    assert s.get(run)['data']['status'] == 'active' and s.get(pid)['data']['status'] == 'cancelled'
    assert any(e['kind'] == 'control' for e in s.events_of(run))


def test_exceptions_references_files_and_views():
    from context_tree.ctm2 import documents as D, views as V, root as R
    s, ctm, sc = setup(); t = ctm.tree
    g = t.add('Feature', 'deliver', None, None, 0, 0.0); a = t.add('design doc', 'write design', g, None, 0, 0.0); b = t.add('impl', 'implement', g, None, 0, 0.0)
    c_parent = s.add('constraint', {'statement': 'All comments in English', 'kind': 'task'}, at=1, source='user', turn=1); s.link(c_parent, 'about', g, at=1, source='ctm')
    # a contrary constraint stated on a child is an exception for that subtree (not a replacement)
    r = say(ctm, sc, 2, 2.0, 'Write the comments in the design document in Chinese', [{'part': 'all', 'to': 'existing', 'node': a}],
            memory={'constraints': [{'statement': 'comments in Chinese', 'kind': 'task', 'validity': 'work', 'node': a}]},
            replace={'items': [{'new': 0, 'replaces': [c_parent]}]})
    assert r['write'].get('exceptions') and s.get(c_parent)['replaced_at'] is None
    ctx_a = P.C.initial_context(s, a, turn=3, at=3.0, message='Go on writing')
    assert 'comments in Chinese' in ctx_a and 'an exception to the constraint above' in ctx_a and '[turn 1](Feature) All comments in English' not in ctx_a
    ctx_b = P.C.initial_context(s, b, turn=3, at=3.0, message='implement')
    assert 'All comments in English' in ctx_b and 'comments in Chinese' not in ctx_b
    # cross-task reference: b uses a's decision; replacing it marks b for re-check
    dec = s.add('decision', {'statement': 'plan P', 'type': 'decision'}, at=4, source='user', turn=4); s.link(dec, 'about', a, at=4, source='ctm')
    other = t.add('elsewhere', 'x', None, None, 0, 0.0)
    s.unlink(g, 'child', a, at=4.5); s.link(other, 'child', a, at=4.5, source='ui'); t.nodes[a].parent = other   # a on another line
    s.link(b, 'uses', dec, at=4.6, source='ctm')
    r = say(ctm, sc, 5, 5.0, 'Implement it with the plan we settled', [{'part': 'all', 'to': 'existing', 'node': b}])
    assert 'plan P' in r['dispatches'][0]['context'].split('## Decisions, research and results from elsewhere that this work uses')[1]
    say(ctm, sc, 6, 6.0, 'Change the plan to Q', [{'part': 'all', 'to': 'existing', 'node': a}],
        memory={'decisions': [{'statement': 'plan Q', 'type': 'decision', 'node': a}]}, replace={'items': [{'new': 0, 'replaces': [dec]}]})
    assert any(e['kind'] == 'needs_recheck' for e in s.events_of(b))
    assert 'plan Q' in P.C.initial_context(s, b, turn=7, at=7.0, message='x').split('## Decisions, research and results from elsewhere that this work uses')[1]
    # a file changed elsewhere ends b's session and notifies
    run_b = X.active_run(s, b)['id']
    D.record_file_versions(s, run=run_b, task=b, tools=[{'name': 'write', 'path': 'D:/r/x.py'}], at=7.5)
    vid, notified = D.observe_file_change(s, path='D:/r/x.py', working_dir='D:/r', at=8.0)
    assert notified == [run_b] and X.end_reason(s, s.get(run_b), b, 9.0) is None           # the session is told, not ended
    assert 'The file D:/r/x.py was changed elsewhere' in P.C.forward_text(s, b, run=run_b, turn=9, at=9.0)[0]
    # constraint-annotation tamper and no-progress budget escalate
    P.K.classify_stop = lambda contract, tail, **kw: ({'type': 'continue', 'action': 'auto_continue', 'why': ''}, {})
    for i in range(3):
        log = ctm.on_reply(10 + i, 10.0 + i, b, 'x', 'Shall I go on?', progress={}, run=run_b, classify=True,
                           diff='--- a/ctm.md' + chr(10) + '- ctm: transport must not expose the sample rate' if i == 0 else None)
    assert log['to_ctm'] and log['to_ctm']['kind'] == 'failed' and L.status(s, b) == 'blocked'
    assert any(p['data'].get('what', '').startswith('The executor deleted or edited constraint comments') for p in s.items('pending'))
    assert not X.constraint_tamper('-No commit or modification of `ctm.md` was made.')   # a mention is not an entry
    # @-reference and document selection
    did = D.create_document(s, kind='knowledge', title='Design', use_when='when designing', text='', task=a, at=12.0, source='executor')
    D.update_section(s, did, 'Commit order', 'flush first, then commit', run=None, task=a, at=12.0, source='executor')
    sel, pointed = ctm._selection('This part is wrong', did + '#Commit order')
    assert sel == a and 'flush first, then commit' in pointed
    assert ctm._selection('@' + b + ' go on', None)[0] == b
    # views and root checks
    page = V.node_page(s, a); rec = V.exchange_record(s, b)
    assert page['decisions'] and any(x['who'] == 'user' for x in rec)
    R.add_overall_goal(s, 'Finish X this month', at=0.0)
    assert any(o['op'] == 'confirm_overall_goal' for o in M.root_checks(s, t, 30 * 86400.0))


def test_side_questions_go_to_a_readonly_executor_or_fork():
    s, ctm, sc = setup(); t = ctm.tree
    n = t.add('T', 't', None, None, 0, 0.0)
    r = say(ctm, sc, 1, 1.0, 'Why is it 625', [{'part': 'all', 'to': 'side', 'node': n}])
    d = r['dispatches'][0]
    assert d['readonly'] and not d['reused'] and 'read-only query' in d['context'] and L.status(s, n) == 'pending'
    ctm.on_reply(1, 2.0, n, 'q', 'because of the sample rate', progress={'done': 'explained 625'}, run=d['run'])
    assert s.get(d['run'])['data']['status'] == 'ended' and s.items('query')[-1]['data'].get('answer') == 'explained 625'
    run, _, _ = X.executor_for(s, n, at=3.0, turn=2)            # the task now has a session
    r = say(ctm, sc, 3, 4.0, 'How is it going now', [{'part': 'all', 'to': 'side', 'node': n}])
    d = r['dispatches'][0]
    assert d['readonly'] and d['fork_of'] == run and d['run'] != run and 'read-only query' in d['forward'] and L.status(s, n) == 'running'
    ctm.on_reply(3, 5.0, n, 'q', 'at the third step', progress={'done': 'two of three steps done'}, run=d['run'])
    assert s.get(d['run'])['data']['status'] == 'ended'
    assert not s.db.execute("select 1 from edges where rel='forwarded_to' and dst=?", (run,)).fetchone()   # the query stayed out of the session
    r = say(ctm, sc, 4, 6.0, 'Then finish the third step', [{'part': 'all', 'to': 'existing', 'node': n}])
    fw = r['dispatches'][0]['forward']
    assert r['dispatches'][0]['run'] == run and 'How is it going now' in fw and 'two of three steps done' in fw   # the session learns the query conclusion


def test_guidance_and_constraint_lift():
    s, ctm, sc = setup(); t = ctm.tree
    par = t.add('Hook the new interface into the quota check', 'hook it in and finish the check', None, None, 0, 0.0)
    a = t.add('Analyse how to hook it in', 'analyse', par, None, 0, 0.0); b = t.add('Implement the plan', 'implement', par, None, 1, 1.0)
    # guidance is kept apart from constraints: the executor reads it as advice, not as a hard limit
    say(ctm, sc, 1, 1.0, 'Implement the plan; test broadly; use az cli', [{'part': 'all', 'to': 'existing', 'node': b}],
        memory={'constraints': [{'statement': 'use az cli', 'kind': 'task', 'validity': 'work', 'node': b}],
                'guidance': [{'statement': 'test broadly', 'node': b}]})
    ctx = P.C.initial_context(s, b, turn=2, at=2.0, message='Go on')
    assert 'test broadly' in ctx.split("## The user's guidance on approach and plan")[1].split('##')[0] and 'test broadly' not in ctx.split('## Constraints and decisions in force')[1].split('##')[0]
    assert 'use az cli' in ctx.split('## Constraints and decisions in force')[1].split('##')[0]
    # the same requirement stated for the sibling: it holds for the whole work -> lifted to the common parent (concept 3.5)
    ctm.lift_same = True
    SC.base.embeddings = lambda texts: [[1.0, float(len(x) % 3)] for x in texts]
    sc.q['scope'] = [lambda p: {'same': [p['candidates'][0]['id']], 'destination': 'lift', 'why': 'the whole work uses az cli'}]
    say(ctm, sc, 2, 2.0, 'Use az cli for the analysis too', [{'part': 'all', 'to': 'existing', 'node': a}],
        memory={'constraints': [{'statement': 'use az cli', 'kind': 'task', 'validity': 'work', 'node': a}]})
    lifted = s.items('constraint', about=par, current_only=True)
    assert len(lifted) == 1, lifted
    assert not s.items('constraint', about=a, current_only=True) and not s.items('constraint', about=b, current_only=True)
    assert any(e['kind'] == 'inheritance_change' for e in s.events_of(b))   # b's own copy was folded into the lifted one
    # a requirement repeated across different top-level works becomes a proposal, not a silent global rule
    o = t.add('Another project', 'x', None, None, 3, 3.0)
    sc.q['scope'] = [lambda p: {'same': [p['candidates'][0]['id']], 'destination': 'global', 'why': 'a personal habit'}]
    say(ctm, sc, 3, 3.0, 'Use az cli here too', [{'part': 'all', 'to': 'existing', 'node': o}], working_dir='D:/q',
        memory={'constraints': [{'statement': 'use az cli', 'kind': 'task', 'validity': 'work', 'node': o}]})
    assert any(p['data']['kind'] == 'proposed_preference' for p in s.items('pending')) and not s.items('constraint', about='ROOT')


def test_siblings_research_behavior_and_request_done():
    from context_tree.ctm2 import documents as D, query as Q
    s, ctm, sc = setup(); t = ctm.tree
    grand = t.add('region-x release', 'g', None, None, 0, 0.0)
    par = t.add('Update and fix region-x', 'x', grand, None, 0, 0.0)
    uncle = t.add('Prepare the release notes', 'u', grand, None, 0, 0.0)
    pu = s.add('progress', {'done': 'release notes drafted'}, at=0.4, source='ctm', turn=0); s.link(pu, 'about', uncle, at=0.4, source='ctm')
    test = t.add('Test region-x', 'test', par, None, 0, 0.0); fix = t.add('Fix the routing regression', 'fix', par, None, 1, 1.0)
    c = s.add('constraint', {'statement': 'Test only in the staging environment', 'kind': 'task'}, at=0.5, source='user', turn=0); s.link(c, 'about', test, at=0.5, source='ctm')
    dec = s.add('decision', {'statement': 'the regression came with commit abc', 'type': 'decision'}, at=0.6, source='user', turn=0); s.link(dec, 'about', test, at=0.6, source='ctm')
    sg = s.add('segment', {'text': 'Test region-x'}, at=0.5, source='user', turn=0); s.link(sg, 'about', test, at=0.5, source='ctm')
    pr = s.add('progress', {'done': 'the test found a model name case mismatch'}, at=0.7, source='ctm', turn=0); s.link(pr, 'about', test, at=0.7, source='ctm')
    # a new executor for the fix sees the recently executed sibling: its results and decisions, not its constraints
    P.K.classify_stop = lambda contract, tail, **kw: ({'type': 'none', 'action': 'report', 'why': ''}, {})
    r = say(ctm, sc, 2, 2.0, 'Start fixing', [{'part': 'all', 'to': 'existing', 'node': fix}])
    ctx = r['dispatches'][0]['context']
    sib = ctx.split("## Recently executed sibling tasks and the parent's siblings")[1].split('## Agent behavior guidance')[0]
    assert 'Test region-x' in sib and 'case mismatch' in sib and 'the regression came with commit abc' in sib and 'Test only in the staging environment' not in ctx
    assert "Prepare the release notes (parent's sibling" in sib and 'release notes drafted' in sib
    # the executor reports the request done: recorded on the run, the task stays open
    ctm.on_reply(2, 3.0, fix, 'Start fixing', 'fixed', progress={'done': 'fixed'}, run=r['dispatches'][0]['run'], classify=True)
    assert L.status(s, fix) == 'running' and any(e['kind'] == 'request_done' for e in s.events_of(r['dispatches'][0]['run']))
    # research without a stated purpose: a research item in the query list, with its own session and document
    r = say(ctm, sc, 3, 4.0, 'Research similar work on the web, only on GitHub', [{'part': 'all', 'to': 'research', 'node': par, 'new': {'title': 'Research similar work'}}])
    d = r['dispatches'][0]; rid = d['task']
    assert d['research'] and s.get(rid)['type'] == 'research' and rid not in t.nodes and 'This is a research' in d['context']
    assert 'only on GitHub' in d['context'].split("## The goal: the user's words this time")[1]
    ctm.on_reply(3, 5.0, rid, 'q', 'Found three related projects: A, B, C', progress={'done': 'listed three projects'}, run=d['run'])
    did = s.get(rid)['data']['doc']
    assert did and 'Found three related projects' in D.latest(s, did)['data']['sections']['turn 3']
    r = say(ctm, sc, 4, 6.0, 'Go on with the research, look at B again', [{'part': 'all', 'to': 'research', 'research': rid}])
    assert r['dispatches'][0]['reused'] and r['dispatches'][0]['run'] == d['run']
    assert any(x.get('research') == 'Research similar work' for x in Q.panel(s))
    # later it turns out to be part of a work: maintenance attaches it as a task under that work
    tmp = Store(); tt = P.CTM(tmp, model='stub').tree; w = tt.add('W', 'w', None, None, 0, 0.0)
    rr = tmp.add('research', {'title': 'R', 'status': 'open'}, at=0.1, source='ctm', turn=0); tmp.link(rr, 'about', 'ROOT', at=0.1, source='ctm')
    sg2 = tmp.add('segment', {'text': 'Research R'}, at=0.1, source='user', turn=0); tmp.link(sg2, 'about', rr, at=0.1, source='ctm')
    M.apply_ops(tmp, tt, [{'op': 'attach_research', 'research': rr, 'parent': w, 'why': 'serves W'}], 1.0)
    nn = [c for c in tmp.children(w)][0]
    assert tmp.get(rr)['data']['status'] == 'attached' and tmp.about(sg2) == [nn]
    # a task that uses the research gets its conclusion
    s.link(fix, 'uses', rid, at=6.5, source='ctm')
    assert 'Found three related projects' in P.C.initial_context(s, fix, turn=5, at=7.0, message='x').split('## Decisions, research and results from elsewhere that this work uses')[1]
    # general agent behavior guidance goes to a behavior document; executors get the index
    from context_tree.ctm2 import model as MD
    orig = MD.ask
    MD.ask = lambda system, payload, **kw: ({'items': [{'i': 0, 'doc': 'new', 'title': 'Starting sub-agents', 'use_when': 'when starting sub-agents or subprocesses'}]}, {})
    try:
        say(ctm, sc, 5, 8.0, 'From now on start sub-agents without a window, and change the current launcher too', [{'part': 'all', 'to': 'existing', 'node': fix}],
            memory={'behavior': [{'statement': 'start sub-agents without a window', 'use_when': 'when starting sub-agents'}]})
    finally:
        MD.ask = orig
    assert D.behavior_docs(s) and 'Starting sub-agents' in P.C.initial_context(s, test, turn=6, at=9.0, message='x').split('## Agent behavior guidance')[1]


def test_subtask_continues_in_parent_session_and_gets_local_constraints():
    s, ctm, sc = setup(); t = ctm.tree
    fix = t.add('Fix the routing regression', 'fix', None, None, 0, 0.0)
    run, _, _ = X.executor_for(s, fix, at=1.0, turn=1)
    # "keep solving the problems you found": the same work continuing, in the same session
    r = say(ctm, sc, 2, 2.0, 'Keep solving them', [{'part': 'all', 'to': 'existing', 'node': fix}])
    assert r['dispatches'][0]['run'] == run and not s.children(fix)
    # problem A gets its own requirement: it becomes a subtask, done in the parent's session, with its local constraint
    r = say(ctm, sc, 3, 3.0, 'Do not touch the interface when fixing A', [{'part': 'all', 'to': 'new', 'session': 'parent', 'new': {'title': 'Fix A', 'purpose': 'fix problem A', 'parent': fix}}],
            memory=lambda p: {'constraints': [{'statement': 'do not touch the interface when fixing A', 'kind': 'task', 'validity': 'work', 'node': p['deliveries'][0]['node']}]})
    d = r['dispatches'][0]; a = d['task']
    assert s.parent(a) == fix and d['run'] == run and d['reused'] and 'Do not touch the interface when fixing A' in d['forward']
    # the parent's session sees the part's local constraint marked as local
    ic = P.C.initial_context(s, fix, turn=4, at=4.0, message='x')
    assert 'only for the part "Fix A"' in ic and 'do not touch the interface when fixing A' in ic


def test_new_work_with_a_new_goal_runs_as_a_task():
    s, ctm, sc = setup()
    r = say(ctm, sc, 1, 1.0, 'I want a provider layer; implement the Copilot one first',
            [{'part': 'all', 'to': 'new', 'new': {'title': 'Implement the Copilot provider', 'purpose': 'q', 'goal': {'title': 'Reading sessions of several clients', 'purpose': 'p', 'stated': True}}}])
    d = r['dispatches']
    task = ctm.tree.nodes[d[0]['task']]
    assert len(d) == 1 and task.kind == 'task' and task.title == 'Implement the Copilot provider' and ctm.tree.nodes[task.parent].kind == 'goal'


def test_research_requirements_stay_on_the_research_item():
    """A research item is not on the tree; what the user requires of it is its own (concept 3.4), not a global rule that would
    reach every executor (the memory call once did not see research deliveries and put such requirements on the root)."""
    s, ctm, sc = setup()
    w = ctm.tree.add('W', 'w', None, None, 0, 0.0)
    r = say(ctm, sc, 1, 1.0, 'Research similar work on the web, only on GitHub', [{'part': 'all', 'to': 'research', 'new': {'title': 'Research similar work'}}],
            memory=lambda p: {'constraints': [{'statement': 'only on GitHub', 'kind': 'task', 'node': p['deliveries'][0]['node']}]})
    rid = r['dispatches'][0]['task']
    assert [s.about(c['id']) for c in s.items('constraint')] == [[rid]]
    assert 'only on GitHub' in P.C.research_context(s, rid, turn=2, at=2.0, message='Go on').split("## This research's requirements")[1].split('##')[0]
    assert 'only on GitHub' not in P.C.initial_context(s, w, turn=2, at=2.0, message='x').split('## Constraints and decisions in force')[1].split('##')[0]


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
