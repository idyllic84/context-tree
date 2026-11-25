"""CTM memory store (concept model v2, sections 3.1 and 4).

One SQLite database holds every memory item and relation with its times and its source:
  items  - work nodes (goal, task), conversation records (turn, segment, display), query, run, document and its versions,
           object, file_version, resource, constraint, decision, environment, progress, pending, root entries;
  edges  - child, dep, about, serves, produced, involves, contains, uses, supersedes, detailedIn, prev, replaces;
  events - status changes and structural edits (move, merge, rename, ...) with time, source and reason.
Times: `at` is when CTM wrote/learned the item; `occurred_at` when it happened; `valid_from` / `replaced_at` / `replaced_by`
bound the period in which an authoritative item (constraint, decision, environment, state) is current; `observed_at` marks
volatile observations. Every query can be asked "as known at" a time, which makes causal replay exact.
Sources: user, ctm, executor, planner, maintenance, ui.
"""
import json
import sqlite3
import time as _time

SOURCES = {'user', 'ctm', 'executor', 'planner', 'maintenance', 'ui'}

SCHEMA = '''
create table if not exists items(
  id text primary key, type text not null, data text not null, at real not null, source text not null, turn integer,
  occurred_at real, valid_from real, replaced_at real, replaced_by text, observed_at real);
create index if not exists items_type on items(type);
create index if not exists items_turn on items(turn);
create table if not exists edges(
  src text not null, rel text not null, dst text not null, at real not null, source text not null,
  valid_to real, data text);
create index if not exists edges_src on edges(src, rel);
create index if not exists edges_dst on edges(dst, rel);
create table if not exists events(
  item text not null, kind text not null, at real not null, source text not null, data text);
create index if not exists events_item on events(item);
create table if not exists counters(name text primary key, value integer not null);
'''


