"""CTM's own record of object rules beside the objects (concept 3.5).

Object rules live in CTM's memory; CTM itself also writes them into ctm.md files next to the objects, where executors read them
before changing files. An entry is written when an executor that did not hear the user say it needs it: before an executor of
another work, or a new session, starts in that directory, when the work it was said in is finished, or at once when it was said
in no work. Until then the executor of that work has it from the conversation, which also carries its refinements and
replacements; a file read independently would lag behind them (2026-11-24: a one-off ordering request recorded as a rule was
written at once, the next message narrowed it, and the executor read the stale entry and stopped). A ctm.md is CTM's file: it stays on this machine (the repository's local exclude list gets it), executors
only read it, and CTM rewrites or removes an entry as soon as its rule is replaced. Annotations in source files are the user's
code: CTM proposes one (a numbered pending item) and an executor writes it only after the user answers.

CTM writes nothing but files named ctm.md inside the work's directory. Writing is on in the pilot (`CTM.write_object_files`);
offline tests and replays leave the user's directories alone.
"""
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

NAME = 'ctm.md'
HEADER = '''# ctm.md

Object rules maintained by CTM: follow them when changing these objects; when one conflicts with the user's request this time, stop and report it to CTM.
This file stays on this machine and is not committed; executors read it and do not change it.'''
_ENTRY = re.compile(r'^- \[ctm:(?P<id>[A-Za-z0-9_-]+)\]')


def target_dir(working_dir, obj):
    """The closest directory holding the object when it names a path in the work's directory, else the project root."""
    if not working_dir or not Path(working_dir).is_dir(): return None
    root = Path(working_dir).resolve()
    o = (obj or '').strip().strip('`').replace('\\', '/')
    for cand in ([Path(o)] if o and Path(o).is_absolute() else []) + ([root / o] if o else []):
        try:
            c = cand.resolve()
            if c.exists() and (c == root or root in c.parents):
                return c if c.is_dir() else c.parent
        except OSError:
            continue
    return root


def _lines(path):
    return path.read_text(encoding='utf-8', errors='ignore').splitlines() if path.exists() else []


def upsert(directory, entry_id, obj, statement, when):
    """Write (or rewrite) one entry; returns the file."""
    path = Path(directory) / NAME
    line = f"- [ctm:{entry_id}] <{obj}> {statement} (the user's decision, {when})"
    lines = _lines(path)
    kept = [l for l in lines if not ((m := _ENTRY.match(l)) and m.group('id') == entry_id)]
    body = '\n'.join(kept).rstrip('\n') if kept else HEADER.rstrip('\n')
    path.write_text(body + '\n' + line + '\n', encoding='utf-8')
    keep_local(path)
    return path


def remove(path, entry_id):
    """Take one entry out; a file left with no entries is deleted (it is CTM's own file; its header may be from any version)."""
    path = Path(path)
    lines = _lines(path)
    kept = [l for l in lines if not ((m := _ENTRY.match(l)) and m.group('id') == entry_id)]
    if len(kept) == len(lines): return False
    body = '\n'.join(kept).strip()
    if not any(_ENTRY.match(l) for l in kept):
        path.unlink(); return True
    path.write_text(body + '\n', encoding='utf-8')
    return True


def _same_dir(a, b):
    """One directory contains the other (an object recorded for a project, an executor working in it or in a part of it)."""
    a, b = [str(x or '').replace('\\', '/').rstrip('/').lower() + '/' for x in (a, b)]
    return len(a) > 1 and len(b) > 1 and (a.startswith(b) or b.startswith(a))


def keep_local(path):
    """The repository's local exclude list gets 'ctm.md' (never committed; nothing in the repository changes)."""
    p = Path(path)
    try:
        r = subprocess.run(['git', '-C', str(p.parent), 'rev-parse', '--git-path', 'info/exclude'], capture_output=True, text=True,
                           timeout=15, creationflags=0x08000000 if os.name == 'nt' else 0)
        if r.returncode != 0 or not r.stdout.strip(): return None
        ex = Path(r.stdout.strip())
        if not ex.is_absolute(): ex = p.parent / ex
        lines = _lines(ex)
        if NAME not in [l.strip() for l in lines]:
            ex.parent.mkdir(parents=True, exist_ok=True)
            with open(ex, 'a', encoding='utf-8') as f: f.write(('' if not lines or not lines[-1].strip() else '\n') + NAME + '\n')
        return str(ex)
    except Exception:
        return None


def _events(store, item, kind):
    return [json.loads(d) if isinstance(d, str) else (d or {}) for (d,) in
            store.db.execute("select data from events where item=? and kind=? order by at", (item, kind)).fetchall()]


def _object_of(store, cid):
    for (dst,) in store.db.execute("select dst from edges where src=? and rel='about' and dst like 'OBJ:%'", (cid,)).fetchall():
        o = store.get(dst)
        if o: return o['data']
    return None


