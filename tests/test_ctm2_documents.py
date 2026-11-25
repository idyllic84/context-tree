"""Offline tests for documents, file versions and object constraint index (no model calls)."""
from context_tree.ctm2 import documents as D
from context_tree.ctm2.store import Store


def setup():
    s = Store()
    t = s.add('task', {'title': 'T', 'status': 'running'}, at=0, source='user')
    r1 = s.add('run', {'reply': ''}, at=1, source='executor'); s.link(r1, 'serves', t, at=1, source='ctm')
    return s, t, r1


def test_file_versions_link_run_task_and_previous_version():
    s, t, r1 = setup()
    D.record_file_versions(s, run=r1, task=t, tools=[{'name': 'Edit', 'path': 'D:\\r\\a.py'}, {'name': 'Read', 'path': 'D:\\r\\b.py'}], at=1)
    r2 = s.add('run', {'reply': ''}, at=2, source='executor')
    v2 = D.record_file_versions(s, run=r2, task=t, tools=[{'name': 'write', 'path': 'D:/r/a.py'}], at=2)
    docs, files = D.index(s, [t], at=3)
    assert [f['path'] for f in files] == ['D:/r/a.py']          # read-only access is not a produced file
    assert s.db.execute("select count(*) from edges where src=? and rel='prev'", (v2[0],)).fetchone()[0] == 1


def test_knowledge_document_sections_and_staleness():
    s, t, r1 = setup()
    dec = s.add('decision', {'statement': 'use A'}, at=1, source='user')
    did = D.create_document(s, kind='knowledge', title='How to test', use_when='before running e2e', text='intro', task=t, run=r1, at=1,
                            source='executor', cites=[dec])
    D.update_section(s, did, 'steps', 'run x', run=r1, task=t, at=2, source='executor', cites=[dec])
    assert set(D.latest(s, did)['data']['sections']) == {'', 'steps'}
    D.mark_stale_on_decision(s, dec, at=3)
    assert D.is_stale(s, did)
    D.update_section(s, did, 'steps', 'run y', run=r1, task=t, at=4, source='executor')
    assert not D.is_stale(s, did)


def test_single_writer():
    s, t, r1 = setup()
    did = D.create_document(s, kind='report', title='r', use_when='w', text='x', task=t, at=1, source='executor')
    r2 = s.add('run', {'reply': ''}, at=2, source='executor')
    assert D.assign_writer(s, did, r1, at=2) and not D.assign_writer(s, did, r2, at=2)
    D.release_writer(s, did, r1, at=3)
    assert D.assign_writer(s, did, r2, at=4)


def test_object_constraint_index_and_write_proposal():
    s, t, r1 = setup()
    c = s.add('constraint', {'statement': 'transport must not expose sample rate', 'kind': 'object'}, at=1, source='user')
    D.index_object_constraint(s, constraint=c, obj='transport', working_dir='D:/r', at=1)
    assert [x['id'] for x in D.object_constraints(s, 'D:/r', at=2)] == [c]
    assert not s.items('pending')          # CTM's record and its proposal come from objectfiles.sync, not from executors


def test_paths_from_any_client_have_one_identity():
    n = D.norm_path
    vs = n('{"file:///d%3A/work/acme/docs/plan.md": {"$mid": 1, "path": "/d:/work/acme/docs/plan.md", "scheme": "file"}}')
    assert vs.lower() == 'd:/work/acme/docs/plan.md'
    assert n('docs/plan.md', 'D:' + chr(92) + 'work' + chr(92) + 'acme').lower() == vs.lower()
    assert n('file:///d%3A/work/acme/docs/plan.md').lower() == vs.lower()
    assert n('D:/work/acme/x/../docs/plan.md').lower() == vs.lower()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn(); print('PASS', name)
