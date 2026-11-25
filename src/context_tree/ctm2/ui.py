"""User edits in the UI (concept model v2, 1.2 tree UI, 5.5).

Every edit is authoritative and is applied with four kinds of propagation: memory relations (messages, constraints,
decisions follow), running executors (affected ones are updated, an abandoned task's executor is stopped), pending items
(moved or cancelled), and references (the edit is recorded as a 'ui' event that later localization and maintenance treat
as a reference - not locked, but only the user's later words or edits change it directly).
"""
from . import execution as X
from . import lifecycle as L


def _inherited(store, node, at):
    out = []
    for n in [node] + store.ancestors(node, at) + ['ROOT']:
        out += [r['id'] for r in store.items('constraint', about=n, at=at, current_only=True)]
    return set(out)


def _notify_runs(store, node, at, why):
    for rid in X.runs_affected_by(store, node, at):
        nid = store.add('notice', {'text': why}, at=at, source='ui')
        X.forward(store, run_id=rid, item_id=nid, at=at, why=why)


def move(store, node, new_parent, *, at, reason=''):
    before = _inherited(store, node, at)
    store.set_parent(node, new_parent, at=at, source='ui', reason=reason)
    after = _inherited(store, node, at + 1e-6)
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'move', 'to': new_parent, 'gained': sorted(after - before), 'lost': sorted(before - after)})
    _notify_runs(store, node, at, 'The task was moved in the tree; the constraints that apply changed')


def merge(store, keep, drop, *, at, reason=''):
    for p in store.items('pending', about=drop, at=at):
        store.unlink(p['id'], 'about', drop, at=at); store.link(p['id'], 'about', keep, at=at, source='ui')
    run = X.active_run(store, drop)
    if run:
        X.end_run(store, run['id'], 'the task was merged', at=at)
    store.merge(keep, drop, at=at, source='ui', reason=reason)
    store.event(keep, 'ui_edit', at=at, source='ui', data={'op': 'merge', 'absorbed': drop})


def split(store, node, parts, *, at):
    """parts: [{'title','purpose','segments':[segment ids]}]: new sibling tasks; the segments move, and constraints and
    decisions written from those segments' turns move with them."""
    created = []
    for part in parts:
        nid = store.add('task', {'title': part['title'], 'purpose': part.get('purpose', ''), 'status': 'pending'}, at=at, source='ui')
        p = store.parent(node, at)
        if p: store.link(p, 'child', nid, at=at, source='ui')
        for sid in part.get('segments', []):
            reattach_segment(store, sid, nid, at=at)
        created.append(nid)
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'split', 'into': created})
    return created


def reattach_segment(store, segment, node, *, at):
    old = store.about(segment, at)
    for o in old: store.unlink(segment, 'about', o, at=at)
    store.link(segment, 'about', node, at=at, source='ui')
    turn = store.get(segment)['turn']
    for typ in ('constraint', 'decision', 'guidance', 'mention'):    # what was written from this message follows it (mentions keep objects findable)
        for o in old:
            for r in store.items(typ, about=o, at=at):
                if r['turn'] == turn:
                    store.unlink(r['id'], 'about', o, at=at); store.link(r['id'], 'about', node, at=at, source='ui')
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'reattach', 'segment': segment, 'from': old})


def rename(store, node, title, *, at):
    store.patch(node, {'title': title}, at=at, source='ui')
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'rename'})


def set_purpose(store, node, purpose, *, at):
    """The user rewrites what a work is for (a CTM-summarized Goal whose works changed, a task whose aim moved)."""
    store.patch(node, {'purpose': purpose}, at=at, source='ui')
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'purpose'})


def set_status(store, node, new, *, at, reason=''):
    ok = L.set_status(store, node, new, at=at, source='ui', reason=reason)
    if ok and new in ('abandoned', 'replaced'):        # stop what the executor is doing; the session stays for a reopening
        run = X.active_run(store, node)
        if run: X.stop_run(store, run['id'], at=at, why=f'the user set the task to {new}')
        for p in store.items('pending', about=node, at=at):
            if p['data'].get('status', 'open') == 'open': store.patch(p['id'], {'status': 'cancelled'}, at=at, source='ui')
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'status', 'to': new, 'applied': ok})
    return ok


