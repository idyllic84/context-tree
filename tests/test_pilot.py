"""Offline test of the pilot orchestration: a fake pi (RPC protocol subset) and stubbed model calls.
new work -> new session; a follow-up reuses it; a side question forks it read-only; a UI selection targets the next
message; rename and redirect; a restart reloads the conversation and resumes the session file."""
import json
import os
import sys
import tempfile
import textwrap
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM, query as Q, control as K

FAKE_PI = textwrap.dedent(r'''
    import json, os, sys, uuid
    args = sys.argv[1:]
    def opt(name):
        return args[args.index(name) + 1] if name in args else None
    session = opt('--session')
    sdir = opt('--session-dir') or '.'
    fork = opt('--fork')
    if not session:
        session = os.path.join(sdir, uuid.uuid4().hex[:8] + '.jsonl')
        open(session, 'a').write(json.dumps({'fork': fork, 'tools': opt('--tools')}) + '\n')
    out = sys.stdout
    def emit(o):
        out.write(json.dumps(o, ensure_ascii=False) + '\n'); out.flush()
    for line in sys.stdin:
        cmd = json.loads(line)
        t = cmd.get('type'); cid = cmd.get('id')
        if t == 'prompt':
            msg = cmd.get('message', '')
            open(session, 'a', encoding='utf-8').write(json.dumps({'prompt': msg[:200]}, ensure_ascii=False) + '\n')
            emit({'id': cid, 'type': 'response', 'command': 'prompt', 'success': True, 'data': {'disposition': 'started'}})
            emit({'type': 'agent_start'})
            emit({'type': 'message_update', 'assistantMessageEvent': {'type': 'text_delta', 'contentIndex': 0, 'delta': 'Handled'}})
            if '--tools' not in args:
                emit({'type': 'tool_execution_start', 'toolCallId': 'c1', 'toolName': 'write', 'args': {'path': 'out.txt', 'content': 'x'}})
                emit({'type': 'tool_execution_end', 'toolCallId': 'c1', 'toolName': 'write', 'result': {}, 'isError': False})
            emit({'type': 'message_end', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Handled: ' + msg[-40:]}]}})
            emit({'type': 'agent_end', 'messages': [], 'willRetry': False})
            emit({'type': 'agent_settled', 'aborted': False})
        elif t == 'get_state':
            emit({'id': cid, 'type': 'response', 'command': t, 'success': True, 'data': {'sessionFile': session}})
        elif t == 'export_html':
            open(cmd['outputPath'], 'w', encoding='utf-8').write('<html>' + session + '</html>')
            emit({'id': cid, 'type': 'response', 'command': t, 'success': True, 'data': {'path': cmd['outputPath']}})
        elif t == 'get_session_stats':
            emit({'id': cid, 'type': 'response', 'command': t, 'success': True, 'data': {'tokens': {'total': 10}, 'contextUsage': {'tokens': 10}}})
        else:
            emit({'id': cid, 'type': 'response', 'command': t, 'success': True})
''')


def stub_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 64
        for ch in t: v[ord(ch) % 64] += 1.0
        out.append(v)
    return out


class Script:
    def __init__(self): self.q = {}
    def __call__(self, system, payload, **kw):
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def sent(root, turn):
    ev = [json.loads(l) for l in open(os.path.join(root, 'events.jsonl'), encoding='utf-8')]
    return [e['run'] for e in ev if e['kind'] == 'send' and e['turn'] == turn]


def relayed(pilot, turn, n=1):
    return sum(1 for it in pilot.items if it['kind'] == 'ctm' and it['turn'] == turn) >= n


