"""Documents, files and objects (concept model v2: 3.1 Document/FileVersion/object nodes, 3.5 object constraints,
3.6 documents, 3.7 links; files produced by a run are linked to the task).

- Files: every file an executor wrote or edited (from its trace) becomes a file version produced by that run, linked to the
  previous version of the same path and to the task (involves). The working directory is the boundary; branches and
  commits are execution details.
- Documents: kinds knowledge / deliverable / report / plan / material, each with a "use when" line; versions link to the
  producing run, the task and the decisions they cite; knowledge documents change section by section; only one writer
  at a time; a document citing a replaced decision, or describing a file that changed, is marked stale and updated the
  next time it is used.
- Object constraints: CTM indexes them by object (file, directory or path pattern) and proposes the annotation or the
  ctm.md entry to write; writing files happens through an executor in the working directory (runtime integration).
"""
import json

WRITE_TOOLS = {'Edit', 'edit', 'Write', 'write', 'copilot_applyPatch', 'copilot_createFile', 'copilot_replaceString',
               'copilot_multiReplaceString', 'str_replace_editor', 'apply_patch', 'create_file', 'insert_edit_into_file'}
NL = chr(10)
KINDS = ('knowledge', 'deliverable', 'report', 'plan', 'material', 'behavior', 'research')
SECTIONED = ('knowledge', 'behavior', 'research')


def norm_path(p, working_dir=''):
    """One canonical form for a file path from any tool trace: a JSON object keyed by a file URI (VS Code chat), a file URI,
    a Windows or POSIX absolute path, or a path relative to the working directory. Relative paths are joined to the working
    directory, so the same file has the same identity (the lower-cased path) across clients."""
    import json, posixpath
    from urllib.parse import urlparse, unquote
    p = (p or '').strip()
    if p.startswith('{'):
        try:
            obj = json.loads(p)
            key = next(iter(obj)) if isinstance(obj, dict) and obj else ''
            val = obj.get(key) if isinstance(obj, dict) else None
            p = key if key.startswith('file:') else ((val or {}).get('path') if isinstance(val, dict) else '') or key
        except (ValueError, StopIteration):
            pass
    if p.startswith('file:'):
        p = unquote(urlparse(p).path)
    p = p.replace(chr(92), '/')
    if len(p) > 2 and p[0] == '/' and p[2] == ':': p = p[1:]          # /d:/x -> d:/x
    if not (len(p) > 1 and p[1] == ':') and not p.startswith('/') and working_dir:
        p = norm_path(working_dir).rstrip('/') + '/' + p
    return posixpath.normpath(p) if p else p             # identities compare the lower-cased path (FILE:<path.lower()>)


def record_file_versions(store, *, run, task, tools, at, working_dir=''):
    """Link files written or edited in this run: file -> file_version (produced by the run, prev version), task involves file."""
    out = []
    for t in tools or []:
        if t.get('name') not in WRITE_TOOLS or not t.get('path') or t.get('success') is False: continue
        path = norm_path(t['path'], working_dir)
        fid = f'FILE:{path.lower()}'
        if not store.get(fid):
            store.add('file', {'path': path, 'working_dir': working_dir}, at=at, source='executor', id=fid)
        prev = store.db.execute("select v.id from items v join edges e on e.src=v.id and e.rel='version_of' and e.dst=? order by v.at desc, v.rowid desc limit 1",
                                (fid,)).fetchone()
        vid = store.add('file_version', {'path': path, 'tool': t.get('name')}, at=at, source='executor')
        store.link(vid, 'version_of', fid, at=at, source='ctm'); store.link(run, 'produced', vid, at=at, source='ctm')
        if prev: store.link(vid, 'prev', prev[0], at=at, source='ctm')
        if task and not store.db.execute("select 1 from edges where src=? and rel='involves' and dst=? and valid_to is null", (task, fid)).fetchone():
            store.link(task, 'involves', fid, at=at, source='ctm')
        mark_stale_on_file_change(store, fid, at=at, by_run=run)
        _notify_sessions(store, fid, path, at=at, by_run=run, by_task=task)
        out.append(vid)
    return out


