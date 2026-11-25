"""Candidate works for a user message (concept model 5.1): where to look depends on how the message points to its work.

Step 1 (ref.py) gives the ways the message points (modes), the entities it names and its time references. After delivery
the named entities are kept as mentions of the work (record_mentions). The sources:
- recent: works the recent turns of the conversation went to;
- live: the current work, works whose executor is running or waiting, works of open pending items and recent displays;
- objects: message entity -> objects in memory -> the works that involve them. For now the objects are what the user named
  in earlier messages (in the user's own words) and the files a work modified. Identifiers match when identical, or nearly
  identical to allow for typos (character-level, identifiers only); names match by embedding similarity. The quota counts
  objects; each object brings its whole family of works (bounded) and the delivery call ranks within it;
- time: works active around the time a time reference points to.
Each mode sets how many candidates each source contributes; no source is switched off, so a wrong mode costs extra
candidates, not a missing one. The localization call decides among the candidates.
"""
import math
import posixpath

from . import documents as D

# per mode: (recent works, live works, objects, time works) quotas; objects are counted as objects, each bringing its family of works
QUOTAS = {
    'display': (6, 6, 2, 0), 'continue': (4, 8, 1, 0), 'nearby': (12, 4, 3, 0), 'named': (6, 3, 6, 3),
    'past': (4, 2, 4, 6), 'material': (6, 4, 5, 0), 'reference': (4, 2, 5, 3), 'new': (6, 3, 5, 0),
    'external': (3, 1, 3, 0), 'project_question': (6, 3, 5, 0), 'chat': (2, 2, 0, 0),
}
DEFAULT = (8, 4, 5, 2)
PER_OBJECT, TOTAL_OBJECT_WORKS = 8, 30                  # an object's family of works is shown whole up to these bounds
TIME_FLOOR, TIME_SCALE_H = 0.85, 72.0


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def lev(a, b, cap=3):
    """Edit distance (bounded); used for identifier typos only, never for meaning."""
    if abs(len(a) - len(b)) > cap: return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def ident_key(text):
    """Canonical form of an identifier as written: paths through norm_path, others trimmed and lower-cased."""
    t = (text or '').strip().strip('`"' + chr(39))
    if '/' in t or chr(92) in t or t.startswith('file:') or t.startswith('{'):
        t = D.norm_path(t)
    return t.lower()


def record_mentions(store, node, ref, *, turn, at):
    """After a message is delivered: the objects it named (step 1) are kept as mentions of the work it went to, in the
    user's own words, so that later messages naming the same objects find this work."""
    out = []
    for e in (ref or {}).get('entities') or []:
        said, resolved = (e.get('said') or '').strip(), (e.get('resolved') or '').strip()
        if not (said or resolved): continue
        mid = store.add('mention', {'said': said, 'resolved': resolved or said, 'type': e.get('type'), 'role': e.get('role')},
                        at=at, source='user', turn=turn)
        store.link(mid, 'about', node, at=at, source='ctm'); out.append(mid)
    return out


def _keys(said, typ):
    """Identifier keys for a mention: only identifiers and named objects or artifacts, as written (canonical form)."""
    if typ not in ('identifier', 'object', 'artifact') or not said: return set()
    key = ident_key(said); base = posixpath.basename(key)
    return {k for k in (key, base) if len(k) >= 4}


def object_index(store, at=None):
    """Objects in memory with the works that involve them: what the user named in messages delivered to each work
    (mentions), the files each work modified and the decisions currently in force there. [{'kind','name','keys','works'}]"""
    entries = {}

    def add(kind, name, keys, work):
        e = entries.setdefault((kind, name.lower()), {'kind': kind, 'name': name, 'keys': set(), 'works': set()})
        e['keys'] |= keys; e['works'].add(work)
    q = " and e.at <= ?" if at is not None else ''
    args = (at,) if at is not None else ()
    for (task, fid) in store.db.execute("select e.src, e.dst from edges e where e.rel='involves'" + q, args).fetchall():
        f = store.get(fid)
        path = D.norm_path((f or {}).get('data', {}).get('path') or fid.replace('FILE:', ''))
        add('file', path, {path.lower(), posixpath.basename(path).lower()}, task)
    for (mid, node) in store.db.execute("select i.id, e.dst from items i join edges e on e.src=i.id and e.rel='about' where i.type='mention'" + q, args).fetchall():
        d = (store.get(mid) or {}).get('data', {})
        name = d.get('resolved') or d.get('said') or ''
        if name: add('mention', name, _keys(d.get('said'), d.get('type')), node)
    for r in store.items('decision', at=at, current_only=True):       # what the user settled, for "as we decided" (5.1)
        if r['source'] != 'user' or not r['data'].get('statement'): continue
        for node in store.about(r['id'], at):
            if node != 'ROOT': add('decision', r['data']['statement'][:300], set(), node)
    return [e for e in entries.values() if e['name']]


def _last_active(store, node, at):
    x = store.db.execute("select max(i.at) from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? where i.type in ('segment','progress')"
                         + (" and i.at <= ?" if at is not None else ''), (node, at) if at is not None else (node,)).fetchone()[0]
    return x or (store.get(node) or {}).get('at') or 0


_MATRIX = {}


def _matrix(index, embed):
    """Normalised object-name vectors, cached per index (the index is rebuilt per message; names repeat, so embed caches)."""
    import numpy as np
    names = [o['name'][:500] for o in index]
    key = hash(tuple(names))
    if key not in _MATRIX:
        _MATRIX.clear()
        m = np.array(embed(names), dtype=np.float32)
        m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
        _MATRIX[key] = m
    return _MATRIX[key]


