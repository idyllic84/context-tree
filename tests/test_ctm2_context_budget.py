"""Resolution by budget (concept 3.2): a new executor's initial context over its character budget lowers the farthest parts
first (the farther siblings' exchanges, then the recent conversation; the nearest sibling last); the task, its constraints and the user's words stay."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2.store import Store
from context_tree.ctm2 import pipeline as P, ref as REF, deliver as DV, remember as RM, context as C

H = 3600.0


class Script:
    def __init__(self): self.q = {}
    def __call__(self, system, payload, **kw):
        q = self.q.get(kw.get('role')) or []
        out = q.pop(0) if q else {}
        return (out(payload) if callable(out) else out), {}


def test_budget_lowers_far_parts_first():
    sc = Script(); REF.ask = DV.ask = RM.ask = sc
    s = Store(); ctm = P.CTM(s, model='stub', embed=lambda ts: [[1.0, 0.0] for _ in ts])
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'Project', 'purpose': 'a project'}}]}]
    root = ctm.on_message(0, 0.0, 'Start a project', recent=[], previous_reply='', working_dir='D:/r')['node']
    for k, title in enumerate(['Sibling one', 'Sibling two'], start=1):
        sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
        sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': title, 'purpose': title, 'parent': root}}]}]
        n = ctm.on_message(k, k * H, f'{title}: ' + 'a very long requirement' * 300, recent=[], previous_reply='', working_dir='D:/r')['node']
        ctm.on_reply(k, k * H + 1, n, '..', 'reply' * 400, tools=[], progress={'done': f'{title} is done', 'open': [], 'failed': []})
    sc.q['ref'] = [{'modes': ['new'], 'entities': []}]
    sc.q['deliver'] = [{'deliveries': [{'part': 'all', 'to': 'new', 'new': {'title': 'This task', 'purpose': 'This task', 'parent': root}}]}]
    sc.q['remember'] = [lambda p: {'constraints': [{'statement': 'only change the transport directory', 'kind': 'task', 'node': p['deliveries'][0]['node']}]}]
    old = C.BUDGET
    try:
        C.BUDGET = None
        r = ctm.on_message(5, 5 * H, 'Do this task, only change the transport directory', recent=[], previous_reply='', working_dir='D:/r')
        x = r['node']
        full = C.initial_context(s, x, turn=5, at=5 * H + 0.5, message='Do this task, only change the transport directory')
        assert full.count('Latest exchanges (original text):') == 2 and 'a very long requirement' in full     # both siblings with their original exchanges
        C.BUDGET = len(full) // 2
        small = C.initial_context(s, x, turn=5, at=5 * H + 0.5, message='Do this task, only change the transport directory')
        assert len(small) < len(full) and 'for length' in small
        far = small.split('### Sibling one')[1].split('###')[0] if '### Sibling one' in small else ''
        assert 'Latest exchanges (original text)' not in far                                 # the farther sibling loses its exchanges first
        assert 'only change the transport directory' in small and 'Sibling two is done' in small and small.rstrip().endswith('Do this task, only change the transport directory')
    finally:
        C.BUDGET = old
    print('PASS budget_lowers_far_parts_first')


def test_quoted_headings_do_not_open_sections():
    """An executor reply quoted into the context keeps its markdown headings from becoming sections of the context."""
    from context_tree.ctm2 import context as CX
    nl = chr(10)
    out = CX._flat(nl.join(['Conclusion', '## Please confirm', '  ### Subsection', '#tag stays']))
    assert not any(l.startswith('#') and not l.startswith('#tag') for l in out.split(nl)) and '\\## Please confirm' in out and '#tag stays' in out

if __name__ == '__main__':
    test_budget_lowers_far_parts_first()
    test_quoted_headings_do_not_open_sections(); print('PASS quoted_headings_do_not_open_sections')