def _notify_sessions(store, fid, path, *, at, by_run=None, by_task=None, source='executor'):
    """Sessions of other tasks involving the file get a notice (forwarded with their next message) instead of ending."""
    from . import execution as X
    notified = []
    for (task,) in store.db.execute("select src from edges where rel='involves' and dst=? and valid_to is null", (fid,)).fetchall():
        if task == by_task: continue
        run = X.active_run(store, task)
        if run and run['id'] != by_run:
            who = (store.get(by_task) or {}).get('data', {}).get('title') if by_task else ('the user' if source == 'user' else source)
            nid = store.add('notice', {'text': f'The file {path} was changed elsewhere ({who})'}, at=at, source='ctm')
            X.forward(store, run_id=run['id'], item_id=nid, at=at, why='a file it works on was changed elsewhere'); notified.append(run['id'])
    return notified


def create_document(store, *, kind, title, use_when, text, task, run=None, at, source, cites=(), path=None):
    assert kind in KINDS, kind
    did = store.add('document', {'kind': kind, 'title': title, 'use_when': use_when, 'path': path}, at=at, source=source)
    store.link(did, 'about', task or 'ROOT', at=at, source='ctm')
    _new_version(store, did, {'text': text} if kind not in SECTIONED else {'sections': {'': text} if text else {}}, run=run, task=task, at=at, source=source, cites=cites)
    return did


def _new_version(store, did, body, *, run, task, at, source, cites=()):
    prev = store.db.execute("select v.id from items v join edges e on e.src=v.id and e.rel='version_of' and e.dst=? order by v.at desc, v.rowid desc limit 1",
                            (did,)).fetchone()
    vid = store.add('doc_version', body, at=at, source=source)
    store.link(vid, 'version_of', did, at=at, source='ctm')
    if prev: store.link(vid, 'prev', prev[0], at=at, source='ctm')
    if run: store.link(run, 'produced', vid, at=at, source='ctm')
    if task: store.link(vid, 'for_task', task, at=at, source='ctm')
    for d in cites:
        store.link(vid, 'cites', d, at=at, source='ctm')
        if not store.db.execute("select 1 from edges where src=? and rel='detailedIn' and dst=?", (d, did)).fetchone():
            store.link(d, 'detailedIn', did, at=at, source='ctm')
    store.event(did, 'fresh', at=at, source='ctm')
    return vid


def latest(store, did):
    r = store.db.execute("select v.id from items v join edges e on e.src=v.id and e.rel='version_of' and e.dst=? order by v.at desc, v.rowid desc limit 1", (did,)).fetchone()
    return store.get(r[0]) if r else None


def update_section(store, did, section, text, *, run, task, at, source, cites=()):
    """Knowledge documents change section by section; other sections are carried over unchanged."""
    cur = latest(store, did)
    sections = dict((cur or {}).get('data', {}).get('sections') or {})
    sections[section] = text
    return _new_version(store, did, {'sections': sections, 'changed_section': section}, run=run, task=task, at=at, source=source, cites=cites)


def assign_writer(store, did, run, *, at):
    """One writer at a time: returns False when another run currently holds the document."""
    cur = store.db.execute("select src from edges where dst=? and rel='writing' and valid_to is null", (did,)).fetchone()
    if cur and cur[0] != run: return False
    if not cur: store.link(run, 'writing', did, at=at, source='ctm')
    return True


def release_writer(store, did, run, *, at):
    store.unlink(run, 'writing', did, at=at)


def is_stale(store, did):
    ev = store.db.execute("select kind from events where item=? and kind in ('stale','fresh') order by at desc, rowid desc limit 1", (did,)).fetchone()
    return bool(ev and ev[0] == 'stale')


def mark_stale_on_decision(store, decision_id, *, at):
    """Documents whose current version cites a decision that was replaced are stale (updated at next use)."""
    for (vid,) in store.db.execute("select src from edges where rel='cites' and dst=?", (decision_id,)).fetchall():
        did = store.db.execute("select dst from edges where src=? and rel='version_of'", (vid,)).fetchone()
        if did and latest(store, did[0])['id'] == vid:
            store.event(did[0], 'stale', at=at, source='ctm', data={'because': decision_id})