def _work_of(store, c):
    """The work the rule was stated in (the message's segment), for showing the proposal under it."""
    row = store.db.execute("select e.dst from items s join edges e on e.src=s.id and e.rel='about' where s.type='segment' and s.turn=? "
                           "and e.dst not like 'OBJ:%' and e.dst != 'ROOT' limit 1", (c['turn'],)).fetchone() if c.get('turn') is not None else None
    return row[0] if row else 'ROOT'


def sync(store, *, at, turn=None, write=True, need=None):
    """Bring ctm.md files and annotation proposals in line with the object rules in memory as known at `at`.
    need: {'working_dir', 'task', 'reused'} when an executor is about to start there (entries for it become due).
    Returns {'written': [(rule, file)], 'removed': [(rule, file)], 'proposals': [{'pending', 'task', 'text'}],
    'withdrawn': [{'pending', 'text'}]} (proposals taken back because their rule no longer holds)."""
    from . import lifecycle as L
    out = {'written': [], 'removed': [], 'proposals': [], 'withdrawn': []}
    if not write: return out
    since = store.db.execute("select min(at) from events where item='ROOT' and kind='object_files_since'").fetchone()[0]
    if since is None:                       # rules recorded before CTM kept these files (an import's) are not written in bulk
        store.event('ROOT', 'object_files_since', at=at, source='ctm'); since = at
    rows = store.db.execute("select id from items where type='constraint' and at >= ? and at <= ? and data like ?",
                            (since, at, '%"kind": "object"%')).fetchall()
    for (cid,) in rows:
        c = store.get(cid)
        if not c or c['data'].get('kind') != 'object': continue
        obj = _object_of(store, cid)
        if not obj: continue
        written = _events(store, cid, 'ctm_md_written')
        removed = _events(store, cid, 'ctm_md_removed')
        gone = c['replaced_at'] is not None and c['replaced_at'] <= at
        if not gone and not written:
            origin = _work_of(store, c)
            due = (origin == 'ROOT' or L.status(store, origin) in L.FINISHED
                   or (need and _same_dir(obj.get('working_dir'), need.get('working_dir'))
                       and not (need.get('task') == origin and need.get('reused'))))
            if not due: continue
            d = target_dir(obj.get('working_dir'), obj.get('name'))
            if d is None: continue
            when = datetime.fromtimestamp(c['at']).strftime('%Y-%m-%d')
            f = upsert(d, cid, obj.get('name') or '', c['data'].get('statement', ''), when)
            store.event(cid, 'ctm_md_written', at=at, source='ctm', data={'file': str(f)})
            out['written'].append((cid, str(f)))
            text = f"Write the object rule \"{c['data'].get('statement', '')}\" into a source comment of <{obj.get('name')}>? (It is recorded in {f}.)"
            pid = store.add('pending', {'kind': 'propose_annotation', 'constraint': cid, 'what': text, 'status': 'open',
                                        'object': obj.get('name'), 'working_dir': obj.get('working_dir')}, at=at, source='ctm', turn=turn)
            store.link(pid, 'about', _work_of(store, c), at=at, source='ctm')
            out['proposals'].append({'pending': pid, 'task': _work_of(store, c), 'text': text})
        elif gone and written and not removed:
            f = written[-1].get('file')
            if f and remove(f, cid): out['removed'].append((cid, f))
            store.event(cid, 'ctm_md_removed', at=at, source='ctm', data={'file': f})
            for p in store.items('pending', at=at):              # an unanswered proposal for a rule that no longer holds
                if p['data'].get('kind') == 'propose_annotation' and p['data'].get('constraint') == cid and p['data'].get('status', 'open') == 'open':
                    store.patch(p['id'], {'status': 'superseded'}, at=at, source='ctm')
                    out['withdrawn'].append({'pending': p['id'], 'text': p['data'].get('what', '')})
            if _events(store, cid, 'annotation_answered'):     # the user may have had it written into the code: propose the update
                byi = store.get(c['replaced_by']) or {}; by = byi.get('data', {})
                text = (f"The object rule \"{c['data'].get('statement', '')}\" no longer holds" + (f" (replaced by \"{by.get('statement')}\")" if by.get('statement') else '')
                        + f". Update this comment in the source of <{obj.get('name')}>?")
                pid = store.add('pending', {'kind': 'propose_annotation', 'constraint': cid, 'update': True, 'what': text, 'status': 'open',
                                            'object': obj.get('name'), 'working_dir': obj.get('working_dir')}, at=at, source='ctm', turn=turn)
                store.link(pid, 'about', _work_of(store, c), at=at, source='ctm')
                out['proposals'].append({'pending': pid, 'task': _work_of(store, c), 'text': text})
    return out
