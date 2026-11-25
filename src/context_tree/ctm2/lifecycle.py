"""Task lifecycle (concept model v2, 3.4 status and relations, 3.6 cross-task references, section 4 phases and timing).

Status changes are events with time, reason and source; time passing alone never changes a status. Dependencies
(serial, join, conditional, alternative) decide when a task becomes executable; a predecessor whose result is overturned
marks its successors for re-check. A parent's completion is judged when needed (the user asks about progress, a successor
depends on it, results should fold further up): its children must all be finished and its purpose covered - children are
added one step at a time and may not cover the purpose yet. On completion a task's result folds up into the parent and is
handed to the successors.
"""
STATUSES = ('proposed', 'pending', 'ready', 'running', 'blocked', 'paused', 'reported_done', 'verified', 'abandoned', 'replaced', 'reopened')
FINISHED = ('reported_done', 'verified', 'abandoned', 'replaced')
DONE = ('reported_done', 'verified')
ALLOWED = {
    'proposed': {'pending', 'ready', 'abandoned'},
    'pending': {'ready', 'running', 'paused', 'abandoned', 'replaced', 'blocked'},
    'ready': {'running', 'pending', 'paused', 'abandoned', 'replaced'},
    'running': {'blocked', 'paused', 'reported_done', 'verified', 'abandoned', 'replaced', 'pending'},
    'blocked': {'running', 'paused', 'abandoned', 'replaced', 'pending', 'ready'},
    'paused': {'pending', 'ready', 'running', 'abandoned', 'replaced'},
    'reported_done': {'verified', 'reopened', 'running', 'replaced'},
    'verified': {'reopened', 'replaced'},
    'abandoned': {'reopened'},
    'replaced': {'reopened'},
    'reopened': {'pending', 'ready', 'running'},
}


def status(store, node):
    return (store.get(node) or {}).get('data', {}).get('status') or 'pending'


def set_status(store, node, new, *, at, source, reason=''):
    """Apply a status event if the transition is allowed; returns True when applied. Side effects: readiness of
    successors, fold-up on completion, re-check marks when a finished result is reopened or replaced."""
    old = status(store, node)
    if new == old: return False
    if new not in STATUSES or new not in ALLOWED.get(old, set()):
        store.event(node, 'status_rejected', at=at, source=source, data={'from': old, 'to': new, 'reason': reason})
        return False
    store.patch(node, {'status': new}, at=at, source=source, reason=reason)
    store.event(node, 'status', at=at, source=source, data={'from': old, 'to': new, 'reason': reason})
    if new in DONE:
        fold_up(store, node, at=at, source=source)
        for succ in successors(store, node):
            refresh_ready(store, succ, at=at, source='ctm')
        p = store.parent(node)
        if p:                                         # successors of the parent may be waiting for it (judged on demand)
            for succ in successors(store, p):
                refresh_ready(store, succ, at=at, source='ctm')
    if old in DONE and new in ('reopened', 'replaced'):
        for succ in successors(store, node):
            store.event(succ, 'needs_recheck', at=at, source='ctm', data={'because': node, 'reason': f'predecessor {new}'})
    return True


def add_dep(store, before, after, *, at, source, kind='serial', condition=None):
    """after depends on before. kind: serial (before must finish), join (all such predecessors), conditional (before's
    result must satisfy `condition`, judged by CTM when it finishes), alternative (any one of the predecessors)."""
    store.link(before, 'dep', after, at=at, source=source, data={'type': kind, 'condition': condition})
    refresh_ready(store, after, at=at, source=source)


def predecessors(store, node):
    rows = store.db.execute("select src, data from edges where dst=? and rel='dep' and valid_to is null", (node,)).fetchall()
    import json
    return [(r[0], json.loads(r[1]) if r[1] else {}) for r in rows]


def successors(store, node):
    return [r[0] for r in store.db.execute("select dst from edges where src=? and rel='dep' and valid_to is null", (node,)).fetchall()]


def deps_satisfied(store, node):
    preds = predecessors(store, node)
    if not preds: return True
    alts = [p for p, d in preds if d.get('type') == 'alternative']
    musts = [p for p, d in preds if d.get('type') != 'alternative']
    ok_musts = all(is_done(store, p) for p in musts)
    ok_alts = (not alts) or any(is_done(store, p) for p in alts)
    conds = [(p, d) for p, d in preds if d.get('type') == 'conditional']
    ok_conds = all(store.db.execute("select 1 from events where item=? and kind='condition_met'", (node + '|' + p,)).fetchone() for p, d in conds)
    return ok_musts and ok_alts and ok_conds