def move_constraint(store, constraint, node, *, at):
    for o in store.about(constraint, at): store.unlink(constraint, 'about', o, at=at)
    store.link(constraint, 'about', node, at=at, source='ui')
    store.event(constraint, 'ui_edit', at=at, source='ui', data={'op': 'move_constraint', 'to': node})
    _notify_runs(store, node, at, 'The user moved a constraint')


def drop_inherited_constraint(store, node, constraint, *, at):
    """The user says a sibling's constraint CTM gave this work does not apply here: the reference goes (the user's edit over CTM's
    inference); the constraint stays where it was."""
    store.unlink(node, 'uses', constraint, at=at)
    store.event(node, 'ui_edit', at=at, source='ui', data={'op': 'drop_inherited_constraint', 'constraint': constraint})
    _notify_runs(store, node, at, 'The user removed a constraint CTM had judged to apply')


def change_constraint_kind(store, constraint, kind, *, at, obj=None, working_dir=''):
    from . import documents as D
    store.patch(constraint, {'kind': kind}, at=at, source='ui')
    if kind == 'object':
        for o in store.about(constraint, at): store.unlink(constraint, 'about', o, at=at)
        D.index_object_constraint(store, constraint=constraint, obj=obj, working_dir=working_dir, at=at)
    store.event(constraint, 'ui_edit', at=at, source='ui', data={'op': 'kind', 'to': kind})


def user_edited(store, node):
    """Nodes the user edited: maintenance treats them as references and changes them only on the user's later evidence."""
    return bool(store.db.execute("select 1 from events where item=? and kind='ui_edit'", (node,)).fetchone())


def create_task(store, tree, title, purpose, parent, *, at, working_dir=''):
    """The user creates a node in the tree UI: authoritative, not a proposal."""
    nid = tree.add(title, purpose, parent, None, 0, at, working_dir=working_dir, source='ui')
    store.event(nid, 'ui_edit', at=at, source='ui', data={'op': 'create'})
    return nid


EDIT_CHECK = '''The user edited a section of a document directly in the document browser. Below are the edited content and this work's current decisions.
Which decisions does the edited content contradict? A contradiction is the user's new statement; give the suggested new decision, in the language the user writes in. Output JSON only: {"conflicts":[{"decision":"DE3","new_statement":".."}]}'''


def edit_document(store, did, section, text, *, at, model=None):
    """A user edit of a knowledge document becomes a version with source 'user'; where it contradicts a current decision CTM
    proposes updating that decision (3.7)."""
    from . import documents as D
    from .model import ask
    task = (store.about(did) or [None])[0]
    vid = D.update_section(store, did, section, text, run=None, task=task, at=at, source='ui')
    store.event(did, 'ui_edit', at=at, source='ui', data={'op': 'edit_document', 'section': section})
    proposals = []
    if model and task:
        decs = [{'id': d['id'], 'statement': d['data'].get('statement')} for n in [task] + store.ancestors(task, at)
                for d in store.items('decision', about=n, at=at, current_only=True)]
        if decs:
            out, _ = ask(EDIT_CHECK, {'section': section, 'text': text, 'decisions': decs}, model=model, effort='low', role='doc-edit')
            for c in out.get('conflicts') or []:
                pid = store.add('pending', {'kind': 'proposed_decision_update', 'status': 'open', 'replaces': c.get('decision'),
                                            'what': c.get('new_statement')}, at=at, source='ctm')
                store.link(pid, 'about', task, at=at, source='ctm'); proposals.append(pid)
    return vid, proposals


def edit_root_item(store, item, text, *, at):
    """The user edits a root entry (persona, an understanding entry, an overall goal, a preference): a new version replaces
    the old one, which is kept as history (3.3)."""
    old = store.get(item)
    field = 'text' if 'text' in old['data'] else 'statement'
    new = store.add(old['type'], dict(old['data'], **{field: text}), at=at, source='user')
    store.link(new, 'about', 'ROOT', at=at, source='ui')
    store.replace(item, new, at=at, source='user')
    store.event(new, 'ui_edit', at=at, source='ui', data={'op': 'edit_root', 'previous': item})
    return new
