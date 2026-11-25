"""In-memory task tree for replay (concept model v2, section 3): Goal/Task nodes placed by service relation.

Nodes keep only what localization and placement need: title, purpose, parent, predecessor, recent notes
(segment texts and brief executor progress) and activity time. Persistence and documents come later.
"""
from dataclasses import dataclass, field


@dataclass
class Node:
    id: str
    title: str
    purpose: str
    parent: str | None
    after: str | None
    created_turn: int
    last_turn: int
    last_time: float
    notes: list = field(default_factory=list)
    vector: list | None = None
    proposed: bool = False
    merged_into: str | None = None
    kind: str = 'task'            # 'goal' (a purpose the user expressed) or 'task'
    working_dir: str = ''         # where its executors work; inherited from the parent when unknown

    def text(self):
        return f"{self.title}. {self.purpose}. " + '; '.join(self.notes[-3:])


class Tree:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.alias: dict[str, str] = {}
        self.counter = 0

    def add(self, title, purpose, parent, after, turn, time, kind='task', working_dir=''):
        self.counter += 1
        nid = f'N{self.counter}'
        parent = parent if parent in self.nodes else None
        after = after if after in self.nodes else None
        wd = working_dir or (self.nodes[parent].working_dir if parent else '')
        self.nodes[nid] = Node(nid, title, purpose, parent, after, turn, turn, time, kind=kind, working_dir=wd)
        return nid

    def ancestors(self, nid):
        out = []
        while nid in self.nodes and self.nodes[nid].parent in self.nodes and self.nodes[nid].parent not in out:
            nid = self.nodes[nid].parent; out.append(nid)
        return out

    def root(self, nid):
        a = self.ancestors(nid)
        return a[-1] if a else nid

    def line_view(self, nid, now, max_nodes=40):
        """The current task's line: its ancestors, the siblings at each level and its children (hot subtree)."""
        if nid not in self.nodes: return []
        keep = [nid] + self.ancestors(nid)
        for a in list(keep):
            par = self.nodes[a].parent
            keep += [n.id for n in self.nodes.values() if n.parent == par and n.id not in keep]
        keep += [n.id for n in self.nodes.values() if n.parent == nid and n.id not in keep]
        return [self.detail(n, now) for n in keep[:max_nodes]]

    def touch(self, nid, turn, time, note=None, keep=4):
        n = self.nodes[nid]
        n.last_turn, n.last_time = turn, time
        if note:
            n.notes = (n.notes + [note])[-keep:]
        n.vector = None

    def merge(self, keep, drop):
        """Fold a duplicate node into another; its children and notes move, the dropped id resolves to the kept one."""
        k, d = self.nodes[keep], self.nodes.pop(drop)
        k.notes = sorted(k.notes + d.notes, key=lambda s: 0)[-6:]
        k.last_turn, k.last_time = max(k.last_turn, d.last_turn), max(k.last_time, d.last_time)
        k.vector = None
        for n in self.nodes.values():
            if n.parent == drop: n.parent = keep
            if n.after == drop: n.after = keep
        self.alias[drop] = keep

    def resolve(self, nid):
        if isinstance(nid, (list, tuple)): nid = nid[0] if nid else None      # model output occasionally gives a list
        if not isinstance(nid, str): return None
        while nid in self.alias: nid = self.alias[nid]
        return nid

    def path(self, nid):
        out = []
        while nid:
            out.append(self.nodes[nid].title); nid = self.nodes[nid].parent
        return ' / '.join(reversed(out))

    def outline(self, now):
        """Compact listing of every node, most recently active first."""
        return [{'id': n.id, 'title': n.title, 'kind': n.kind, 'parent': n.parent, 'hours_since_active': round((now - n.last_time) / 3600, 1)}
                for n in sorted(self.nodes.values(), key=lambda n: -n.last_time)]

    def outline_around(self, cands, now, max_tops=40):
        """Bounded outline for large trees: the most recently active top-level nodes, plus every candidate's ancestor chain
        and siblings. Keeps the localization prompt from growing with the whole tree."""
        keep = set()
        tops = sorted((n for n in self.nodes.values() if n.parent not in self.nodes), key=lambda n: -n.last_time)[:max_tops]
        keep.update(n.id for n in tops)
        for c in cands:
            if c not in self.nodes: continue
            p = c
            while p in self.nodes and p not in keep - {c}:
                keep.add(p); p = self.nodes[p].parent
            par = self.nodes[c].parent
            keep.update(n.id for n in self.nodes.values() if n.parent == par)
        return [o for o in self.outline(now) if o['id'] in keep]

    def detail(self, nid, now):
        n = self.nodes[nid]
        return {'id': n.id, 'kind': n.kind, 'path': self.path(nid), 'purpose': n.purpose, 'working_dir': n.working_dir, 'after': n.after,
                'children': [c.id for c in self.nodes.values() if c.parent == nid],
                'hours_since_active': round((now - n.last_time) / 3600, 1), 'recent_notes': n.notes[-3:]}

    # structural edits go through methods so that a store-backed tree can persist them with time and source
    def set_parent(self, nid, parent, *, at=None, source='ctm', reason=''):
        if nid in self.nodes and (parent is None or parent in self.nodes):
            self.nodes[nid].parent = parent

    def rename(self, nid, title, *, at=None, source='ctm', reason=''):
        if nid in self.nodes:
            self.nodes[nid].title = title; self.nodes[nid].vector = None