def refresh_ready(store, node, *, at, source):
    st = status(store, node)
    if st == 'pending' and deps_satisfied(store, node):
        set_status(store, node, 'ready', at=at, source=source, reason='preconditions met')
    elif st == 'ready' and not deps_satisfied(store, node):
        set_status(store, node, 'pending', at=at, source=source, reason='preconditions not met')


def fold_up(store, node, *, at, source):
    """Write the finished task's result (its latest progress, including 'not feasible') to the parent and successors."""
    prog = store.items('progress', about=node)
    last = prog[-1]['data'] if prog else {}
    title = (store.get(node) or {}).get('data', {}).get('title', node)
    summary = {'statement': f"Subtask \"{title}\" { {'reported_done': 'done (self-reported)', 'verified': 'done (verified)'}.get(status(store, node), 'ended')}: "
                            f"{last.get('done', '')}; open: {last.get('open') or 'none'}; verified: {last.get('verified', '')}", 'from': node}
    targets = [p for p in [store.parent(node)] if p] + successors(store, node)
    for t in targets:
        rid = store.add('result', summary, at=at, source=source)
        store.link(rid, 'about', t, at=at, source=source); store.link(rid, 'folded_from', node, at=at, source=source)


def children_finished(store, node):
    """None if the node has no children; otherwise whether all of them are finished (abandoned and replaced ones aside, at
    least one done)."""
    kids = store.children(node)
    if not kids: return None
    live = [k for k in kids if status(store, k) not in ('abandoned', 'replaced')]
    return bool(live) and all(status(store, k) in DONE for k in live)


def is_done(store, node):
    """For dependencies: a task is done by its own status; a parent also when all its children are finished (cheap check;
    whether the purpose is covered is judged by parent_completion when someone needs it)."""
    return status(store, node) in DONE or children_finished(store, node) is True


PARENT = '''Judge whether a parent work is finished. Its subtasks were added step by step and may not yet cover all of its purpose.
From the parent's purpose and the status and results of its subtasks, judge: done (the whole purpose is accomplished) / not_done (some subtasks are unfinished) / gap (all subtasks are done, but part of the purpose has no work for it; say what).
Output JSON only: {"verdict":"done|not_done|gap","missing":"..","why":"one sentence"}'''


def parent_completion(store, node, *, at, model):
    """On-demand completion judgment of a parent: its children and its purpose."""
    from .model import ask
    kids = store.children(node, at)
    if not kids: return {'verdict': 'done' if status(store, node) in DONE else 'not_done', 'missing': '', 'why': 'no subtasks; by its own status'}
    if children_finished(store, node) is False:
        return {'verdict': 'not_done', 'missing': ', '.join((store.get(k) or {}).get('data', {}).get('title', k) for k in kids
                                                          if status(store, k) not in DONE + ('abandoned', 'replaced')), 'why': 'some subtasks are unfinished'}
    d = (store.get(node) or {}).get('data', {})
    res = [r['data'].get('statement') for r in store.items('result', about=node, at=at)][-12:]
    out, _ = ask(PARENT, {'parent': {'title': d.get('title'), 'purpose': d.get('purpose')}, 'children': [{'title': (store.get(k) or {}).get('data', {}).get('title'),
                 'status': status(store, k)} for k in kids], 'results': res}, model=model, effort='low', role='parent-done')
    return out


def recheck_on_replaced_decision(store, decision_id, *, at):
    """A decision referenced by other tasks (Task -uses-> Decision) was replaced: those tasks are marked for re-check (3.6)."""
    for (t,) in store.db.execute("select src from edges where rel='uses' and dst=? and valid_to is null", (decision_id,)).fetchall():
        store.event(t, 'needs_recheck', at=at, source='ctm', data={'because': decision_id, 'reason': 'a decision it uses was replaced'})


def condition_met(store, before, after, *, at, source='ctm', note=''):
    """CTM judged that `before`'s result satisfies the condition of a conditional dependency of `after` (e.g. tests passed)."""
    store.event(after + '|' + before, 'condition_met', at=at, source=source, data={'note': note})
    refresh_ready(store, after, at=at, source=source)