def _top(mat, q, k):
    import numpy as np
    v = np.asarray(q, dtype=np.float32); v /= np.linalg.norm(v) + 1e-9
    sims = mat @ v
    idx = np.argsort(-sims)[:k]
    return [(float(sims[i]), int(i)) for i in idx]


def object_hits(store, ref, *, embed, index=None, at=None, k=8):
    """Objects in memory that the message's entities name. Returns [(entry, score, why)] best first; an entry carries all the
    works that involve the object. Identifiers: identical 2.0, nearly identical (typo) 1.5; names: embedding similarity."""
    index = index if index is not None else object_index(store, at)
    ents = [e for e in (ref or {}).get('entities') or [] if (e.get('said') or e.get('resolved'))]
    if not ents or not index: return []
    best = {}

    def add(i, sc, w):
        if sc > best.get(i, (0, ''))[0]: best[i] = (sc, w)
    for e in ents:                                      # identifiers: identical, or nearly identical (typos)
        if e.get('type') not in ('identifier', 'object', 'artifact'): continue
        key = ident_key(e.get('said') or e.get('resolved')); base = posixpath.basename(key)
        if len(base) < 4: continue
        for i, o in enumerate(index):
            if not o['keys']: continue
            if key in o['keys'] or base in o['keys']:
                add(i, 2.0, 'same identifier')
            elif len(base) >= 5 and any(lev(base, kk) <= max(1, len(base) // 8) for kk in o['keys'] if abs(len(kk) - len(base)) <= 2):
                add(i, 1.5, 'similar identifier')
    mat = _matrix(index, embed)
    for e in ents:                                      # names: embedding similarity to object names
        q = embed([(e.get('resolved') or e.get('said'))[:500]])[0]
        w = 1.0 if e.get('role') != 'context' else 0.85
        for sc, i in _top(mat, q, k):
            add(i, sc * w, 'similar ' + {'mention': 'named object', 'file': 'changed file', 'decision': 'decision'}.get(index[i]['kind'], index[i]['kind']))
    return [(index[i], sc, f"{w}: {index[i]['name'][:60]}") for i, (sc, w) in sorted(best.items(), key=lambda x: -x[1][0])][:k]


def object_matches(store, ref, *, at, embed, index=None, k=8):
    """Works reached through the matched objects, scored by the best object (recency with a floor). Kept for retrieval
    experiments and the wider second call; the delivery call itself gets whole object families (object_families)."""
    score, why = {}, {}
    for o, sc, w in object_hits(store, ref, embed=embed, index=index, at=at, k=k):
        for n in o['works']:
            if sc > score.get(n, 0): score[n], why[n] = sc, w
    if at is not None:                                  # recency with a floor: an old work named by its object stays reachable
        for n in score:
            age_h = max(0.0, (at - _last_active(store, n, at)) / 3600)
            score[n] *= TIME_FLOOR + (1 - TIME_FLOOR) * math.exp(-age_h / TIME_SCALE_H)
    return [(n, score[n], why[n]) for n in sorted(score, key=lambda x: -score[x])]


def object_families(store, ref, *, at, embed, index=None, objects=6, per_object=PER_OBJECT, total=TOTAL_OBJECT_WORKS):
    """The matched objects, each with the works that involved it (most recently active first, bounded). The LLM ranks
    within a family; no score or recency rule picks one work here. Returns [{'object','matched','works'}]."""
    out, seen = [], 0
    for o, sc, w in object_hits(store, ref, embed=embed, index=index, at=at, k=objects):
        works = sorted(o['works'], key=lambda n: -_last_active(store, n, at))[:per_object]
        works = works[:max(0, total - seen)]
        if not works: break
        seen += len(works)
        out.append({'object': o['name'][:120], 'matched': f"{w.split(': ')[0]} ({sc:.2f})", 'works': works})
    return out


def time_matches(store, ref, *, at, nodes, k=6):
    out = []
    for tr in (ref or {}).get('time_refs') or []:
        h = tr.get('hours_ago')
        if not isinstance(h, (int, float)): continue
        center = at - h * 3600
        out += sorted(nodes, key=lambda n: abs(_last_active(store, n, at) - center))[:k]
    return list(dict.fromkeys(out))


def candidates(store, *, at, ref, recent=(), live=(), embed=None, index=None, groups=None):
    """Union of the sources with quotas by mode. recent: work ids of recent turns (newest last); live: current work,
    running or waiting executors' works, works of open pending items and recent displays. Returns [(node, [sources])];
    groups (a list, if given) receives the object families for the delivery call."""
    modes = (ref or {}).get('modes') or []
    quotas = [QUOTAS.get(m, DEFAULT) for m in modes] or [DEFAULT]
    q = tuple(max(x[i] for x in quotas) for i in range(4))
    picked = {}

    def take(nodes, n, tag):
        for x in [y for y in nodes if y][:n]:
            picked.setdefault(x, []).append(tag)
    take(list(dict.fromkeys(reversed(list(recent)))), q[0], 'recent')
    take(list(dict.fromkeys(live)), q[1], 'live')
    if embed is not None and q[2]:
        fams = object_families(store, ref, at=at, embed=embed, index=index, objects=q[2])
        for f in fams:
            for n in f['works']:
                picked.setdefault(n, []).append(f"objects ({f['matched']}: {f['object'][:40]})")
        if groups is not None: groups.extend(fams)
    if q[3]:
        nodes = [r['id'] for t in ('task', 'goal') for r in store.items(t, at=at)]
        take(time_matches(store, ref, at=at, nodes=nodes), q[3], 'time')
    return list(picked.items())
