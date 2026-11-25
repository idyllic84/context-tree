"""Behavior guidance is exported as files the executor can read; the index gives the path (concept 3.6)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from context_tree.ctm2 import documents as D, model as MD, root as R  # noqa: E402
from context_tree.ctm2.store import Store  # noqa: E402


def test_behavior_files():
    d = tempfile.mkdtemp()
    s = Store(os.path.join(d, 'ctm.sqlite')); R.ensure_root(s)
    old = MD.ask
    MD.ask = lambda prompt, payload, **kw: ({'items': [{'i': 0, 'doc': None, 'title': 'Starting subprocesses', 'use_when': 'when starting subprocesses or sub-agents'}]}, {})
    try:
        D.file_behavior(s, [{'statement': 'Start subprocesses without opening a window', 'use_when': 'when starting subprocesses'}], at=1.0, turn=1, model='stub')
    finally:
        MD.ask = old
    docs = D.behavior_docs(s)
    assert len(docs) == 1
    f = D.behavior_file(s, docs[0]['id'])
    assert os.path.exists(f) and 'Start subprocesses without opening a window' in open(f, encoding='utf-8').read()
    idx = D.behavior_index(s)
    assert idx and f in idx[0] and 'when starting subprocesses or sub-agents' in idx[0]
    assert D.behavior_file(Store(), 'X') is None                       # in memory: nothing to export
    # several statements of one call that start the same new document go into one document
    MD.ask = lambda prompt, payload, **kw: ({'items': [{'i': 0, 'doc': None, 'title': 'Git operations', 'use_when': 'when using git'},
                                                       {'i': 1, 'doc': None, 'title': 'Git operations', 'use_when': 'when using git'},
                                                       {'i': 2, 'doc': None, 'title': 'Starting subprocesses', 'use_when': 'when starting subprocesses'}]}, {})
    try:
        D.file_behavior(s, [{'statement': 'Look at the diff before committing'}, {'statement': 'Never force push'}, {'statement': 'Subprocesses must be stoppable'}], at=2.0, turn=2, model='stub')
    finally:
        MD.ask = old
    titles = [d['data'].get('title') for d in D.behavior_docs(s)]
    assert sorted(titles) == ['Git operations', 'Starting subprocesses'], titles
    git = [d for d in D.behavior_docs(s) if d['data'].get('title') == 'Git operations'][0]
    body = open(D.behavior_file(s, git['id']), encoding='utf-8').read()
    assert 'Look at the diff before committing' in body and 'Never force push' in body
    print('PASS behavior_files')


if __name__ == '__main__':
    test_behavior_files()