def mark_stale_on_file_change(store, file_id, *, at, by_run=None):
    for (did,) in store.db.execute("select src from edges where rel='describes' and dst=? and valid_to is null", (file_id,)).fetchall():
        store.event(did, 'stale', at=at, source='ctm', data={'because': file_id, 'run': by_run})


def index(store, nodes, at):
    """Document and file index for an execution context: what exists for these tasks, what it is for, whether stale."""
    docs, files = [], []
    for n in nodes:
        for r in store.items('document', about=n, at=at):
            d = r['data']
            docs.append({'id': r['id'], 'title': d.get('title'), 'kind': d.get('kind'), 'use_when': d.get('use_when'), 'path': d.get('path'),
                         'stale': is_stale(store, r['id']), 'turn': r['turn']})
        for (fid,) in store.db.execute("select dst from edges where src=? and rel='involves' and at <= ?", (n, at)).fetchall():
            f = store.get(fid)
            if f and f['type'] == 'file':
                files.append({'id': fid, 'path': f['data'].get('path')})
    seen, uniq = set(), []
    for f in files:
        if f['id'] not in seen: seen.add(f['id']); uniq.append(f)
    return docs, uniq


# ---- object constraints (3.5) -------------------------------------------------------------------------------------
def index_object_constraint(store, *, constraint, obj, working_dir, at):
    """obj: what the user named (file, module, directory, interface). CTM indexes the constraint under the object; its own
    ctm.md record and the annotation proposal to the user follow from the index (objectfiles.sync), not from executors."""
    key = f"OBJ:{norm_path(working_dir).lower()}::{(obj or '').strip().lower()}"
    if not store.get(key):
        store.add('object', {'name': obj, 'working_dir': working_dir}, at=at, source='ctm', id=key)
    store.link(constraint, 'about', key, at=at, source='ctm')
    return key


def object_constraints(store, working_dir, at):
    """Object constraints known in a working directory (for CTM's conflict check and queries; executors read them from files)."""
    prefix = f"OBJ:{norm_path(working_dir).lower()}::"
    out = []
    for (oid,) in store.db.execute("select id from items where type='object' and id like ?", (prefix + '%',)).fetchall():
        out += [dict(r, object=store.get(oid)['data'].get('name')) for r in store.items('constraint', about=oid, at=at, current_only=True)]
    return out


def observe_file_change(store, *, path, working_dir, at, source='user', by_run=None):
    """An observed change to a file not made by the current executors (S10): a file version with its source; executors
    whose task involves the file get a notice; documents describing it become stale."""
    from . import execution as X
    path = norm_path(path); fid = f'FILE:{path.lower()}'
    if not store.get(fid): store.add('file', {'path': path, 'working_dir': working_dir}, at=at, source='ctm', id=fid)
    vid = store.add('file_version', {'path': path, 'observed': True}, at=at, source=source)
    store.link(vid, 'version_of', fid, at=at, source='ctm')
    if by_run: store.link(by_run, 'produced', vid, at=at, source='ctm')
    mark_stale_on_file_change(store, fid, at=at, by_run=by_run)
    notified = _notify_sessions(store, fid, path, at=at, by_run=by_run, source=source)
    return vid, notified


def history(store, did):
    """Version history of a document (oldest first) for the document browser."""
    rows = store.db.execute("select v.id from items v join edges e on e.src=v.id and e.rel='version_of' and e.dst=? order by v.at, v.rowid", (did,)).fetchall()
    return [store.get(r[0]) for r in rows]


# ---- agent behavior guidance (concept 3.6: a third kind of knowledge, skill-like, outside the tree) -------------------------
FILE_BEHAVIOR = '''The user stated how agents should generally do a kind of operation (new). Below are the existing behavior guidance documents (title and when to use).
For each statement decide which document it goes into: one about the same kind of operation (doc: its id); otherwise a new one (doc is "new", with a title and when to use it, in the language the user writes in).
Output JSON only: {"items":[{"i":0,"doc":"DO3|new","title":"..","use_when":".."}]}'''


