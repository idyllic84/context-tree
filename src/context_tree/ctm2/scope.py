"""Constraint scope adjustment (concept model v2, 3.5: lifting a constraint and moving it back down).

When the user states a task constraint, CTM looks for the same requirement already in force on other branches (embedding
similarity proposes candidates, the model decides whether they are the same requirement). If they are, it judges where the
requirement belongs: it moves up to the branches' common parent when it holds for all work there; an object rule becomes an
object-constraint proposal and an all-work habit a root-preference proposal (both need the user's acceptance). A wrong lift is
undone by a subtree exception or by moving the constraint back down (maintenance op lower_constraint, or the user in the tree).
Every move records how inherited constraints changed and notifies the executors under the node.
"""
import math

from context_tree.common import llm as base
from .model import ask

PROMPT = '''The user just stated a constraint for a work (new, with the path of its work). Below are current constraints on other branches that may be similar (candidates, with the paths of their works).
First judge which candidates state the same requirement as new (same; the same requirement in different words counts, a similar but different requirement does not). If there are any, judge where this requirement belongs (destination):
- lift: it holds for every work under the common parent (common_parent, with the titles of the works under it): lift it to the common parent;
- object: it is a rule about an object itself (file, module, directory, interface): propose making it an object constraint; object names the object;
- global: it is a personal habit or prohibition that holds for all the user's work: propose it as a preference on the root;
- behavior: it is how agents should generally do a kind of operation (a "how to", like a skill): propose moving it into a behavior guidance document;
- keep: it holds only for each work on its own; leave it.
When unsure, keep. Output JSON only: {"same":["CO3"],"destination":"lift|object|global|behavior|keep","object":null,"why":"one sentence"}'''


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def _vec(cache, key, text):
    if key not in cache:
        cache[key] = base.embeddings([text[:1000]])[0]
    return cache[key]


def lca(store, nodes, at):
    """Lowest common ancestor of work nodes (None when they only share the root)."""
    paths = [[n] + store.ancestors(n, at) for n in nodes]
    common = set(paths[0]).intersection(*map(set, paths[1:])) if len(paths) > 1 else set(paths[0])
    for x in paths[0]:
        if x in common: return x
    return None


def candidates(store, cid, at, cache, k=6):
    """Current user task constraints on other branches (not on the new constraint's path or below it), most similar first."""
    node = (store.about(cid, at) or [None])[0]
    if not node or node == 'ROOT': return []
    path = set([node] + store.ancestors(node, at))
    stmt = store.get(cid)['data'].get('statement') or ''
    out = []
    for (oid,) in store.db.execute("select id from items where type='constraint' and source='user' and id != ? and at <= ? and (replaced_at is null or replaced_at > ?)",
                                   (cid, at, at)).fetchall():
        o = store.get(oid)
        if o['data'].get('kind') != 'task': continue
        on = (store.about(oid, at) or [None])[0]
        if not on or on == 'ROOT' or on in path or node in store.ancestors(on, at): continue
        out.append((oid, on, o['data'].get('statement') or ''))
    if not out: return []
    q = _vec(cache, cid, stmt)
    scored = sorted(out, key=lambda x: -_cos(q, _vec(cache, x[0], x[2])))
    return scored[:k]


def check(store, tree, cid, *, at, model, cache, log=None):
    """Decide and apply where a newly stated task constraint belongs given the same requirement elsewhere. Returns the decision."""
    cands = candidates(store, cid, at, cache)
    if not cands: return None
    title = lambda n: (store.get(n) or {}).get('data', {}).get('title', n)
    path = lambda n: ' / '.join(title(x) for x in reversed([n] + store.ancestors(n, at)))
    node = store.about(cid, at)[0]
    payload = {'new': {'id': cid, 'statement': store.get(cid)['data'].get('statement'), 'work': path(node)},
               'candidates': [{'id': oid, 'statement': st, 'work': path(on)} for oid, on, st in cands]}
    nodes_by_id = {oid: on for oid, on, _ in cands}
    common = lca(store, [node] + list(nodes_by_id.values()), at)
    payload['common_parent'] = {'id': common, 'title': title(common), 'children': [title(c) for c in store.children(common, at)][:20]} if common else None
    out, usage = ask(PROMPT, payload, model=model, effort='low', role='scope')
    same = [x for x in out.get('same') or [] if x in nodes_by_id]
    dest = out.get('destination')
    if log is not None: log.setdefault('scope', []).append({'constraint': cid, 'same': same, 'destination': dest, 'why': out.get('why')})
    if not same or dest in (None, 'keep'): return out
    if dest == 'lift':
        target = lca(store, [node] + [nodes_by_id[x] for x in same], at)
        if not target: return out                           # only the root in common: a structure question for maintenance
        lift(store, cid, target, at=at, duplicates=same, why=out.get('why'))
    elif dest in ('object', 'global', 'behavior'):
        pid = store.add('pending', {'kind': {'object': 'proposed_object_constraint', 'global': 'proposed_preference', 'behavior': 'proposed_behavior'}[dest], 'status': 'open',
                                    'constraints': [cid] + same, 'object': out.get('object'),
                                    'what': f"\"{store.get(cid)['data'].get('statement')}\" appears in several works. Suggest making it " +
                                            {'object': 'an object constraint (' + (out.get('object') or '') + ')', 'global': 'your global preference', 'behavior': 'agent behavior guidance'}[dest]},
                        at=at, source='ctm')
        store.link(pid, 'about', 'ROOT', at=at, source='ctm')
    return out