def wait(cond, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond(): return True
        time.sleep(0.05)
    raise AssertionError('timeout')


def test_pilot_flow():
    from context_tree.pilot.app import Pilot
    tmp = tempfile.mkdtemp()
    fake = os.path.join(tmp, 'fake_pi.py'); open(fake, 'w', encoding='utf-8').write(FAKE_PI)
    sc = Script()
    REF.ask = DV.ask = RM.ask = sc
    Q.ask = lambda system, payload, **kw: ({'kind': 'current_state', 'from_memory': False, 'readonly_plan': 'read the file', 'needs_change': False}, {})
    Q.answer = lambda store, node, at, qs, **kw: ([{'q': 0, 'answer': 'not in memory', 'found': False}], {})
    P.summarize = lambda *a, **kw: ({'done': 'wrote out.txt', 'open': []}, {})
    K.classify_stop = lambda *a, **kw: ({'type': 'report', 'action': 'report', 'why': 'done'}, {})
    opts = dict(model='stub', light_model='stub', memory_model='stub', control_model='stub', embed=stub_embed, maintain_every=None)
    root = os.path.join(tmp, 'pilot')
    pilot = Pilot(root, pi_command=[sys.executable, fake], ctm_options=opts, maintain_hours=1e9)
    pilot.ctm_options = opts
    # 1. new work: a new session gets the initial context; the reply goes back through CTM
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Write out', 'purpose': 'write out.txt'}}]}]
    r1 = pilot.message('Write an out.txt')
    x = r1['node']
    wait(lambda: relayed(pilot, r1['turn']))
    done = next(it for it in pilot.items if it['kind'] == 'ctm' and it['turn'] == r1['turn'])
    assert done['done'] and 'wrote out.txt' in done['text']          # CTM relays the progress summary, not the executor's text
    assert not any(it['kind'] in ('run', 'reply') for it in pilot.items)
    run1 = sent(root, r1['turn'])[0]
    sf = pilot._session_file(run1)
    assert sf and os.path.exists(sf)
    wd1 = pilot.call(lambda: pilot.ctm.tree.nodes[x].working_dir)       # no project: a scratch directory of its own under the root
    assert wd1.replace(chr(92), '/').endswith('/work/' + x) and os.path.isdir(wd1)
    # 2. follow-up on the same work: the same session receives the forwarded message
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'existing', 'node': x}]}]
    r2 = pilot.message('Add one more line')
    wait(lambda: relayed(pilot, r2['turn']))
    run2 = sent(root, r2['turn'])[0]
    assert run2 == run1
    assert sum(1 for l in open(sf, encoding='utf-8') if '"prompt"' in l) == 2
    # 3. a side question: a read-only fork of the work's session
    sc.q['ref'] = [{'modes': ['named'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'side', 'node': x}]}]
    r3 = pilot.message('How many lines does out.txt have now?')
    wait(lambda: relayed(pilot, r3['turn']))
    ans = next(it for it in pilot.items if it['kind'] == 'ctm' and it['turn'] == r3['turn'])
    assert ans['query'] and ans['detail'].startswith('Handled')         # a query's answer is for the user, with the full answer
    run3 = sent(root, r3['turn'])[0]
    assert run3 != run1 and pilot.runs[run3].readonly
    first = json.loads(open(pilot._session_file(run3), encoding='utf-8').readline())
    assert first['fork'] == sf and first['tools'] == 'read,grep,find,ls'
    # 4. a UI selection targets the next message; rename; redirect to another work
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Another thing', 'purpose': 'another thing'}}]}]
    r4 = pilot.message('Do another thing')
    y = r4['node']
    assert y != x
    wait(lambda: relayed(pilot, r4['turn']))
    pilot.ui('select', node=x)
    def to_selected(p):
        assert p['ui_selection']['id'] == x
        return {'deliveries': [{'part': 'all', 'to': 'existing', 'node': x}]}
    sc.q['ref'] = [{'modes': ['continue'], 'entities': []}]
    sc.q['deliver'] = [to_selected]
    r5 = pilot.message('Go on')
    assert r5['node'] == x and pilot.selection is None
    wait(lambda: relayed(pilot, r5['turn']))
    pilot.ui('rename', node=y, title='Another thing (renamed)')
    assert pilot.tree()['nodes'] and any(n['title'] == 'Another thing (renamed)' for n in pilot.tree()['nodes'])
    out = pilot.ui('redirect', turn=r5['turn'], node=y)
    assert out['ok']
    wait(lambda: relayed(pilot, r5['turn'], 2))
    assert pilot.call(lambda: pilot.ctm.assigned[r5['turn']]) == y
    ev = [json.loads(l) for l in open(os.path.join(root, 'events.jsonl'), encoding='utf-8')]
    assert any(e['kind'] == 'ui' and e['op'] == 'redirect' for e in ev) and any(e['kind'] == 'message' for e in ev)
    path = pilot.export_record(run1)                                  # the executor's session, read-only, on request
    assert path and sf in open(path, encoding='utf-8').read()
    assert any(json.loads(l)['kind'] == 'view_record' for l in open(os.path.join(root, 'events.jsonl'), encoding='utf-8'))
    node = next(n for n in pilot.tree()['nodes'] if n['id'] == x)
    assert node['session'] and node['run'] == run1
    n_items = len(pilot.items)
    pilot.shutdown()
    # 5. restart: the conversation and the session file are kept
    p2 = Pilot(root, pi_command=[sys.executable, fake], ctm_options=opts, maintain_hours=1e9)
    assert len(p2.items) == n_items and p2.call(lambda: p2._session_file(run1)) == sf
    p2.shutdown()
    print('PASS pilot_flow')


def test_report_counts_corrections_and_waiting():
    """The usage report (read-only) counts page corrections by block, executor stops, raw-reply views and waiting time."""
    import json, tempfile
    from pathlib import Path
    from context_tree.pilot.report import report
    d = Path(tempfile.mkdtemp())
    ev = [{'t': 10, 'kind': 'message', 'turn': 1, 'to': 'new', 'seconds': 20, 'dispatch_seconds': 12, 'usage': [{'role': 'deliver', 'in': 1000, 'out': 100}]},
          {'t': 11, 'kind': 'ui', 'op': 'redirect'}, {'t': 12, 'kind': 'ui', 'op': 'select'}, {'t': 13, 'kind': 'ui', 'op': 'reattach'},
          {'t': 14, 'kind': 'reply', 'run': 'RU1', 'cost': 0.5}, {'t': 15, 'kind': 'control', 'stop': {'type': 'decision', 'action': 'escalate'}, 'to_ctm': {'kind': 'decision'}},
          {'t': 16, 'kind': 'view_record', 'run': 'RU1'}]
    (d / 'events.jsonl').write_text(chr(10).join(json.dumps(e) for e in ev), encoding='utf-8')
    (d / 'conversation.jsonl').write_text(json.dumps({'t': 15, 'kind': 'ctm', 'text': 'done'}), encoding='utf-8')
    r = report(d)
    assert "'1 delivery': 1" in r and '3 memory (message placement)' in r and "'select': 1" in r, r
    assert 'decision/escalate' in r and "opened an executor's original reply 1 times" in r and 'median 20.0 s' in r, r
    print('PASS report_counts_corrections_and_waiting')


if __name__ == '__main__':
    test_pilot_flow()
    test_report_counts_corrections_and_waiting()
