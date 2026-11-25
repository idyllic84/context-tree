"""Write-back of an executor reply into the store (concept model v2:
5.1 step 2, 5.2 item 6, 3.4 task content, 3.5 constraint placement, 3.6 decisions, section 4 replacement).

Reply (concept 5.2 item 6; agent reply analysis): the raw reply is kept as the run's evidence; CTM writes one brief summary
into the task's progress (done, changed files and documents, verification with trace vs self-report, open issues, failed
attempts), observed at that time; long content still in the reply is stored as a document. CTM does not extract every fact
from replies: details stay in documents and run evidence and are read on demand; what the user then says about the reply
decides what becomes a decision, a rejected approach or a pending item.
The items in force that a user's new words may replace are collected by in_force (used by ctm2.remember).
"""
from . import documents as D
from . import lifecycle as L
from . import root as R

ROOT = 'ROOT'
FACT_TYPE = {'environment': 'environment', 'location': 'environment', 'identifier': 'identifier', 'state': 'state', 'procedure': 'procedure'}
AUTHORITATIVE = ('constraint', 'decision', 'environment', 'identifier', 'state', 'guidance')


def project_of(working_dir):
    return (working_dir or '').replace(chr(92), '/').rstrip('/').split('/')[-1].lower()


def line_nodes(tree, node):
    if node not in tree.nodes: return set()
    root = tree.root(node)
    return {n for n in tree.nodes if tree.root(n) == root}


def in_force(store, tree, node, at, object_keys=()):
    """User-stated items currently in force that new user items may replace: on the node's work line, the object index
    entries involved, the root. Constraints and decisions change only by the user's words, never by an executor report."""
    out = []
    for n in sorted(line_nodes(tree, node)):
        for typ in AUTHORITATIVE:
            out += store.items(typ, about=n, at=at, current_only=True)
    for key in [ROOT, *object_keys]:
        out += store.items('constraint', about=key, at=at, current_only=True)
    out += store.items('environment', about=ROOT, at=at, current_only=True)
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: r['at']):
        if r['id'] not in seen and r['source'] == 'user': seen.add(r['id']); uniq.append(r)
    return uniq


def object_keys(store, working_dir):
    prefix = f"OBJ:{D.norm_path(working_dir).lower()}::"
    return [r[0] for r in store.db.execute("select id from items where type='object' and id like ?", (prefix + '%',)).fetchall()]


def _write_fact(store, tree, f, node, turn, at, source):
    """Fact mapping (concept 3.4): environment and locations -> the task's scope (replaceable like constraints); common
    environments -> the root; identifiers (version, PR number) and states (test results) -> progress with time; procedures ->
    the work line's knowledge document."""
    stmt = f.get('statement') or ''
    if f.get('kind') == 'deadline':                         # deadlines and event conditions belong to the task (section 4)
        if node in tree.nodes:
            store.patch(node, {'deadline': stmt}, at=at, source=source, reason='a deadline the user stated')
        return []
    typ = FACT_TYPE.get(f.get('kind'), 'environment')
    if typ == 'environment':
        if f.get('common') or node not in tree.nodes:
            return [R.add_environment(store, stmt, volatile=bool(f.get('volatile')), at=at, source=source)]
        fid = store.add('environment', {'statement': stmt, 'volatile': bool(f.get('volatile'))}, at=at, source=source, turn=turn,
                        observed_at=at if f.get('volatile') else None)
        store.link(fid, 'about', node, at=at, source='ctm')
        return [fid]
    if typ in ('identifier', 'state'):
        pid = store.add('progress', {'note': stmt, 'stated_by': 'user', 'kind': typ}, at=at, source=source, turn=turn, observed_at=at)
        store.link(pid, 'about', node if node in tree.nodes else ROOT, at=at, source='ctm')
        return []
    # procedure -> knowledge document of the work line (CTM is its writer for user-stated procedures)
    line_root = tree.root(node) if node in tree.nodes else ROOT
    docs = [d for d in store.items('document', about=line_root, at=at) if d['data'].get('ctm_notes')]
    if docs:
        cur = D.latest(store, docs[0]['id'])['data'].get('sections', {}).get('Practices the user described', '')
        D.update_section(store, docs[0]['id'], 'Practices the user described', (cur + chr(10) if cur else '') + f'- [turn {turn}] {stmt}', run=None, task=node, at=at, source='ctm')
    else:
        title = (store.get(line_root) or {}).get('data', {}).get('title', 'global')
        did = D.create_document(store, kind='knowledge', title=f'{title}: practices and notes', use_when='when you need to know how this line of work is run, tested or queried', text='',
                                task=line_root if line_root != ROOT else None, at=at, source='ctm')
        store.patch(did, {'ctm_notes': True}, at=at, source='ctm')
        D.update_section(store, did, 'Practices the user described', f'- [turn {turn}] {stmt}', run=None, task=node, at=at, source='ctm')
    return []


def write_reply(store, tree, *, turn, at, node, reply, progress, model, long_chars=3000, run_id=None, tools=None, working_dir='', progress_about=None):
    """progress: the brief summary of the reply (ctm2.progress PROMPT). No facts are extracted and nothing is replaced.
    run_id: the executor run this reply came from (a session may answer several times); without it a single-call run is
    recorded. progress_about: what the summary is about when it is not the task's own progress (a query answered by a read-only
    run or fork: the query record, linked to the task it asked about). Files the run wrote or edited become file versions linked to the run and the task; a long reply is stored as a
    report document produced by the run."""
    log = {'calls': 0, 'usage': [], 'replaced': [], 'created': [], 'files': []}
    if node not in tree.nodes: node = None
    if run_id is None:
        run_id = store.add('run', {'reply': reply or '', 'mode': 'single', 'status': 'ended'}, at=at, source='executor', turn=turn)
        store.link(run_id, 'serves', node or ROOT, at=at, source='ctm')
        ex = run_id
    else:
        ex = store.add('exchange', {'reply': reply or ''}, at=at, source='executor', turn=turn)
        store.link(ex, 'in_run', run_id, at=at, source='ctm')
    log['run'], log['exchange'] = run_id, ex
    if tools:
        log['files'] = D.record_file_versions(store, run=run_id, task=node, tools=tools, at=at, working_dir=working_dir)
    if not progress: return log
    pid = store.add('progress', {k: progress.get(k) for k in ('done', 'changed', 'verified', 'open', 'failed')}, at=at, source='ctm', turn=turn, observed_at=at)
    store.link(pid, 'about', progress_about or node or ROOT, at=at, source='ctm'); store.link(pid, 'summarizes', ex, at=at, source='ctm')
    if reply and len(reply) > long_chars:
        did = D.create_document(store, kind='report', title=(progress.get('done') or '')[:80], use_when='when the details of this execution are needed', text=reply,
                                task=node, run=run_id, at=at, source='executor')
        log['created'].append(did)
    return log