def _inherited(store, node, at):
    out = set()
    for n in [node] + store.ancestors(node, at) + ['ROOT']:
        out |= {r['id'] for r in store.items('constraint', about=n, at=at, current_only=True)}
    return out


def _subtree(store, node, at):
    out, todo = [], [node]
    while todo:
        x = todo.pop(); out.append(x); todo += store.children(x, at)
    return out


def lift(store, cid, target, *, at, duplicates=(), why='', source='ctm'):
    """Move a constraint up to `target`; identical copies on the branches are folded into it. Inheritance changes are logged
    on every affected node and executors under the target are notified."""
    from . import execution as X
    affected = _subtree(store, target, at)
    before = {n: _inherited(store, n, at) for n in affected}
    olds = store.about(cid, at)
    for o in olds: store.unlink(cid, 'about', o, at=at)
    store.link(cid, 'about', target, at=at, source=source)
    for d in duplicates:
        for o in store.about(d, at): store.unlink(d, 'about', o, at=at)
        store.link(d, 'merged_into', cid, at=at, source=source)
    store.event(cid, 'lifted', at=at, source=source, data={'from': olds, 'to': target, 'duplicates': list(duplicates), 'why': why})
    for n in affected:
        a = _inherited(store, n, at + 1e-6)
        if a != before[n]:
            store.event(n, 'inheritance_change', at=at, source=source, data={'gained': sorted(a - before[n]), 'lost': sorted(before[n] - a)})
    for rid in X.runs_affected_by(store, target, at):
        nid = store.add('notice', {'text': f"The constraint \"{store.get(cid)['data'].get('statement', '')}\" now applies to all work under \"{(store.get(target) or {}).get('data', {}).get('title', target)}\""},
                        at=at, source=source)
        X.forward(store, run_id=rid, item_id=nid, at=at, why='constraint lifted')


def lower(store, cid, nodes, *, at, why='', source='maintenance'):
    """Move a constraint back down to the given nodes (the reverse of a wrong lift)."""
    olds = store.about(cid, at)
    for o in olds: store.unlink(cid, 'about', o, at=at)
    for n in nodes: store.link(cid, 'about', n, at=at, source=source)
    store.event(cid, 'lowered', at=at, source=source, data={'from': olds, 'to': list(nodes), 'why': why})


INHERIT_NEW = '''A new work has just joined a level of the task tree (new_work: its path, its purpose and the user's words this time). The sibling works on the same level carry some constraints (siblings: each work's title, purpose and the constraints attached to it).
A sibling's constraints go only to that work's own executor - mostly they are requirements for that one work's output or approach. But while doing one of them the user also often states requirements for the larger whole (rules for the same product,
practices this kind of work must always follow), which the new work should follow too when it touches the same things; attached to the sibling, they never reach the new work's executor, and the user has to say them again.
Judge which constraints also apply to this new work: by the constraint's content and what the user meant when saying it, the new work will touch what it constrains and should follow it too. Those that apply go to the new work's executor, marked with the work they come from;
given wrongly, the executor is restricted where it should not be; missed, the user has to say it again. Analyse first, then judge; when unsure, do not give it.
Output JSON only: {"analysis":"..","applies":["CO1"],"why":"one sentence"}'''


def inherit_for_new_work(store, node, *, at, model, message='', apply=True, ask_fn=None):
    """Concept 3.5 for a new work: the constraints on its siblings that also apply to it are given to it (a 'uses' reference,
    marked as CTM's judgment), leaving the siblings and the rest of the level as they are. Code decides only when to ask."""
    par = store.parent(node, at)
    if not par: return {}
    title = lambda n: (store.get(n) or {}).get('data', {}).get('title', n)
    purpose = lambda n: ((store.get(n) or {}).get('data', {}).get('purpose') or '')[:200]
    sibs = []
    for c in [x for x in store.children(par, at) if x != node]:
        cons = [{'id': r['id'], 'statement': r['data'].get('statement', '')[:300]}
                for n in _subtree(store, c, at) for r in store.items('constraint', about=n, at=at, current_only=True)
                if r['data'].get('kind') == 'task']
        if cons: sibs.append({'id': c, 'title': title(c), 'purpose': purpose(c), 'constraints': cons[-8:]})
    if not sibs: return {}
    payload = {'new_work': {'path': ' / '.join(title(x) for x in reversed([node] + store.ancestors(node, at))), 'purpose': purpose(node),
                            'user_words': (message or '')[:1500]},
               'siblings': sibs[:12]}
    out, _ = (ask_fn or ask)(INHERIT_NEW, payload, model=model, effort='medium', role='inherit-new')
    ids = {c['id'] for s_ in sibs for c in s_['constraints']}
    got = [c for c in (out.get('applies') or []) if c in ids]
    if apply:
        for cid in got:
            store.link(node, 'uses', cid, at=at, source='ctm', data={'why': out.get('why') or '', 'inferred': True})
    return {'applies': got, 'why': out.get('why'), 'analysis': out.get('analysis'), 'payload': payload}