class Store:
    def __init__(self, path=':memory:'):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)   # reads may come from worker threads; writes stay single-threaded
        self.db.executescript(SCHEMA)

    # ---- writing -------------------------------------------------------------------------------------------------
    def new_id(self, prefix):
        cur = self.db.execute('select value from counters where name=?', (prefix,)).fetchone()
        n = (cur[0] if cur else 0) + 1
        self.db.execute('insert or replace into counters(name, value) values(?, ?)', (prefix, n))
        return f'{prefix}{n}'

    def add(self, type_, data, *, at, source, turn=None, id=None, occurred_at=None, valid_from=None, observed_at=None):
        assert source in SOURCES, source
        iid = id or self.new_id({'goal': 'N', 'task': 'N'}.get(type_, type_[:2].upper()))
        self.db.execute('insert into items values(?,?,?,?,?,?,?,?,?,?,?)',
                        (iid, type_, json.dumps(data, ensure_ascii=False), at, source, turn, occurred_at,
                         valid_from if valid_from is not None else at, None, None, observed_at))
        return iid

    def patch(self, iid, changes, *, at, source, reason=''):
        """Change fields of an item; the old values are kept in an event."""
        old = self.get(iid)
        data = dict(old['data']); before = {k: data.get(k) for k in changes}
        data.update(changes)
        self.db.execute('update items set data=? where id=?', (json.dumps(data, ensure_ascii=False), iid))
        self.event(iid, 'patch', at=at, source=source, data={'before': before, 'after': changes, 'reason': reason})

    def replace(self, old_id, new_id, *, at, source):
        """old_id stops being current at `at`; it is kept as history with what replaced it."""
        self.db.execute('update items set replaced_at=?, replaced_by=? where id=? and replaced_at is null', (at, new_id, old_id))
        self.link(new_id, 'replaces', old_id, at=at, source=source)

    def link(self, src, rel, dst, *, at, source, data=None):
        self.db.execute('insert into edges values(?,?,?,?,?,?,?)', (src, rel, dst, at, source, None,
                                                                     json.dumps(data, ensure_ascii=False) if data else None))

    def unlink(self, src, rel, dst, *, at):
        self.db.execute('update edges set valid_to=? where src=? and rel=? and dst=? and valid_to is null', (at, src, rel, dst))

    def event(self, iid, kind, *, at, source, data=None):
        self.db.execute('insert into events values(?,?,?,?,?)', (iid, kind, at, source, json.dumps(data or {}, ensure_ascii=False)))

    # ---- tree operations (work nodes) -----------------------------------------------------------------------------
    def set_parent(self, node, parent, *, at, source, reason=''):
        old = self.parent(node)
        if old == parent: return
        if old: self.unlink(old, 'child', node, at=at)
        if parent: self.link(parent, 'child', node, at=at, source=source)
        self.event(node, 'move', at=at, source=source, data={'from': old, 'to': parent, 'reason': reason})

    def merge(self, keep, drop, *, at, source, reason=''):
        """Fold a duplicate work node into another: children, segments and items move; the dropped id resolves to `keep`."""
        for rel in ('child', 'about'):
            for (dst,) in self.db.execute('select dst from edges where src=? and rel=? and valid_to is null', (drop, rel)).fetchall():
                self.unlink(drop, rel, dst, at=at); self.link(keep, rel, dst, at=at, source=source)
        for (src, rel) in self.db.execute("select src, rel from edges where dst=? and valid_to is null and rel in ('about','serves','on')", (drop,)).fetchall():
            self.unlink(src, rel, drop, at=at); self.link(src, rel, keep, at=at, source=source)
        p = self.parent(drop)
        if p: self.unlink(p, 'child', drop, at=at)
        self.link(drop, 'merged_into', keep, at=at, source=source)
        self.patch(drop, {'status': 'merged'}, at=at, source=source, reason=reason)
        self.event(keep, 'merge', at=at, source=source, data={'absorbed': drop, 'reason': reason})

    # ---- reading ------------------------------------------------------------------------------------------------
    def _row(self, r):
        return None if r is None else {'id': r[0], 'type': r[1], 'data': json.loads(r[2]), 'at': r[3], 'source': r[4], 'turn': r[5],
                                       'occurred_at': r[6], 'valid_from': r[7], 'replaced_at': r[8], 'replaced_by': r[9], 'observed_at': r[10]}

    def get(self, iid):
        return self._row(self.db.execute('select * from items where id=?', (iid,)).fetchone())

    def resolve(self, iid):
        seen = set()
        while iid and iid not in seen:
            seen.add(iid)
            r = self.db.execute("select dst from edges where src=? and rel='merged_into' and valid_to is null", (iid,)).fetchone()
            if not r: return iid
            iid = r[0]
        return iid

    def _edge_live(self, at):
        return '(valid_to is null or valid_to > ?) and at <= ?' if at is not None else 'valid_to is null and 1=1'

    def _args(self, at, *head):
        return (*head, at, at) if at is not None else head

    def parent(self, node, at=None):
        r = self.db.execute(f"select src from edges where dst=? and rel='child' and {self._edge_live(at)} order by at desc",
                            self._args(at, node)).fetchone()
        return r[0] if r else None

    def children(self, node, at=None):
        return [r[0] for r in self.db.execute(f"select dst from edges where src=? and rel='child' and {self._edge_live(at)}",
                                               self._args(at, node)).fetchall()]

    def ancestors(self, node, at=None):
        out = []
        p = self.parent(node, at)
        while p and p not in out:
            out.append(p); p = self.parent(p, at)
        return out

    def work_nodes(self, at=None):
        q = "select * from items where type in ('goal','task')" + (' and at <= ?' if at is not None else '')
        rows = [self._row(r) for r in self.db.execute(q, (at,) if at is not None else ()).fetchall()]
        return [r for r in rows if r['data'].get('status') != 'merged' or (at is not None and self._merged_after(r['id'], at))]

    def _merged_after(self, iid, at):
        r = self.db.execute("select at from edges where src=? and rel='merged_into'", (iid,)).fetchone()
        return r is not None and r[0] > at

    def items(self, type_, *, at=None, about=None, current_only=False, turn_before=None):
        """Items of a type, optionally attached to a node (`about` edge), as known at `at`; current_only drops those
        replaced at or before `at`."""
        q = 'select i.* from items i'
        args = []
        if about is not None:
            q += f" join edges e on e.src=i.id and e.rel='about' and e.dst=? and {self._edge_live(at).replace('valid_to', 'e.valid_to').replace('at <=', 'e.at <=')}"
            args += self._args(at, about)
        q += ' where i.type=?'; args.append(type_)
        if at is not None: q += ' and i.at <= ?'; args.append(at)
        if turn_before is not None: q += ' and i.turn < ?'; args.append(turn_before)
        if current_only and at is not None: q += ' and (i.replaced_at is null or i.replaced_at > ?)'; args.append(at)
        elif current_only: q += ' and i.replaced_at is null'
        q += ' order by i.at, i.id'
        return [self._row(r) for r in self.db.execute(q, args).fetchall()]

    def about(self, iid, at=None):
        return [r[0] for r in self.db.execute(f"select dst from edges where src=? and rel='about' and {self._edge_live(at)}",
                                               self._args(at, iid)).fetchall()]

    def events_of(self, iid):
        return [{'kind': r[1], 'at': r[2], 'source': r[3], 'data': json.loads(r[4])}
                for r in self.db.execute('select * from events where item=? order by at', (iid,)).fetchall()]

    def commit(self):
        self.db.commit()
