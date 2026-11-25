"""Views generated from memory (concept model v2, 1.2 and 3.7).

The UI is only a view of the same memory: the task metadata page (purpose and scope, working directory, status and its
history, constraints and decisions, progress, relations, execution records, related documents), the task exchange record
(the user's messages for the task, CTM's relays and questions, each run's summary and final reply - generated, not
editable), the tree outline with status, running markers and proposals, and the document version history.
"""
from . import documents as D
from . import execution as X
from . import lifecycle as L


def node_page(store, node, at=None):
    w = store.get(node)
    d = w['data']
    cons = [{'id': r['id'], 'statement': r['data'].get('statement'), 'turn': r['turn'], 'current': r['replaced_at'] is None or (at is not None and r['replaced_at'] > at),
             'exception_of': (store.db.execute("select dst from edges where src=? and rel='exception_of'", (r['id'],)).fetchone() or [None])[0]}
            for r in store.items('constraint', about=node, at=at)]
    decs = [{'id': r['id'], 'statement': r['data'].get('statement'), 'type': r['data'].get('type'), 'turn': r['turn'],
             'current': r['replaced_at'] is None or (at is not None and r['replaced_at'] > at), 'replaced_by': r['replaced_by']}
            for r in store.items('decision', about=node, at=at)]
    inherited = []                                   # siblings' constraints CTM judged to apply here too (scope.inherit_for_new_work)
    for (cid, data) in store.db.execute("select dst, data from edges where src=? and rel='uses' and valid_to is null", (node,)).fetchall():
        r = store.get(cid)
        if r and r['type'] == 'constraint' and r['replaced_at'] is None:
            src = (store.about(cid, at) or [''])[0]
            inherited.append({'id': cid, 'statement': r['data'].get('statement'), 'turn': r['turn'], 'from': src,
                              'from_title': (store.get(src) or {}).get('data', {}).get('title', src)})
    status_hist = [e for e in store.events_of(node) if e['kind'] in ('status', 'needs_recheck', 'children_finished', 'ui_edit', 'move', 'merge')]
    rel = {'parent': store.parent(node, at), 'children': store.children(node, at),
           'after': [r[0] for r in store.db.execute("select src from edges where dst=? and rel='dep' and valid_to is null", (node,)).fetchall()],
           'before': L.successors(store, node),
           'uses': [r[0] for r in store.db.execute("select dst from edges where src=? and rel='uses' and valid_to is null", (node,)).fetchall()]}
    runs = [{'run': r[0], **store.get(r[0])['data']} for r in store.db.execute("select src from edges where dst=? and rel='serves'", (node,)).fetchall()
            if store.get(r[0])['type'] == 'run']
    docs, files = D.index(store, [node], at if at is not None else 9e18)
    return {'id': node, 'kind': w['type'], 'title': d.get('title'), 'purpose': d.get('purpose'), 'working_dir': d.get('working_dir'),
            'environment': [r['data'].get('statement') for r in store.items('environment', about=node, at=at, current_only=True)],
            'status': L.status(store, node), 'status_history': status_hist, 'constraints': cons, 'inherited_constraints': inherited, 'decisions': decs,
            'progress': [dict(r['data'], turn=r['turn'], observed_at=r['observed_at']) for r in store.items('progress', about=node, at=at)],
            'pending': [dict(r['data'], id=r['id']) for r in store.items('pending', about=node, at=at)],
            'relations': rel, 'runs': runs, 'documents': docs, 'files': files, 'proposed': d.get('status') == 'proposed'}


def exchange_record(store, node, at=None):
    """The task's exchange record: user segments, CTM displays, run summaries and replies, in time order."""
    out = []
    for r in store.items('segment', about=node, at=at):
        out.append({'at': r['at'], 'turn': r['turn'], 'who': 'user', 'text': r['data'].get('text')})
    for r in store.items('display', about=node, at=at):
        out.append({'at': r['at'], 'turn': r['turn'], 'who': 'ctm', 'text': f"{r['data'].get('no')}. {r['data'].get('text')}"})
    for r in store.items('progress', about=node, at=at):
        out.append({'at': r['at'], 'turn': r['turn'], 'who': 'summary', 'text': r['data'].get('done') or r['data'].get('note')})
    for (rid,) in store.db.execute("select src from edges where dst=? and rel='serves'", (node,)).fetchall():
        run = store.get(rid)
        if run['type'] != 'run': continue
        if run['data'].get('reply'):
            out.append({'at': run['at'], 'turn': run['turn'], 'who': 'executor', 'text': run['data']['reply']})
        for (x,) in store.db.execute("select src from edges where dst=? and rel='in_run'", (rid,)).fetchall():
            e = store.get(x)
            out.append({'at': e['at'], 'turn': e['turn'], 'who': 'executor', 'text': e['data'].get('reply')})
    return sorted(out, key=lambda x: (x['at'], {'user': 0, 'ctm': 1, 'executor': 2, 'summary': 3}[x['who']]))


def document_page(store, did):
    hist = D.history(store, did)
    return {'id': did, **store.get(did)['data'], 'stale': D.is_stale(store, did), 'versions': [{'id': v['id'], 'at': v['at'], 'source': v['source'],
            'changed_section': v['data'].get('changed_section')} for v in hist], 'latest': hist[-1]['data'] if hist else None,
            'used_by': [r[0] for r in store.db.execute("select src from edges where dst=? and rel='uses'", (did,)).fetchall()],
            'cites': sorted({r[0] for v in hist for r in store.db.execute("select dst from edges where src=? and rel='cites'", (v['id'],)).fetchall()})}
