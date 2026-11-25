"""One modifying executor per working directory (concept 3.6): a second request for the same directory waits for the
first executor's round; read-only executors are not held. Fake sessions, no processes."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.pilot.app import Pilot


class FakeSession:
    def __init__(self, run_id, task, cwd, modifies=True, busy=False):
        self.run_id, self.task, self.cwd, self.modifies, self.busy, self.alive = run_id, task, cwd, modifies, busy, True
        self.readonly = not modifies; self.prompts = []
    def prompt(self, text, turn):
        self.prompts.append(text); self.busy = True; return {'success': True}
    def state(self): return {}


def test_same_directory_waits():
    root = tempfile.mkdtemp(); repo = os.path.join(root, 'repo'); os.makedirs(repo)
    p = Pilot(root, ctm_options={'embed': lambda ts: [[1.0, 0.0] for _ in ts]})
    try:
        def setup():
            t = p.ctm.tree
            a = t.add('A', 'work A', None, None, 0, 0.0, working_dir=repo); b = t.add('B', 'work B', None, None, 1, 1.0, working_dir=repo.upper())
            c = t.add('C', 'read only', None, None, 2, 2.0, working_dir=repo)
            ra, rb, rc = (p.store.add('run', {'mode': m, 'status': 'active', 'state': 'idle'}, at=3.0, source='ctm') for m in ('session', 'session', 'readonly'))
            p.runs[ra] = FakeSession(ra, a, repo, busy=True)
            p.runs[rb] = FakeSession(rb, b, repo)
            p.runs[rc] = FakeSession(rc, c, repo, modifies=False)
            return a, b, c, ra, rb, rc
        a, b, c, ra, rb, rc = p.call(setup)
        p.call(lambda: p._send(rb, 'do B', 5, b))
        assert not p.runs[rb].prompts and len(p.queued) == 1                       # B waits: A is changing the same directory
        assert any(it['kind'] == 'notice' and 'waits for' in it['text'] for it in p.items)
        p.call(lambda: p._send(rc, 'question', 6, c, readonly=True))
        assert p.runs[rc].prompts == ['question']                                  # a read-only executor is not held
        p.runs[ra].busy = False
        p.call(lambda: p._drain(repo))
        assert p.runs[rb].prompts == ['do B'] and not p.queued                     # A's round ended: B starts
    finally:
        p.shutdown()
    print('PASS same_directory_waits')


def test_outside_change_observed():
    import time
    from context_tree.ctm2 import documents as D, execution as X
    root = tempfile.mkdtemp(); repo = os.path.join(root, 'repo'); os.makedirs(repo); f = os.path.join(repo, 'a.py')
    open(f, 'w').write('x = 1')
    p = Pilot(root, ctm_options={'embed': lambda ts: [[1.0, 0.0] for _ in ts]})
    try:
        t0 = time.time() - 100
        def setup():
            t = p.ctm.tree
            a = t.add('A', 'work A', None, None, 0, t0, working_dir=repo); b = t.add('B', 'work B', None, None, 1, t0, working_dir=repo)
            ra = p.store.add('run', {'mode': 'session', 'status': 'active', 'state': 'idle'}, at=t0, source='ctm'); p.store.link(ra, 'serves', a, at=t0, source='ctm')
            rb = p.store.add('run', {'mode': 'session', 'status': 'active', 'state': 'idle'}, at=t0, source='ctm'); p.store.link(rb, 'serves', b, at=t0, source='ctm')
            D.record_file_versions(p.store, run=ra, task=a, tools=[{'name': 'write', 'path': f}], at=t0, working_dir=repo)
            D.record_file_versions(p.store, run=rb, task=b, tools=[{'name': 'edit', 'path': f}], at=t0 + 1, working_dir=repo)
            return a, b, ra, rb
        a, b, ra, rb = p.call(setup)
        os.utime(f, (time.time(), time.time()))                           # the user edits the file outside the executors
        p.call(lambda: p._observe_outside_changes(time.time()))
        def check():
            v = p.store.db.execute("select source from items where type='file_version' order by at desc limit 1").fetchone()[0]
            notes = p.store.db.execute("select count(*) from edges e join items i on i.id=e.src where e.rel='forwarded_to' and i.type='notice' "
                                       "and i.data like '%(the user)%'").fetchone()[0]
            return v, notes
        v, notes = p.call(check)
        assert v == 'user' and notes == 2                                    # both executors involving the file are told
        p.call(lambda: p._observe_outside_changes(time.time() + 5))         # seen once, not again
        assert p.call(lambda: p.store.db.execute("select count(*) from items where type='file_version'").fetchone()[0]) == 3
    finally:
        p.shutdown()
    print('PASS outside_change_observed')


def test_long_round_milestone():
    import time
    import context_tree.pilot.app as A
    root = tempfile.mkdtemp(); repo = os.path.join(root, 'repo'); os.makedirs(repo)
    p = Pilot(root, ctm_options={'embed': lambda ts: [[1.0, 0.0] for _ in ts]})
    old = A.MILESTONE_S; A.MILESTONE_S = 0.5
    try:
        def setup():
            a = p.ctm.tree.add('A', 'work A', None, None, 0, 0.0, working_dir=repo)
            ra = p.store.add('run', {'mode': 'session', 'status': 'active', 'state': 'working'}, at=1.0, source='ctm'); p.store.link(ra, 'serves', a, at=1.0, source='ctm')
            return a, ra
        a, ra = p.call(setup)
        sess = FakeSession(ra, a, repo, busy=True); sess.started_at = time.time() - 1; sess._last_text = 'Finished the parser changes, running the tests'; sess.turn = 3
        p._on_event(sess, {'type': 'tool_execution_start', 'toolName': 'bash'})
        p._on_event(sess, {'type': 'tool_execution_start', 'toolName': 'bash'})       # within the interval: once
        rows = p.call(lambda: [r['data'] for r in p.store.items('progress', about=a)])
        assert len(rows) == 1 and rows[0]['milestone'] and 'running the tests' in rows[0]['done']
    finally:
        A.MILESTONE_S = old; p.shutdown()
    print('PASS long_round_milestone')


def test_ctm_md_written_by_an_executor_stays_local():
    """A ctm.md an executor writes inside a git repository goes into the repository's local exclude list (never committed)."""
    import subprocess, tempfile
    from pathlib import Path
    from context_tree.pilot.app import Pilot
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(['git', 'init', '-q', d], check=True, creationflags=0x08000000 if os.name == 'nt' else 0)
        sub = Path(d) / 'config'; sub.mkdir(); (sub / 'ctm.md').write_text('ctm: rule', encoding='utf-8')
        done = Pilot._keep_ctm_md_local([{'name': 'write', 'path': str(sub / 'ctm.md'), 'success': True}])
        ex = (Path(d) / '.git' / 'info' / 'exclude').read_text(encoding='utf-8').splitlines()
        assert done and 'ctm.md' in [l.strip() for l in ex], ex
        Pilot._keep_ctm_md_local([{'name': 'write', 'path': str(sub / 'ctm.md'), 'success': True}])     # written twice: listed once
        assert [l.strip() for l in (Path(d) / '.git' / 'info' / 'exclude').read_text(encoding='utf-8').splitlines()].count('ctm.md') == 1
        st = subprocess.run(['git', '-C', d, 'status', '--porcelain'], capture_output=True, text=True, creationflags=0x08000000 if os.name == 'nt' else 0).stdout
        assert 'ctm.md' not in st, st


if __name__ == '__main__':
    test_same_directory_waits(); test_outside_change_observed(); test_long_round_milestone()
    test_ctm_md_written_by_an_executor_stays_local(); print('PASS ctm_md_written_by_an_executor_stays_local')