def behavior_docs(store, at=None):
    return [r for r in store.items('document', about='ROOT', at=at) if r['data'].get('kind') == 'behavior']


def file_behavior(store, statements, *, at, turn, model):
    """Store behavior guidance the user stated: each statement goes into the behavior document for that kind of operation
    (chosen by the model among existing ones, or a new one); active sessions are told at their next message."""
    from .model import ask
    from . import execution as X
    if not statements: return []
    docs = behavior_docs(store, at)
    out, _ = ask(FILE_BEHAVIOR, {'new': [dict(s, i=i) for i, s in enumerate(statements)],
                                 'documents': [{'id': d['id'], 'title': d['data'].get('title'), 'use_when': d['data'].get('use_when')} for d in docs]},
                 model=model, effort='low', role='behavior')
    ids = {d['id'] for d in docs}
    by_title = {(d['data'].get('title') or '').strip(): d['id'] for d in docs}   # one document per title, also within one call
    touched = []
    for it in out.get('items') or []:
        i = it.get('i')
        if not isinstance(i, int) or i >= len(statements): continue
        st = statements[i]
        title = (it.get('title') or st.get('statement', '')[:30]).strip()
        if it.get('doc') not in ids and title in by_title: it['doc'] = by_title[title]
        if it.get('doc') in ids:
            did = it['doc']
            sec, cur = practice(store, did)
            update_section(store, did, sec, (cur + chr(10) if cur else '') + f"- [turn {turn}] {st.get('statement')}", run=None, task=None, at=at, source='user')
        else:
            did = create_document(store, kind='behavior', title=title,
                                  use_when=it.get('use_when') or st.get('use_when') or '', text='', task=None, at=at, source='user')
            update_section(store, did, 'Practice', f"- [turn {turn}] {st.get('statement')}", run=None, task=None, at=at, source='user')
            ids.add(did); by_title[title] = did
        touched.append(did)
        for (rid,) in store.db.execute("select id from items where type='run' and data like '%\"status\": \"active\"%'").fetchall():
            if store.get(rid)['data'].get('mode') in ('session', 'research'):
                nid = store.add('notice', {'text': f"The behavior guidance '{store.get(did)['data'].get('title')}' has a new practice: {st.get('statement')}"}, at=at, source='ctm')
                X.forward(store, run_id=rid, item_id=nid, at=at, why='behavior guidance updated')
    export_behavior(store, set(touched))
    return touched


def practice(store, did):
    """A behavior document's one section (its name as stored, whatever the language it was written in) and its text."""
    secs = ((latest(store, did) or {}).get('data', {}).get('sections') or {})
    return next(iter(secs.items()), ('Practice', ''))


def behavior_file(store, did):
    """Where a behavior document is exported for executors to read: <CTM directory>/behavior/<id>.md (None in memory)."""
    import os
    path = getattr(store, 'path', None)
    if not path or path == ':memory:': return None
    return os.path.join(os.path.dirname(os.path.abspath(path)), 'behavior', f'{did}.md')


def export_behavior(store, dids=None):
    """Write behavior documents (all, or the given ones) as files; the executor reads one when it does that kind of thing."""
    import os
    out = []
    for d in behavior_docs(store):
        if dids is not None and d['id'] not in dids: continue
        f = behavior_file(store, d['id'])
        if not f: continue
        os.makedirs(os.path.dirname(f), exist_ok=True)
        body = practice(store, d['id'])[1]
        text = f"# {d['data'].get('title')}" + NL + NL + f"When to use: {d['data'].get('use_when') or ''}" + NL + NL + '## Practice' + NL + body + NL
        with open(f, 'w', encoding='utf-8') as fh: fh.write(text)
        out.append(f)
    return out


def behavior_index(store, at=None):
    import os
    out = []
    for d in behavior_docs(store, at):
        f = behavior_file(store, d['id'])
        where = f"read {f}" if f and os.path.exists(f) else f"document {d['id']}"
        out.append(f"'{d['data'].get('title')}' (when to use: {d['data'].get('use_when') or ''}; {where})")
    return out
