"""Build CTM's memory from recent conversation history, so the pilot starts with the user's works already in the tree.

The live flow writes memory as each message arrives (concept 5.1); importing months of history that way would take days,
so the import works in bulk and produces the same structures: work nodes with their messages, the executor reply ends,
the user's lasting requirements and decisions, progress, mentioned objects and modified files, and statuses.

  collect  - user messages of the user's own sessions since --since (an optional session archive in ClaudeViewer's format,
             read-only, for Claude Code / Codex / Copilot CLI / VS Code Chat: CONTEXT_TREE_HISTORY_DB and _LIB; pi session
             files directly); automated sessions (CONTEXT_TREE_AUTOMATED_PREFIXES, connection probes, tools run from
             AppData) and sessions under CONTEXT_TREE_EXCLUDE_DIRS are left out
  segment  - per session, chunks of messages -> the works in them (argon), sessions in parallel, chunks in order
  merge    - per project: the same work continued in another session is merged; parents for works made of parts
  write    - the store, the pilot state (current work, message -> work)

python -m context_tree.pilot.bootstrap --root <CTM directory> [--since 2026-08-11] [--threads 8] [--step all|collect|segment|merge|write]
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from context_tree.ctm2.model import ask
from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree
from context_tree.ctm2 import lifecycle as L, candidates as K, documents as D, root as R

CV_DB = os.environ.get('CONTEXT_TREE_HISTORY_DB', '')     # an archive of earlier sessions (ClaudeViewer's local.db); optional
CV_LIB = os.environ.get('CONTEXT_TREE_HISTORY_LIB', '')   # the directory holding its `codec` module
PI_SESSIONS = Path.home() / '.pi' / 'agent' / 'sessions'
MODEL = 'gemini-4-argon'
CHUNK = 80
WRITE_TOOLS = set(D.WRITE_TOOLS) | {'MultiEdit', 'NotebookEdit', 'copilot_insertEdit', 'copilot_editFile', 'apply_patch'}
PROBE = re.compile(r'^(reply (with )?exact|use the bash tool|prompt_|hi$|what model'
                   + ''.join('|' + p for p in os.environ.get('CONTEXT_TREE_PROBE_PATTERNS', '').split(';') if p) + ')', re.I)


def clip(s, n):
    s = s or ''
    return s if len(s) <= n else s[:int(n * .75)] + ' ... ' + s[-int(n * .25):]


def norm_cwd(p):
    p = (p or '').strip()
    m = re.match(r'vscode-remote://wsl%2[Bb]ubuntu/mnt/([a-z])/(.*)', p)
    if m: p = f'{m.group(1).upper()}:/{m.group(2)}'
    p = p.replace('\\', '/')
    if re.match(r'^[a-z]:/', p): p = p[0].upper() + p[1:]
    return p.rstrip('/')


# ---- collect ----------------------------------------------------------------------------------------------------------
def _text(content):
    if isinstance(content, str): return content
    return ''.join(x.get('text', '') for x in content or [] if isinstance(x, dict) and x.get('type') == 'text')


def _path_of(args):
    if not isinstance(args, dict): return None
    return args.get('file_path') or args.get('path') or args.get('filePath')


def _sessions_from_viewer(since_ms):
    if not CV_DB or not os.path.exists(CV_DB): return []        # no archive configured: pi sessions only
    sys.path.insert(0, CV_LIB)
    from codec import unpack_json
    db = sqlite3.connect(f'file:{CV_DB}?mode=ro', uri=True)
    out = []
    rows = db.execute("select id, source, project, name from sessions where last_modified >= ? and available=1 and source != 'pi'", (since_ms,)).fetchall()
    for sid, src, proj, name in rows:
        msgs, cur = [], None
        for (blob,) in db.execute("select normalized_json from messages where session_id=? order by order_id", (sid,)):
            m = unpack_json(blob)
            c = (m.get('message') or {}).get('content')
            if m.get('type') == 'user' and m.get('role') == 'user':
                txt = _text(c).strip()
                if not txt: continue
                cur = {'t': (m.get('timestamp') or 0) / 1000.0, 'user': txt, 'agent_end': '', 'files': []}
                msgs.append(cur)
            elif cur and m.get('role') == 'assistant':
                for x in c if isinstance(c, list) else []:
                    if not isinstance(x, dict): continue
                    if x.get('type') == 'text' and x.get('text', '').strip(): cur['agent_end'] = x['text']
                    if x.get('type') == 'tool_use' and x.get('name') in WRITE_TOOLS and _path_of(x.get('input')):
                        cur['files'].append(_path_of(x.get('input')))
        out.append({'sid': sid, 'source': src, 'cwd': norm_cwd(proj), 'name': name, 'msgs': msgs})
    return out


def _sessions_from_pi(since):
    out = []
    for f in PI_SESSIONS.rglob('*.jsonl'):
        if f.stat().st_mtime < since: continue
        msgs, cur, cwd, sid = [], None, '', f.stem
        for line in f.open(encoding='utf-8', errors='replace'):
            try: e = json.loads(line)
            except ValueError: continue
            if e.get('type') == 'session':
                cwd, sid = e.get('cwd') or '', 'pi:' + (e.get('id') or f.stem)
            if e.get('type') != 'message': continue
            m = e.get('message') or {}
            ts = e.get('timestamp')
            t = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp() if ts else 0
            if m.get('role') == 'user':
                txt = _text(m.get('content')).strip()
                if not txt: continue
                cur = {'t': t, 'user': txt, 'agent_end': '', 'files': []}
                msgs.append(cur)
            elif cur and m.get('role') == 'assistant':
                for x in m.get('content') or []:
                    if not isinstance(x, dict): continue
                    if x.get('type') == 'text' and x.get('text', '').strip(): cur['agent_end'] = x['text']
                    if x.get('type') == 'toolCall' and x.get('name') in WRITE_TOOLS and _path_of(x.get('arguments')):
                        cur['files'].append(_path_of(x.get('arguments')))
        out.append({'sid': sid, 'source': 'pi', 'cwd': norm_cwd(cwd), 'name': '', 'msgs': msgs})
    return out


# directories whose sessions are left out of the tree, ';'-separated (the user's choice; e.g. private or unrelated work)
EXCLUDE_DIRS = tuple(d.strip().replace(chr(92), '/').lower().rstrip('/') for d in os.environ.get('CONTEXT_TREE_EXCLUDE_DIRS', '').split(';') if d.strip())
# first-message prefixes of sessions started by the user's own automations (bots that inject a context block), ';'-separated
AUTOMATED_PREFIXES = tuple(p for p in os.environ.get('CONTEXT_TREE_AUTOMATED_PREFIXES', '').split(';') if p)


def _automated(s):
    users = [m['user'] for m in s['msgs']]
    if not users: return 'empty'
    cwd = (s['cwd'] or '').lower().rstrip('/') + '/'
    if any(cwd.startswith(d.rstrip('/') + '/') for d in EXCLUDE_DIRS): return 'excluded directory'
    if AUTOMATED_PREFIXES and users[0].lstrip().startswith(AUTOMATED_PREFIXES): return 'automated session'
    if 'AppData' in s['cwd']: return 'tool run from AppData'
    if len(users) <= 2 and all(PROBE.match(u.strip()) for u in users): return 'connection probe'
    return None


def collect(root, since):
    since_ts = datetime.datetime.fromisoformat(since).timestamp()
    sessions = _sessions_from_viewer(since_ts * 1000) + _sessions_from_pi(since_ts)
    kept, dropped = [], defaultdict(int)
    for s in sessions:
        s['msgs'] = [m for m in s['msgs'] if m['t'] >= since_ts]
        why = _automated(s)
        if why: dropped[why] += 1; continue
        kept.append(s)
    kept.sort(key=lambda s: s['msgs'][0]['t'])
    (root / 'bootstrap').mkdir(parents=True, exist_ok=True)
    (root / 'bootstrap' / 'sessions.json').write_text(json.dumps(kept, ensure_ascii=False), encoding='utf-8')
    n = sum(len(s['msgs']) for s in kept)
    print(f'collect: {len(kept)} sessions, {n} user messages; left out {dict(dropped)}', flush=True)
    return kept


# ---- segment ----------------------------------------------------------------------------------------------------------
SEG = '''You are importing memory for an assistant (CTM) from the user's past conversations. CTM organizes memory by works: a work has a definite output or a resource state it changes; an executor who later takes over the work gets the user's words, requirements, guidance, decisions and results in it.
You get a span of user messages from one session in time order (k is the number; with the end of the executor's reply and the files the executor changed in that turn), and the works already imported from earlier in this session (prior_works).

First understand what the user is doing in this span and write it in analysis (a few sentences): why each message is said at that moment and what it asks for - continuing, correcting, checking or following up a work, or a new output;
which work a wrap-up after finishing (cleaning up, stopping a service, switching branches, pushing) completes; how a further output asked for next relates to the earlier work - a part of it (that work is finished only when this one is), the next step after it, or another thing it led to;
what each message that only shares an object, topic or project moves forward. For questions where the user only wants to know something, see which work they ask about (questions about no work belong nowhere).
Then mark the works in this span. For each work:
- id: the id from prior_works when it continues one of them, otherwise N1, N2, ... (unique in this span); parent: the id of the work (in this span or prior) it is a part of, otherwise null
- title: short (about six words), named by its output or the state it changes; purpose: one sentence
- messages: the k of the messages belonging to it
- status: done (a result was obtained and the user accepted it or did not raise it again) / open (still in progress or unfinished) / abandoned (the user explicitly dropped it)
- result: the final result or state, one or two sentences, only what the replies say
- constraints: requirements the user stated that later work on it must still follow (going against one later would be a mistake to the user), faithful to the words; limits for a single message and the thing to be done this time do not count
- guidance: how the user wants later work on it considered, what to watch for, how to arrange it, without being a hard limit (given to executors as "consider this"; when the user requires something be done this way, forbids another way, or asks to confirm before acting, it is constraints - recorded as guidance, the executor may not follow it; advice recorded as a constraint restricts the executor needlessly): {"statement":"..","k":3}
- decisions: what the user settled, rejected or questioned: {"statement":"..","type":"decision|rejected|questioned","k":12}
- behavior: how the user wants agents to generally do a kind of operation, not limited to this work (in an unrelated work doing the same kind of operation the user would ask the same): {"statement":"..","use_when":"when doing what","k":3}
- objects: names the user mentioned that may later be used to refer to this work (files, branches, services, tickets, projects, product names, as they are)
These records will be given to executors who take over: a wrong attribution brings another work's requirements to it; anything added that the user did not say becomes a requirement the user never made.
Write titles, purposes, results and statements in the language the user writes in.
Output JSON only: {"analysis":"..","works":[{"id":"N1","parent":null,"title":"..","purpose":"..","messages":[3,4],"status":"done","result":"..",
"constraints":[{"statement":"..","k":3}],"guidance":[],"decisions":[],"behavior":[],"objects":[".."]}]}'''


def _seg_session(root, s):
    d = root / 'bootstrap' / 'seg'; d.mkdir(parents=True, exist_ok=True)
    prior = {}
    msgs = s['msgs']
    for ci, a in enumerate(range(0, len(msgs), CHUNK)):
        f = d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', s['sid'])}-{ci:03d}.json"
        if f.exists():
            out = json.loads(f.read_text(encoding='utf-8'))
        else:
            payload = {'session_dir': s['cwd'], 'prior_works': list(prior.values())[-40:],
                       'messages': [{'k': a + i, 'time': datetime.datetime.fromtimestamp(m['t']).strftime('%m-%d %H:%M'),
                                     'user': clip(m['user'], 1200), 'agent_end': (m['agent_end'] or '')[-500:], 'files': m['files'][:8]}
                                    for i, m in enumerate(msgs[a:a + CHUNK])]}
            try:
                out, _ = ask(SEG, payload, model=MODEL, effort='medium', max_out=30000, role='bootstrap-seg')
            except Exception as e:
                out = {'works': [], 'error': str(e)[:300]}
                print('segment failed', s['sid'], ci, str(e)[:120], flush=True)
            f.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
        ws = [w for w in out.get('works') or [] if isinstance(w, dict) and w.get('id')]
        local = {}
        for w in ws:                                  # a prior id continues that work; a new id gets a session-wide key
            local[w['id']] = w['_key'] = w['id'] if w['id'] in prior else f"W{ci}_{w['id']}"
        for w in ws:
            p = w.get('parent')
            w['_parent'] = local.get(p) or (p if p in prior else None) if p else None
            k = w['_key']
            if k in prior:
                prior[k]['status'] = w.get('status') or prior[k]['status']
                if w.get('result'): prior[k]['result'] = w['result']
            else:
                prior[k] = {'id': k, 'title': w.get('title'), 'purpose': w.get('purpose'), 'status': w.get('status'), 'result': w.get('result')}
        out['works'] = ws
        f.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return len(msgs)


def segment(root, threads):
    sessions = json.loads((root / 'bootstrap' / 'sessions.json').read_text(encoding='utf-8'))
    t0 = time.time()
    with ThreadPoolExecutor(threads) as ex:
        for n in ex.map(lambda s: _seg_session(root, s), sorted(sessions, key=lambda s: -len(s['msgs']))): pass
    print(f'segment: {len(sessions)} sessions in {round(time.time() - t0)} s', flush=True)


def _works(root, sessions):
    """All segmented works with their messages (session-local k) and the session; keyed '<session>#<work key>'."""
    d = root / 'bootstrap' / 'seg'
    works = {}
    for s in sessions:
        stem = re.sub(r'[^A-Za-z0-9_.-]', '_', s['sid'])
        for ci in range((len(s['msgs']) + CHUNK - 1) // CHUNK):
            f = d / f'{stem}-{ci:03d}.json'
            if not f.exists(): continue
            for w in json.loads(f.read_text(encoding='utf-8')).get('works') or []:
                if not w.get('_key'): continue
                gid = f"{s['sid']}#{w['_key']}"
                ks = [k for k in w.get('messages') or [] if isinstance(k, int) and 0 <= k < len(s['msgs'])]
                if gid not in works:
                    works[gid] = {'gid': gid, 'sid': s['sid'], 'cwd': s['cwd'], 'title': w.get('title') or '', 'purpose': w.get('purpose') or '',
                                  'parent': None, 'ks': [], 'status': w.get('status'), 'result': w.get('result'),
                                  'constraints': [], 'guidance': [], 'decisions': [], 'behavior': [], 'objects': []}
                g = works[gid]
                g['ks'] += ks
                g['status'] = w.get('status') or g['status']
                if w.get('result'): g['result'] = w['result']
                g['constraints'] += [c for c in w.get('constraints') or [] if isinstance(c, dict) and c.get('statement')]
                g['decisions'] += [c for c in w.get('decisions') or [] if isinstance(c, dict) and c.get('statement')]
                g['guidance'] += [c for c in w.get('guidance') or [] if isinstance(c, dict) and c.get('statement')]
                g['behavior'] += [c for c in w.get('behavior') or [] if isinstance(c, dict) and c.get('statement')]
                g['objects'] += [o for o in w.get('objects') or [] if isinstance(o, str) and o.strip()]
                if w.get('_parent') and w['_parent'] != w['_key']: g['parent'] = f"{s['sid']}#{w['_parent']}"
    for g in works.values(): g['ks'] = sorted(set(g['ks']))
    return {k: v for k, v in works.items() if v['ks']}


# ---- merge ------------------------------------------------------------------------------------------------------------
MERGE = '''Below are works imported from the user's different sessions in the same working directory, ordered by start time, each with its first few user messages. The user often continues earlier work in a new session.
What merging is for: once one work is a single node, the executor taking over sees all its earlier requirements, decisions and results. Merged wrongly, one work's requirements are brought into another; not merged, the executor lacks the history of the same work.
Analyse first, in analysis (a few sentences): which works pursue the same output or change the same state - a later one continuing, correcting or checking an earlier one; which only share an object, topic or module, each accomplishing its own thing.
(The long-term goals they serve and how they are composed are settled later; here only find the same work.) Output JSON only: {"analysis":"..","same":[["A3","A9"]]}'''


def merge(root, threads):
    sessions = json.loads((root / 'bootstrap' / 'sessions.json').read_text(encoding='utf-8'))
    by_sid = {s['sid']: s for s in sessions}
    works = _works(root, sessions)
    by_proj = defaultdict(list)
    for g in works.values(): by_proj[g['cwd'] or '(none)'].append(g)
    d = root / 'bootstrap' / 'merge'; d.mkdir(parents=True, exist_ok=True)
    jobs = []
    for proj, gs in by_proj.items():
        if len({g['sid'] for g in gs}) < 2 and len(gs) < 4: continue
        gs = sorted(gs, key=lambda g: by_sid[g['sid']]['msgs'][g['ks'][0]]['t'])
        for part in range(0, len(gs), 150):
            jobs.append((proj, part, gs[part:part + 150]))
    def one(job):
        proj, part, gs = job
        f = d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', proj)[-60:]}-{part}.json"
        if f.exists(): return
        alias = {f'A{i}': g['gid'] for i, g in enumerate(gs)}
        payload = {'project': proj, 'works': [{'id': f'A{i}', 'title': g['title'], 'purpose': g['purpose'], 'status': g['status'],
                                               'started': datetime.datetime.fromtimestamp(by_sid[g['sid']]['msgs'][g['ks'][0]]['t']).strftime('%m-%d'),
                                               'session': g['sid'][-8:], 'user_said': [clip(by_sid[g['sid']]['msgs'][k]['user'], 160) for k in g['ks'][:3]]}
                                              for i, g in enumerate(gs)]}
        try:
            out, _ = ask(MERGE, payload, model=MODEL, effort='medium', max_out=20000, role='bootstrap-merge')
        except Exception as e:
            out = {'same': [], 'parents': [], 'error': str(e)[:300]}; print('merge failed', proj, str(e)[:120], flush=True)
        out['alias'] = alias
        f.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    t0 = time.time()
    with ThreadPoolExecutor(threads) as ex: list(ex.map(one, jobs))
    print(f'merge: {len(works)} works in {len(by_proj)} projects, {len(jobs)} calls, {round(time.time() - t0)} s', flush=True)


# ---- write ------------------------------------------------------------------------------------------------------------
def write(root):
    sessions = json.loads((root / 'bootstrap' / 'sessions.json').read_text(encoding='utf-8'))
    by_sid = {s['sid']: s for s in sessions}
    works = _works(root, sessions)
    canon = {g: g for g in works}                     # union-find over "same work"
    def find(x):
        while canon[x] != x: canon[x] = canon[canon[x]]; x = canon[x]
        return x
    parents = []
    for f in sorted((root / 'bootstrap' / 'merge').glob('*.json')) if (root / 'bootstrap' / 'merge').exists() else []:
        out = json.loads(f.read_text(encoding='utf-8')); alias = out.get('alias') or {}
        for grp in out.get('same') or []:
            ids = [alias[a] for a in grp if a in alias and alias[a] in works]
            for x in ids[1:]: canon[find(x)] = find(ids[0])
        for p in out.get('parents') or []:
            ch = [alias[a] for a in p.get('children') or [] if a in alias and alias[a] in works]
            if len(ch) >= 2 and p.get('title'): parents.append({'title': p['title'], 'purpose': p.get('purpose') or '', 'children': ch})
    # global chronological turns
    allmsgs = sorted(((m['t'], s['sid'], k) for s in sessions for k, m in enumerate(s['msgs'])))
    turn_of = {(sid, k): i + 1 for i, (t, sid, k) in enumerate(allmsgs)}
    owner = {}
    for g in works.values():
        for k in g['ks']: owner.setdefault((g['sid'], k), find(g['gid']))
    groups = defaultdict(list)
    for g in works.values(): groups[find(g['gid'])].append(g)
    db = root / 'ctm.sqlite'
    if db.exists(): raise SystemExit(f'{db} exists; remove it to rebuild')
    store = Store(str(db)); R.ensure_root(store); tree = StoreTree(store)
    first_t = {c: min(by_sid[g['sid']]['msgs'][g['ks'][0]]['t'] for g in gs) for c, gs in groups.items()}
    last_t = {c: max(by_sid[g['sid']]['msgs'][g['ks'][-1]]['t'] for g in gs) for c, gs in groups.items()}
    node, run = {}, {}
    now = time.time()
    # parents: from merge (across sessions) first, then from segmentation (inside a session)
    parent_of = {}
    for p in parents:
        kids = list(dict.fromkeys(find(c) for c in p['children']))
        if len(kids) < 2: continue
        t = min(first_t[c] for c in kids)
        first_turn = min(turn_of[(g['sid'], g['ks'][0])] for c in kids for g in groups[c])
        pid = tree.add(p['title'][:40], p['purpose'], None, None, first_turn, t, working_dir=groups[kids[0]][0]['cwd'], source='ctm')
        L.set_status(store, pid, 'running', at=t, source='ctm', reason='history import')
        for c in kids: parent_of.setdefault(c, pid)
    for c, gs in groups.items():
        for g in gs:
            if g['parent'] in canon and find(g['parent']) != c and c not in parent_of: parent_of[c] = ('work', find(g['parent']))
    order = sorted(groups, key=lambda c: first_t[c])
    def make(c):
        if c in node: return node[c]
        gs = sorted(groups[c], key=lambda g: by_sid[g['sid']]['msgs'][g['ks'][0]]['t'])
        par = parent_of.get(c)
        if isinstance(par, tuple): par = make(par[1]) if par[1] in groups and par[1] != c else None
        first = gs[0]
        n = tree.add((first['title'] or 'untitled work')[:40], first['purpose'], par, None, turn_of[(first['sid'], first['ks'][0])], first_t[c],
                     working_dir=first['cwd'], source='ctm')
        node[c] = n
        rid = store.add('run', {'mode': 'session', 'status': 'ended', 'state': 'idle', 'imported': True,
                                'source_sessions': sorted({g['sid'] for g in gs}), 'end_reason': 'history import'}, at=first_t[c], source='ctm', turn=turn_of[(first['sid'], first['ks'][0])])
        store.link(rid, 'serves', n, at=first_t[c], source='ctm'); run[c] = rid
        L.set_status(store, n, 'running', at=first_t[c], source='ctm', reason='history import')
        return n
    for c in order: make(c)
    for c in order:
        first = min(groups[c], key=lambda g: by_sid[g['sid']]['msgs'][g['ks'][0]]['t'])
        for k in range(first['ks'][0] - 1, -1, -1):
            o = owner.get((first['sid'], k))
            if o and o != c and o in node:
                store.patch(node[c], {'raised_during': node[o]}, at=first_t[c], source='ctm'); break
    assigned = {}
    for t, sid, k in allmsgs:
        m = by_sid[sid]['msgs'][k]; turn = turn_of[(sid, k)]
        tid = store.add('turn', {'role': 'user', 'text': m['user'][:6000], 'session': sid}, at=t, source='user', turn=turn)
        if m['agent_end']: store.add('exchange', {'reply': m['agent_end'][-3000:]}, at=t + 1, source='executor', turn=turn)
        c = owner.get((sid, k))
        if not c: continue
        n = node[c]; assigned[turn] = n
        sg = store.add('segment', {'text': m['user'][:2000], 'to': 'existing', 'imported': True}, at=t, source='user', turn=turn)
        store.link(sg, 'part_of', tid, at=t, source='ctm'); store.link(sg, 'about', n, at=t, source='ctm')
        tree.touch(n, turn, t, m['user'][:150])
        if m['files']:
            D.record_file_versions(store, run=run[c], task=n, tools=[{'name': 'write', 'path': p, 'success': True} for p in m['files']],
                                   at=t + 1, working_dir=by_sid[sid]['cwd'])
    behavior = []
    for c, gs in groups.items():
        n = node[c]
        for g in gs:
            ks = g['ks']; by_k = lambda k: by_sid[g['sid']]['msgs'][min(max(k, 0), len(by_sid[g['sid']]['msgs']) - 1)]
            for x in g['constraints']:
                k = x.get('k') if isinstance(x.get('k'), int) else ks[0]; mt = by_k(k)['t']
                cid = store.add('constraint', {'statement': x['statement'], 'kind': 'task', 'validity': 'work', 'imported': True}, at=mt, source='user',
                                turn=turn_of.get((g['sid'], k)))
                store.link(cid, 'about', n, at=mt, source='ctm')
            for x in g['guidance']:
                k = x.get('k') if isinstance(x.get('k'), int) else ks[0]; mt = by_k(k)['t']
                gid_ = store.add('guidance', {'statement': x['statement'], 'imported': True}, at=mt, source='user', turn=turn_of.get((g['sid'], k)))
                store.link(gid_, 'about', n, at=mt, source='ctm')
            for x in g['behavior']:
                k = x.get('k') if isinstance(x.get('k'), int) else ks[0]
                behavior.append({'statement': x['statement'], 'use_when': x.get('use_when') or '', 't': by_k(k)['t'], 'turn': turn_of.get((g['sid'], k))})
            for x in g['decisions']:
                k = x.get('k') if isinstance(x.get('k'), int) else ks[-1]; mt = by_k(k)['t']
                did = store.add('decision', {'statement': x['statement'], 'type': x.get('type') if x.get('type') in ('decision', 'rejected', 'questioned') else 'decision',
                                             'imported': True}, at=mt, source='user', turn=turn_of.get((g['sid'], k)))
                store.link(did, 'about', n, at=mt, source='ctm')
            if g['objects']:
                K.record_mentions(store, n, {'entities': [{'said': o, 'resolved': o, 'type': 'identifier', 'role': 'target'} for o in dict.fromkeys(g['objects'])]},
                                  turn=turn_of[(g['sid'], ks[0])], at=by_k(ks[0])['t'])
        latest = max(gs, key=lambda g: by_sid[g['sid']]['msgs'][g['ks'][-1]]['t'])
        if latest.get('result'):
            pid = store.add('progress', {'done': latest['result'], 'open': [], 'imported': True}, at=last_t[c] + 2, source='ctm',
                            turn=turn_of[(latest['sid'], latest['ks'][-1])])
            store.link(pid, 'about', n, at=last_t[c] + 2, source='ctm')
        st = latest.get('status')
        new = 'reported_done' if st == 'done' else 'abandoned' if st == 'abandoned' else ('running' if now - last_t[c] < 3 * 86400 else 'paused')
        if new != 'running': L.set_status(store, n, new, at=last_t[c] + 3, source='ctm', reason='history import')
    behavior.sort(key=lambda b: b['t'])            # behavior guidance into documents by kind of operation, oldest first
    for i in range(0, len(behavior), 30):
        part = behavior[i:i + 30]
        try:
            D.file_behavior(store, [{'statement': b['statement'], 'use_when': b['use_when']} for b in part], at=part[-1]['t'], turn=part[-1]['turn'], model=MODEL)
        except Exception as e: print('behavior failed', str(e)[:120], flush=True)
    store.event('ROOT', 'maintenance', at=now, source='maintenance', data={'baseline': True, 'imported': True})
    store.commit()
    cur = assigned[max(assigned)] if assigned else None
    (root / 'ctm-state.json').write_text(json.dumps({'current': cur, 'selection': None, 'assigned': {str(k): v for k, v in assigned.items()}},
                                                   ensure_ascii=False), encoding='utf-8')
    n_msgs = len(allmsgs)
    item = {'kind': 'notice', 'text': f'Imported from the recent conversation history: {len(groups)} works, {len(parents)} parents, {n_msgs} messages ({len(assigned)} assigned to works).',
            't': now, 'i': 0}
    (root / 'conversation.jsonl').write_text(json.dumps(item, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'write: {len(groups)} works, {len(parents)} parents, {n_msgs} messages ({len(assigned)} in works); current {cur}; '
          f'{len(behavior)} behavior statements into {len(D.behavior_docs(store))} documents', flush=True)


def fix_parents(root):
    """A parent made by the import is done when all its works are finished, in progress while one runs, else paused."""
    store = Store(str(root / 'ctm.sqlite')); tree = StoreTree(store)
    kids = defaultdict(list)
    for n in tree.nodes.values():
        if n.parent in tree.nodes: kids[n.parent].append(n.id)
    changed = 0
    for pid in sorted(kids, key=lambda p: -len(tree.ancestors(p)) if hasattr(tree, 'ancestors') else 0):
        sts = [L.status(store, c) for c in kids[pid]]
        new = ('reported_done' if all(x in L.FINISHED for x in sts) else 'running' if any(x == 'running' for x in sts) else 'paused')
        if new != L.status(store, pid) and L.set_status(store, pid, new, at=time.time(), source='ctm', reason='history import: by the status of the works below'):
            changed += 1
    store.commit()
    print(f'parents: {changed} statuses updated', flush=True)


def warm(root):
    """Embed every object name once, so the pilot's first message does not wait for thousands of vectors."""
    from .vectors import VectorCache
    store = Store(str(root / 'ctm.sqlite'))
    index = K.object_index(store)
    names = [o['name'][:500] for o in index]
    t0 = time.time()
    VectorCache(root / 'vectors.sqlite').embed(names)
    print(f'warm: {len(names)} object names embedded in {round(time.time() - t0)} s', flush=True)


