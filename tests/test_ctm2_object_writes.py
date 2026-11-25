"""Object rules are CTM's own record (concept 3.5): CTM writes, rewrites and removes its ctm.md entries itself (kept local),
when an executor that did not hear the rule needs them; it proposes source annotations to the user and puts nothing of this
into an executor's input. Model calls are stubbed."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM

H = 3600.0


class Script:
    def __init__(self): self.q = {}
    def __call__(self, system, payload, **kw):
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def _repo():
    repo = tempfile.mkdtemp()
    subprocess.run(['git', 'init', '-q', repo], check=True, creationflags=0x08000000 if os.name == 'nt' else 0)
    return repo


def _ctm(repo, write=True):
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    ctm._choose_workdir = lambda *a, **k: repo
    ctm.write_object_files = write
    return sc, s, ctm


def _say(sc, ctm, repo, turn, at, text, title='', rules=(), replace=None, deliveries=None, memory=None):
    sc.q['ref'] = [{'modes': ['new'], 'entities': [{'said': repo, 'resolved': repo, 'type': 'identifier', 'role': 'target'}]}]
    sc.q['deliver'] = [{'deliveries': deliveries or [{'part': 'all', 'to': 'new', 'new': {'title': title, 'purpose': title}}]}]
    sc.q['remember'] = [memory or {'constraints': [{'statement': st, 'kind': 'object', 'scope': sc_} for st, sc_ in rules]}]
    if replace: sc.q['replace'] = [replace]
    return ctm.on_message(turn, at, text, recent=[], previous_reply='', working_dir='')


def _entries(path):
    return [l for l in open(path, encoding='utf-8').read().splitlines() if l.startswith('- [ctm:')] if os.path.exists(path) else []


def _sent(r):
    d = r['dispatches'][0]
    return d.get('forward') or d.get('context') or ''


def _old_like(p, text):
    return [x.get('id') for x in (p.get('current') or p.get('candidates') or []) if text in str(x)][:1]


def test_rules_reach_ctm_md_when_another_executor_needs_them():
    repo = _repo(); os.makedirs(os.path.join(repo, 'src', 'codec'))
    sc, s, ctm = _ctm(repo)
    root_md, codec_md = os.path.join(repo, 'ctm.md'), os.path.join(repo, 'src', 'codec', 'ctm.md')
    r = _say(sc, ctm, repo, 0, 0.0, f'In {repo}, change transport; remember: transport must not expose a sample rate parameter', 'Change transport',
             rules=[('transport must not expose a sample rate parameter', 'transport'), ('the codec only accepts 16k mono', 'src/codec')])
    assert not os.path.exists(root_md) and not r['object_files']['proposals']      # its own executor has it from the conversation
    # another work starts in the same repository: the entries are written before its executor starts
    r1 = _say(sc, ctm, repo, 1, 1 * H, f'In {repo}, add tests', 'Add tests')
    assert any('transport must not expose a sample rate parameter' in l for l in _entries(root_md)), _entries(root_md)    # not a path: the project root
    assert any('the codec only accepts 16k mono' in l for l in _entries(codec_md)), _entries(codec_md)         # a path: beside the object
    for x in (r, r1):
        assert 'In addition (this time only)' not in _sent(x) and 'ctm.md entry' not in _sent(x)                     # nothing of CTM's own business
    st = subprocess.run(['git', '-C', repo, 'status', '--porcelain', '--untracked-files=all'], capture_output=True, text=True).stdout
    assert 'ctm.md' not in st, st                                                                    # kept local
    props = r1['object_files']['proposals']
    assert len(props) == 2 and all('source comment' in p['text'] for p in props)
    assert all(s.get(p['pending'])['data']['kind'] == 'propose_annotation' for p in props)
    for p in props:                                                                                   # numbered pending items
        assert s.db.execute("select count(*) from edges where rel='shows' and dst=?", (p['pending'],)).fetchone()[0] == 1, p
    # offline (replays, tests) CTM leaves the user's directories alone
    repo2 = _repo(); sc2, s2, ctm2 = _ctm(repo2, write=False)
    _say(sc2, ctm2, repo2, 0, 0.0, f'In {repo2}, change transport', 'Change transport', rules=[('transport must not expose a sample rate parameter', 'transport')])
    _say(sc2, ctm2, repo2, 1, 1 * H, f'In {repo2}, add tests', 'Add tests')
    assert not os.path.exists(os.path.join(repo2, 'ctm.md'))
    print('PASS rules_reach_ctm_md_when_another_executor_needs_them')


def test_a_rule_refined_in_its_own_work_never_reaches_the_file():
    """The live case: a one-off request recorded as a rule, narrowed by the next message in the same work."""
    repo = _repo(); sc, s, ctm = _ctm(repo)
    md = os.path.join(repo, 'ctm.md')
    r = _say(sc, ctm, repo, 0, 0.0, f'In {repo}, sort the configuration by url', 'Sort the configuration', rules=[('the configuration is sorted by url alphabetically', 'config.json')])
    task = r['node']
    sc.q['replace'] = []
    r2 = _say(sc, ctm, repo, 1, 1 * H, 'Only sort the new part', deliveries=[{'part': 'all', 'to': 'existing', 'node': task}],
              memory={'constraints': [{'statement': 'sort only the new part by url', 'kind': 'task', 'node': task}]},
              replace=lambda p: {'items': [{'new': 0, 'replaces': [x['id'] for q in p['new'] for x in q['similar'] if 'by url alphabetically' in x['statement']][:1]}]})
    assert r2['dispatches'][0]['reused'] and not os.path.exists(md), _entries(md)
    _say(sc, ctm, repo, 2, 2 * H, f'In {repo}, add tests', 'Add tests')
    assert not _entries(md), _entries(md)                                   # replaced before it was ever due
    print('PASS a_rule_refined_in_its_own_work_never_reaches_the_file')


def test_answered_proposals_reach_the_executor_and_replaced_entries_leave():
    repo = _repo(); sc, s, ctm = _ctm(repo)
    md = os.path.join(repo, 'ctm.md')
    task = _say(sc, ctm, repo, 0, 0.0, f'In {repo}, change transport, with the timeout fixed at 30 seconds', 'Change transport', rules=[('the transport timeout is 30 seconds', 'transport')])['node']
    r1 = _say(sc, ctm, repo, 1, 1 * H, f'In {repo}, tidy the logs', 'Tidy the logs')                     # another work: the entry is written
    p30 = r1['object_files']['proposals'][0]['pending']; old = s.get(p30)['data']['constraint']
    r2 = _say(sc, ctm, repo, 2, 2 * H, '1 yes', deliveries=[{'part': 'all', 'to': 'existing', 'node': task, 'answers_pending': [p30]}])
    assert "The user is answering CTM's proposals" in _sent(r2) and 'the transport timeout is 30 seconds' in _sent(r2), _sent(r2)[-300:]
    assert s.get(p30)['data']['status'] == 'answered'
    # a new rule replaces it: the old entry goes; since an annotation may exist, CTM proposes updating it
    r3 = _say(sc, ctm, repo, 3, 3 * H, 'Make the timeout 60 seconds', deliveries=[{'part': 'all', 'to': 'existing', 'node': task}],
              rules=[('the transport timeout is 60 seconds', 'transport')],
              replace=lambda p: {'items': [{'new': 0, 'replaces': [x['id'] for q in p['new'] for x in q['similar'] if '30 seconds' in x['statement']][:1]}]})
    assert s.get(old)['replaced_at'] is not None
    assert not any('30 seconds' in l for l in _entries(md)), _entries(md)
    assert any('30 seconds' in p['text'] and 'Update' in p['text'] for p in r3['object_files']['proposals']), r3['object_files']
    print('PASS answered_proposals_reach_the_executor_and_replaced_entries_leave')


def test_a_rule_the_user_drops_leaves_ctm_md():
    """The user says a recorded rule no longer holds: it is recorded as what the user now wants, the replacement step takes the
    old rule out, and CTM removes its entry (a file left with its header only goes, its open proposal is taken back)."""
    repo = _repo(); sc, s, ctm = _ctm(repo)
    md = os.path.join(repo, 'ctm.md')
    task = _say(sc, ctm, repo, 0, 0.0, f'In {repo}, change transport', 'Change transport', rules=[('transport must not expose a sample rate parameter', 'transport')])['node']
    _say(sc, ctm, repo, 1, 1 * H, f'In {repo}, add tests', 'Add tests')
    rule = [c['id'] for c in s.items('constraint', at=2 * H) if 'sample rate' in c['data'].get('statement', '')][0]
    assert _entries(md)
    r = _say(sc, ctm, repo, 2, 2 * H, 'That sample rate rule is wrong, no need to follow it', deliveries=[{'part': 'all', 'to': 'memory', 'node': task}],
             memory={'decisions': [{'statement': 'transport no longer has to hide the sample rate parameter', 'type': 'decision', 'node': task}]},
             replace=lambda p: {'items': [{'new': 0, 'replaces': [x['id'] for q in p['new'] for x in q['similar'] if 'sample rate' in x['statement']][:1]}]})
    assert not r['dispatches'] and s.get(rule)['replaced_at'] is not None
    assert not os.path.exists(md)                                                    # CTM's file had nothing else: deleted
    assert len(r['object_files']['withdrawn']) == 1, r['object_files']                # its unanswered proposal is taken back
    r3 = _say(sc, ctm, repo, 3, 3 * H, 'Go on', deliveries=[{'part': 'all', 'to': 'existing', 'node': task}])
    assert 'transport must not expose a sample rate parameter -> replaced in [turn 2] by: transport no longer has to hide the sample rate parameter' in _sent(r3), _sent(r3)
    print('PASS a_rule_the_user_drops_leaves_ctm_md')


if __name__ == '__main__':
    test_rules_reach_ctm_md_when_another_executor_needs_them()
    test_a_rule_refined_in_its_own_work_never_reaches_the_file()
    test_answered_proposals_reach_the_executor_and_replaced_entries_leave()
    test_a_rule_the_user_drops_leaves_ctm_md()