class StoreTree(Tree):
    """Tree view over the persistent store (implementation plan S0): every structural change is written to the store with
    its time and source; notes are rebuilt from the stored segments and progress when loading."""

    def __init__(self, store):
        super().__init__()
        self.store = store
        for r in store.work_nodes():
            d = r['data']
            self.nodes[r['id']] = Node(r['id'], d.get('title', ''), d.get('purpose', ''), store.parent(r['id']), d.get('after'),
                                       r['turn'] or 0, d.get('last_turn', r['turn'] or 0), d.get('last_time', r['at']),
                                       kind=r['type'], working_dir=d.get('working_dir', ''), proposed=d.get('proposed', False))
        for nid in self.nodes:
            segs = store.items('segment', about=nid)[-4:]
            self.nodes[nid].notes = [s['data'].get('text', '')[:150] for s in segs]

    def add(self, title, purpose, parent, after, turn, time, kind='task', working_dir='', source='ctm', proposed=False):
        parent = parent if parent in self.nodes else None
        after = after if after in self.nodes else None
        wd = working_dir or (self.nodes[parent].working_dir if parent else '')
        nid = self.store.add(kind, {'title': title, 'purpose': purpose, 'working_dir': wd, 'after': after, 'status': 'proposed' if proposed else 'pending',
                                    'proposed': proposed, 'last_turn': turn, 'last_time': time}, at=time, source=source, turn=turn)
        if parent: self.store.link(parent, 'child', nid, at=time, source=source)
        self.nodes[nid] = Node(nid, title, purpose, parent, after, turn, turn, time, kind=kind, working_dir=wd, proposed=proposed)
        if after:
            from . import lifecycle
            lifecycle.add_dep(self.store, after, nid, at=time, source=source)
        return nid

    def touch(self, nid, turn, time, note=None, keep=4):
        super().touch(nid, turn, time, note, keep)

    def set_parent(self, nid, parent, *, at=None, source='ctm', reason=''):
        if nid in self.nodes and (parent is None or parent in self.nodes):
            self.store.set_parent(nid, parent, at=at if at is not None else self.nodes[nid].last_time, source=source, reason=reason)
            self.nodes[nid].parent = parent

    def rename(self, nid, title, *, at=None, source='ctm', reason=''):
        if nid in self.nodes:
            self.store.patch(nid, {'title': title}, at=at if at is not None else self.nodes[nid].last_time, source=source, reason=reason)
            super().rename(nid, title)

    def merge(self, keep, drop, *, at=None, source='maintenance', reason=''):
        when = at if at is not None else max(self.nodes[keep].last_time, self.nodes[drop].last_time)
        self.store.merge(keep, drop, at=when, source=source, reason=reason)
        super().merge(keep, drop)

    def resolve(self, nid):
        nid = super().resolve(nid)
        return self.store.resolve(nid) if nid and nid not in self.nodes else nid

    def detail(self, nid, now):
        """Node detail plus the constraints in force on it (for checking a placement by its constraint consequences)."""
        d = super().detail(nid, now)
        d['constraints'] = [r['data'].get('statement', '')[:120] for r in self.store.items('constraint', about=nid, current_only=True)][-4:]
        d['status'] = (self.store.get(nid) or {}).get('data', {}).get('status')
        run = self.store.db.execute("select i.data from items i join edges e on e.src=i.id and e.rel='serves' and e.dst=? where i.type='run' "
                                    "order by i.at desc limit 1", (nid,)).fetchone()
        import json
        d['executor'] = json.loads(run[0]).get('state') if run else None
        par = self.nodes[nid].parent
        me = self.nodes[nid].last_time
        d['later_siblings'] = [n.title for n in self.nodes.values() if n.parent == par and n.id != nid and n.last_time > me
                               and par is not None][:4]
        # the state of the work: its latest results and open problems (its own executions), and the user's queries about it
        d['latest_results'] = [{'turn': p['turn'], 'done': (p['data'].get('done') or p['data'].get('note') or '')[:200],
                                'open': [str(o)[:100] for o in (p['data'].get('open') or [])[:3]],
                                'failed': [str(o)[:120] for o in (p['data'].get('failed') or [])[:2]],
                                'verified': str(p['data'].get('verified') or '')[:120]}
                               for p in self.store.items('progress', about=nid)[-2:]]
        d['recent_queries'] = [{'turn': q['turn'], 'question': (q['data'].get('question') or '')[:120], 'answer': (q['data'].get('answer') or '')[:160]}
                               for q in self.store.items('query', about=nid) if q['data'].get('answered')][-2:]
        return d