def organize(root, passes=2, split_over=15, batch=None):
    """After an import (concept 3.4): every work goes under the goal it serves -- the same goal judgment as in live use, over
    all works in time order, so goals accumulate as they would have; then, under each goal and under parents with many
    children, the parts of one task are put under it (containment). Periodic maintenance only reads records since its last
    run, so it never sees the imported history."""
    from collections import Counter
    from ..ctm2 import maintain_store as MS
    store = Store(str(root / 'ctm.sqlite')); tree = StoreTree(store)
    t0 = time.time()
    ops = MS.assign_goals(store, tree, time.time(), model=MODEL, batch=batch or MS.GOAL_BATCH, why='history import')
    store.commit()
    print(f"goals: {sum(1 for o in ops if o['op'] == 'new_goal')} goals, {sum(1 for o in ops if o['op'] == 'to_goal')} works placed, "
          f"{sum(1 for o in ops if o['op'] == 'merge_goals')} merged, {round(time.time() - t0)} s", flush=True)
    for k in range(passes):
        kids = Counter(n.parent for n in tree.nodes.values() if n.parent in tree.nodes)
        levels = [p for p, c in kids.items() if (tree.nodes[p].kind == 'goal' and c >= 3) or c > split_over]
        made = []
        for parent in levels:
            try:
                made += MS.structure(store, tree, time.time(), model=MODEL, parent=parent, trigger='maintenance', why='tidying after the history import')
            except Exception as e: print('structure failed', parent, str(e)[:120], flush=True)
        store.commit()
        print(f'organize pass {k + 1}: {len(levels)} levels, {len(made)} groups', flush=True)
    print('organize:', round(time.time() - t0), 's;', MS.tree_shape(tree), flush=True)


def main():
    ap = argparse.ArgumentParser(prog='python -m context_tree.pilot.bootstrap')
    ap.add_argument('--root', required=True)
    ap.add_argument('--since', default=(datetime.date.today() - datetime.timedelta(days=92)).isoformat())
    ap.add_argument('--threads', type=int, default=8)
    ap.add_argument('--step', default='all', choices=['all', 'collect', 'segment', 'merge', 'write', 'parents', 'organize', 'warm'])
    a = ap.parse_args()
    root = Path(a.root); root.mkdir(parents=True, exist_ok=True)
    if a.step in ('all', 'collect'): collect(root, a.since)
    if a.step in ('all', 'segment'): segment(root, a.threads)
    if a.step in ('all', 'merge'): merge(root, a.threads)
    if a.step in ('all', 'write'): write(root)
    if a.step in ('all', 'write', 'parents'): fix_parents(root)
    if a.step in ('all', 'organize'): organize(root)
    if a.step in ('all', 'warm'): warm(root)


if __name__ == '__main__':
    main()
