"""Maintenance over the store (concept model v2, 5.6).

Reads what was written since its last run - message segments and run summaries with the node each was placed on - and
re-checks root-level nodes that could not yet name a service relation. Besides the V2 operations (set_parent,
create_goal, create_parent, merge, rename) it fixes order (dependencies) and status when the records show it, lifts a
constraint to a newly created shared parent when the user's words covered the shared purpose, proposes an object
constraint for a requirement repeated across tasks, and records inferred understanding of the user (CTM-only).
Every move logs how the moved node's inherited constraints changed. Nodes the user edited are references: changes to them
are only proposals unless the user's later words contradict them.
"""
import json

import time
from .model import ask
from . import lifecycle as L
from . import root as R
from . import ui as UI

# 2026-11-18: works with agreed labels, ended or not, 25/43 -> 36/43 (V10 left 18 ended works in progress)
PROMPT = '''You are CTM's periodic maintenance. CTM writes each message into memory when it arrives (delivered to a work, its constraints and decisions recorded), seeing only that moment; maintenance looks back at what was written since the last maintenance and corrects what was not seen clearly then.
Input: the message parts and execution summaries written since the last maintenance (each: turn, hours ago, a summary of the content, the node it was put on when written), the nodes these records touch with their ancestors and siblings (with status, current constraints, and whether the user edited them on the page), root-level nodes to be rechecked, all top-level nodes, and works that have not moved for some time but are still in progress (status_review).

The task tree: under the root are Goals (the user's long-term objectives), under a Goal are tasks, subtasks are parts of a task (the task is done only when its subtasks are done), and the works under one parent are parallel parts or successive steps.
What the tree is for: the constraints and decisions of the works above reach the works below; executors see the scene on the path and of the latest siblings; the user finds their things in the tree and sees how they stand. One set of works often has several reasonable organizations and there is no single answer;
an adjustment has its own cost (positions the user and the executors know change), so adjust only when the current organization clearly works against these uses. Which Goal a work belongs to, and which works of one level go under a common parent, are settled by other judgments; here you correct what was not seen clearly when it was written.

Analyse first, then adjust. In analysis write what you see (a few sentences), thinking through:
- Which works the user was moving forward in this period, and what each record actually moves forward; whether that matches the node it was put on - a message that in hindsight belongs to another existing work (including one first raised as a question that later grew into that work), or messages of another work that has no node yet mixed into a node.
- Whether the relations between nodes reflect the work itself: a node that is really a part of another work, two nodes that are really the same work (created twice), whether a title still identifies the work. When the records under one node contain several different outputs, most likely some content is misplaced; that content should move away, rather than the title being widened.
- Status: a work's status is used in several places - when it ends, its results go to its parent and its successors (which may then start); when the user mentions it again, the delivery uses it to tell continuing from a new step; the user sees in the tree what is still going on and what is left.
  An executor reporting "done" only says that one request is done; the user often has follow-up questions and changes, so do not go by the report alone; nor wait for the user to say "finished" - the user mostly does not say it, but moves on. Judge from the situation: after the user accepted the result,
  or after the execution reported done with nothing left open, the user moved on to other things and did not come back for a long time (see hours_since_active, the works done since, the latest results and open problems) - then the work has most likely ended.
  Ended works with traces such as tests or run results, or checked by the user, are verified; those with only the executor's own report are reported_done; abandoned when the user said not to do it; paused when it is clearly unfinished (open problems, half done) and the user moved elsewhere; reopened when an ended work is taken up again.
  The cost of a wrong judgment: ended too early, the user's return to it is taken as a new step (the new executor has its results and scene, little is lost); never marked, its results never reach its parent and successors, the tree is all "in progress", and the user cannot tell what is left.
  status_review lists works that have not moved for some time but are still in progress; look at each of them too.
- The place of constraints and guidance: whether where a requirement is attached lets it reach every work it applies to without bringing it into works it does not apply to; whether a requirement recurring in different works is really a rule of an object itself.
- Other: waiting relations between works that the tree does not record; stable traits of how the user works; documents that duplicate each other or have grown too large; research that is really part of a work; Goals that serve an overall goal.
Then give the adjustments (ops), each with its grounds in why: which records, which relation. Nodes with user_edited true were edited by the user on the page; change them only when the user's later words in these records contradict them (evidence_turns). Do not create cycles.

Possible adjustments:
- set_parent: a node's place does not reflect its relation to other works (parent: where it belongs);
- move_messages: some messages (turns) under a node belong to another existing work -> move them to that work (to);
- split: some messages under a node are another work that has no node yet -> create a node (title and purpose for that work, parent by its relation to other works) and move these messages to it;
  the constraints, decisions, mentions and execution summaries of those turns move with them; a session already running is not split, and later messages are delivered by the new placement. Moved right, that work's executor later sees its full history; moved wrong, one work's history is torn apart;
- merge: two nodes are the same work; rename: rename a node whose title does not identify the work;
- add_dep: a work has to wait for another's result and the tree does not record it;
- set_status: a node's status does not match the records (evidence_turns: the turns it rests on);
- lift_constraint / lower_constraint: move a constraint up to the work above that it applies to, or back down to the nodes it applies to (nodes);
- propose_object_constraint: several constraints look like rules of one object itself -> propose making them an object constraint (the user confirms);
- add_understanding: one understanding of how the user works, with the turns it rests on and how sure it is;
- link_overall_goal: link a Goal to the overall goal it serves (only a link; it authorizes nothing);
- tidy_document: suggest merging duplicate documents or splitting one that has grown too large (done by the next related execution);
- attach_research: a research is part of a work (the user said it serves that work, or that work goes on from its conclusions) -> put it under that work (parent).
Write titles, purposes and understandings in the language the user writes in.
Output JSON only: {"analysis":"..","ops":[{"op":"set_parent","node":"N5","parent":"N2","why":".."},
{"op":"move_messages","turns":[31,32],"to":"N4","why":".."},{"op":"split","node":"N3","turns":[40,41,45],"title":"..","purpose":"..","parent":null,"why":".."},
{"op":"merge","keep":"N2","drop":"N7","why":".."},{"op":"rename","node":"N3","title":"..","why":".."},
{"op":"add_dep","before":"N3","after":"N4","type":"serial","why":".."},{"op":"set_status","node":"N3","status":"abandoned|paused|reported_done|verified|reopened","evidence_turns":[30],"why":".."},
{"op":"lift_constraint","constraint":"CO12","to":"N9","why":".."},{"op":"lower_constraint","constraint":"CO12","nodes":["N10"],"why":".."},
{"op":"propose_object_constraint","constraints":["CO3","CO8"],"object":"..","why":".."},
{"op":"add_understanding","text":"..","evidence_turns":[3,9],"confidence":"low|medium|high"},{"op":"link_overall_goal","goal":"N2","overall_goal":"OV1"},
{"op":"tidy_document","documents":["DO3","DO5"],"action":"merge|split","why":".."},{"op":"attach_research","research":"RE2","parent":"N5","why":".."}]}'''

STRUCTURE = '''You are CTM's structure judgment. In CTM's task tree a child node is a part of its parent (the parent work is done only when its child works are done), and the nodes under one parent are parallel parts or successive steps.
The user often raises one larger work in pieces, days or even weeks apart, and CTM created a node for each piece at the time; so within one level of the tree, several works may really be parts or successive steps of one larger work that has no node yet.
What structure is for: the constraints and decisions of a parent reach the works below it; executors see each other's results and scenes under the same parent; the user sees in the tree at a glance what they are doing. The works of one level often have several reasonable organizations and there is no single answer, and the tree will keep adjusting to new work; give an organization that serves these uses.
The input is one level of the tree (level: its parent, or a Goal); each work comes with title, purpose, working directory, time span, status, number of messages, child works, latest results, and the work the user was doing when it was raised (raised_during).
trigger says why this level is looked at now: new_work means a new work was just created, and focus lists the works the delivery thought might belong to one work with it; maintenance means periodic maintenance thinks this level may need tidying (why gives the reason).

Analyse first, then decide. In analysis write the relations you see (a few sentences): how the works of this level relate - which of them together accomplish one thing (one deliverable, the solution of one problem, one feature), whether they are parts of it, successive steps, or one done for another;
which only share a project, an object, a topic or nearness in time, each accomplishing its own thing. Then think: would putting some of them under one parent help them - sharing the parent's constraints, seeing each other's results - and would it bring unrelated constraints and scenes to one of them?
When there are such works, create a parent and put them under it (groups): the parent's title and purpose state that thing and its output (product). This is not a classification of the level; most works usually need no group.
When trigger is new_work, only consider whether the works in focus should be grouped with others. Works with user_edited true were edited by the user on the page; leave them.
Write titles and purposes in the language the user writes in.
Output JSON only: {"analysis":"..","groups":[{"title":"..","purpose":"..","product":"the output of this thing","children":["N3","N8"],"why":"how they together accomplish this thing"}]}'''

GOALS = '''You are CTM's goal organization. CTM's task tree: under the root there are only Goals - the user's long-term objectives; the concrete works the user raises time after time go under the Goal they serve.
What a Goal is for: the works under it inherit its constraints (the user's lasting requirements for this kind of work, which need not be repeated each time); executors see the works recently done under the same Goal (how it was done last time, what was run into); the user sees in the tree, Goal by Goal, which things they are moving forward.
One set of works often has several reasonable organizations and there is no single answer, and the tree will keep adjusting to new work; understand these works and give an organization that serves the uses above.
Input: the existing Goals (goals, with purpose, the latest works under them, the working directories involved), and the works not yet under a Goal (works, ordered by start time, with purpose, working directory, time span, status, child works, latest results, and the work the user was doing when it was raised, raised_during).

Analyse first, then decide. In analysis write the long-term things you see, what each is for, and which works each includes (a few sentences). Think through:
- What the user was pursuing in this period: which long-term things were moving forward, and what each was for. The main task of a period can be one very large thing.
- Why each work was raised and which thing it moves forward: which work the user was doing when it was raised (raised_during), whether it was prompted by that work - serving it, arising from its result, an idea it led to - or is a separate thing; a work with a more general output may still have its cause in one thing, and placing it under that thing or on its own may both be reasonable; choose what is more useful for it.
- Which works are useful to each other: whether a lasting requirement the user stated for one also holds for another; whether one's results and the problems it ran into are useful to the other's executor. Only works that share these belong under one Goal; a Goal holding unrelated works passes unrelated constraints and scenes to them.
- Whether some existing Goals are really the same long-term thing (merge_goals, the first is kept).
A Goal's title states the long-term thing (in the user's words when the user said it), not what was done this time; write it in the language the user writes in. A working directory is where work happens; one thing may span several directories, and one directory often holds several things.
Every work needs a Goal: an existing one by its id, a new one in new_goals (keys g1, g2, ...). Output JSON only: {"analysis":"..","assign":[{"work":"N3","goal":"N100"},{"work":"N5","goal":"g1"}],
"new_goals":[{"key":"g1","title":"a short title (about six words)","purpose":"..","why":"why these works are one long-term thing"}],"merge_goals":[["N100","N120"]]}'''


STATUS_REVIEW_H = 12.0          # V11: works with no activity for this long and still in progress are listed for the status review


def last_maintenance(store):
    r = store.db.execute("select max(at) from events where item='ROOT' and kind='maintenance'").fetchone()
    return r[0] if r and r[0] is not None else -1.0


def window_since(store, tree, since, now):
    window = []
    for r in store.items('segment', at=now):
        if r['at'] <= since: continue
        a = [x for x in store.about(r['id'], now) if x in tree.nodes]
        window.append({'i': r['turn'], 'time': r['at'], 'user': r['data'].get('text') or '', 'node': a[0] if a else None})
    for r in store.items('progress', at=now):
        if r['at'] <= since or not r['data'].get('done'): continue
        a = [x for x in store.about(r['id'], now) if x in tree.nodes]
        window.append({'i': r['turn'], 'time': r['at'], 'user': '[execution summary] ' + (r['data'].get('done') or ''), 'node': a[0] if a else None})
    window.sort(key=lambda w: (w['time'], w['i'] or 0))
    return window


def maintain_store(store, tree, now, *, model, effort='medium', recheck_window=2, prompt=None, since=None, max_window=160):
    """Returns (applied ops, usage). since / max_window: evaluation over a chosen span (default: since the last run, 160 records)."""
    since = last_maintenance(store) if since is None else since
    prev = [r[0] for r in store.db.execute("select at from events where item='ROOT' and kind='maintenance' order by at desc limit ?",
                                           (recheck_window,)).fetchall()]
    recheck_since = prev[-1] if prev else -1.0
    window = window_since(store, tree, since, now)
    if not window:
        return [], {}
    touched = [w['node'] for w in window if w.get('node') in tree.nodes]
    roots_new = [n.id for n in tree.nodes.values() if n.parent not in tree.nodes and n.kind == 'task'
                 and (store.get(n.id)['at'] > recheck_since or n.id in touched)]
    keep = []
    for n in dict.fromkeys(touched + roots_new):
        for m in [n] + tree.ancestors(n):
            if m not in keep: keep.append(m)
        par = tree.nodes[n].parent
        if par is not None:
            keep += [s.id for s in tree.nodes.values() if s.parent == par and s.id not in keep]

    def card(n):
        d = dict(tree.detail(n, now), title=tree.nodes[n].title, parent=tree.nodes[n].parent, user_edited=UI.user_edited(store, n),
                 status=(store.get(n) or {}).get('data', {}).get('status'))
        d['constraints'] = [{'id': c['id'], 'statement': c['data'].get('statement'), 'covers': c['data'].get('covers')}
                            for c in store.items('constraint', about=n, at=now, current_only=True)][-6:]
        # a status needs what failed and what was verified (concept 3.4: progress)
        d['latest_results'] = [{'turn': p['turn'], 'done': (p['data'].get('done') or p['data'].get('note') or '')[:200],
                                'open': [str(o)[:100] for o in (p['data'].get('open') or [])[:3]],
                                'failed': [str(o)[:150] for o in (p['data'].get('failed') or [])[:3]],
                                'verified': str(p['data'].get('verified') or '')[:150]} for p in store.items('progress', about=n, at=now)[-2:]]
        return d
    payload = {'recent_turns': [{'i': w['i'], 'hours_ago': round((now - w['time']) / 3600, 1), 'user': w['user'][:200], 'node': w.get('node'),
                                 'node_title': tree.nodes[w['node']].title if w.get('node') in tree.nodes else None} for w in window[-max_window:]],
               'nodes': [card(n) for n in keep[:90]],
               'root_level_to_recheck': roots_new[:40],
               'documents': [{'id': r['id'], 'title': r['data'].get('title'), 'kind': r['data'].get('kind'), 'use_when': r['data'].get('use_when'),
                              'about': n} for n in dict.fromkeys(touched) for r in store.items('document', about=n, at=now)][-40:],
               'research': [{'id': r['id'], 'title': r['data'].get('title'), 'related': store.about(r['id'], now)}
                            for r in store.items('research', at=now) if r['data'].get('status') != 'attached'][-20:],
               'overall_goals': [{'id': g['id'], 'text': g['data'].get('text')} for g in store.items('overall_goal', at=now, current_only=True)],
               'top_level': [o for o in tree.outline(now) if o['parent'] is None][:60]}
    # works left in progress, not among the cards above (by time only)
    live = ('running', 'blocked', 'pending', 'ready', 'reopened')
    stale = sorted((n for n in tree.nodes.values() if n.kind == 'task' and n.id not in keep[:90]
                    and (store.get(n.id) or {}).get('data', {}).get('status') in live and now - (n.last_time or 0) >= STATUS_REVIEW_H * 3600),
                   key=lambda n: -(n.last_time or 0))[:40]
    payload['status_review'] = [card(n.id) for n in stale]
    out, usage = ask(prompt or PROMPT, payload, model=model, effort=effort, max_out=20000, role='maintain4')
    held = _held_inheritance(store, now)            # what each active executor's task inherits before this run's changes
    applied = apply_ops(store, tree, out.get('ops') or [], now)
    applied += root_checks(store, tree, now)
    # looking back at the structure, not only at the new records
    try:
        if stray_works(tree): applied += assign_goals(store, tree, now, model=model)     # every work under the goal it serves
    except Exception as e:
        store.event('ROOT', 'goals_failed', at=now, source='maintenance', data={'error': str(e)[:200]})
    for par, wd in [k for k in changed_levels(store, tree, keep) if k[0] is not None][:3]:   # levels with new works: parts of one task
        try:
            applied += structure(store, tree, now, model=model, parent=par, trigger='maintenance',
                                 why='works joined this level since its last structure judgment')
        except Exception as e:
            store.event('ROOT', 'structure_failed', at=now, source='maintenance', data={'level': [par, wd], 'error': str(e)[:200]})
    _notify_inheritance(store, tree, held, now)
    store.event('ROOT', 'maintenance', at=now, source='maintenance', data={'ops': len(applied), 'window': len(window)})
    return applied, usage


def _held_inheritance(store, at):
    """Active executors and the constraints their task inherits now (concept 3.4: a change of the tree tells the affected
    executors how their inherited constraints changed)."""
    out = {}
    for (rid, data, node) in store.db.execute("select i.id, i.data, e.dst from items i join edges e on e.src=i.id and e.rel='serves' "
                                              "and e.valid_to is null where i.type='run'"):
        d = json.loads(data) if isinstance(data, str) else (data or {})
        if d.get('status') == 'active' and d.get('mode') in ('session', None):
            out[rid] = (node, _inheritance(store, node, at))
    return out


def _notify_inheritance(store, tree, held, now):
    from . import execution as X
    for rid, (node, before) in held.items():
        n = tree.resolve(node) or node
        after = _inheritance(store, n, now)
        added, removed = after - before, before - after
        if not (added or removed): continue
        st = lambda ids: '; '.join((store.get(c) or {}).get('data', {}).get('statement', '')[:120] for c in sorted(ids))
        text = ('Maintenance adjusted the task tree; the constraints this task inherits changed' + (f'. It is now under "{tree.nodes[tree.nodes[n].parent].title}"' if n in tree.nodes and tree.nodes[n].parent in tree.nodes else '')
                + (f'. Now applies: {st(added)}' if added else '') + (f'. No longer applies: {st(removed)}' if removed else ''))
        nid = store.add('notice', {'text': text, 'added': sorted(added), 'removed': sorted(removed)}, at=now, source='maintenance')
        X.forward(store, run_id=rid, item_id=nid, at=now, why='inherited constraints changed after a tree adjustment')


def _edited_ok(store, node, evidence_turns):
    """A user-edited node may be changed directly only with the user's later evidence (turns after the edit)."""
    if not UI.user_edited(store, node): return True
    edit_at = store.db.execute("select max(at) from events where item=? and kind='ui_edit'", (node,)).fetchone()[0]
    ev = [t for t in evidence_turns or [] if isinstance(t, int)]
    return any(store.db.execute("select 1 from items where type='turn' and turn=? and at > ?", (t, edit_at)).fetchone() for t in ev)


def _inheritance(store, node, at):
    out = set()
    for n in [node] + store.ancestors(node, at) + ['ROOT']:
        out |= {r['id'] for r in store.items('constraint', about=n, at=at, current_only=True)}
    return out


def apply_ops(store, tree, ops, now):
    applied = []
    for op in ops:
        kind = op.get('op')
        nodes = [op.get(k) for k in ('node', 'drop', 'keep') if op.get(k)] + list(op.get('children') or [])
        blocked = [n for n in nodes if n in tree.nodes and not _edited_ok(store, n, op.get('evidence_turns'))]
        if blocked:
            pid = store.add('pending', {'kind': 'maintenance_proposal', 'op': op, 'status': 'open', 'what': op.get('why')}, at=now, source='maintenance')
            store.link(pid, 'about', blocked[0], at=now, source='maintenance')
            applied.append(dict(op, proposal=pid)); continue
        if kind in ('set_parent', 'create_goal', 'create_parent', 'merge', 'rename'):
            moved = [op.get('node')] if kind == 'set_parent' else list(op.get('children') or [])
            before = {n: _inheritance(store, n, now) for n in moved if n in tree.nodes}
            res = _apply(tree, [op])
            for n, b in before.items():
                a = _inheritance(store, n, now + 1e-6)
                if a != b:
                    store.event(n, 'inheritance_change', at=now, source='maintenance', data={'gained': sorted(a - b), 'lost': sorted(b - a)})
            applied += res
        elif kind == 'add_dep' and op.get('before') in tree.nodes and op.get('after') in tree.nodes and op['before'] != op['after']:
            L.add_dep(store, op['before'], op['after'], at=now, source='maintenance', kind=op.get('type') or 'serial'); applied.append(op)
        elif kind == 'set_status' and op.get('node') in tree.nodes and op.get('evidence_turns'):
            if L.set_status(store, op['node'], op.get('status'), at=now, source='maintenance', reason=op.get('why', '')):
                applied.append(op)
        elif kind == 'lift_constraint' and op.get('constraint') and store.get(op['constraint']) and op.get('to') in tree.nodes:
            from . import scope
            c, to = op['constraint'], op['to']
            olds = [o for o in store.about(c, now) if o != 'ROOT']
            if olds and all(to in store.ancestors(o, now) for o in olds):
                scope.lift(store, c, to, at=now, why=op.get('why', ''), source='maintenance'); applied.append(op)
        elif kind == 'lower_constraint' and op.get('constraint') and store.get(op['constraint']) and op.get('nodes'):
            from . import scope
            c = op['constraint']; olds = store.about(c, now)
            nodes = [n for n in op['nodes'] if n in tree.nodes and any(o in store.ancestors(n, now) for o in olds)]
            if nodes:
                scope.lower(store, c, nodes, at=now, why=op.get('why', '')); applied.append(op)
        elif kind == 'propose_object_constraint' and op.get('constraints'):
            pid = store.add('pending', {'kind': 'proposed_object_constraint', 'constraints': op['constraints'], 'object': op.get('object'),
                                        'what': op.get('why'), 'status': 'open'}, at=now, source='maintenance')
            store.link(pid, 'about', 'ROOT', at=now, source='maintenance'); applied.append(op)
        elif kind == 'link_overall_goal' and op.get('goal') in tree.nodes and store.get(op.get('overall_goal') or '')                 and store.get(op['overall_goal'])['type'] == 'overall_goal':
            store.link(op['goal'], 'serves_goal', op['overall_goal'], at=now, source='maintenance'); applied.append(op)
        elif kind == 'tidy_document' and op.get('documents'):
            docs = [d for d in op['documents'] if (store.get(d) or {}).get('type') == 'document']
            if docs:
                pid = store.add('pending', {'kind': 'document_tidy', 'status': 'open', 'documents': docs, 'action': op.get('action'), 'what': op.get('why')},
                                at=now, source='maintenance')
                store.link(pid, 'about', (store.about(docs[0]) or ['ROOT'])[0], at=now, source='maintenance'); applied.append(op)
        elif kind in ('move_messages', 'split') and op.get('turns'):
            to = op.get('to') if kind == 'move_messages' else None
            if kind == 'split' and op.get('node') in tree.nodes and op.get('title'):
                par = op.get('parent') if op.get('parent') in tree.nodes else None
                first = min(t for t in op['turns'] if isinstance(t, int)) if any(isinstance(t, int) for t in op['turns']) else 0
                to = tree.add(op['title'][:60], op.get('purpose') or '', par, None, first, now, source='maintenance',
                              working_dir=tree.nodes[op['node']].working_dir)
                L.set_status(store, to, 'running', at=now, source='maintenance', reason=op.get('why', ''))
            if to in tree.nodes:
                moved = move_turns(store, tree, [t for t in op['turns'] if isinstance(t, int)], to, at=now, why=op.get('why', ''))
                if moved: applied.append(dict(op, to=to, moved=moved))
        elif kind == 'attach_research' and (store.get(op.get('research') or '') or {}).get('type') == 'research' and op.get('parent') in tree.nodes:
            attach_research(store, tree, op['research'], op['parent'], at=now, why=op.get('why', '')); applied.append(op)
        elif kind == 'add_understanding' and op.get('text'):
            R.add_understanding(store, op['text'], evidence=op.get('evidence_turns'), confidence=op.get('confidence'), at=now, source='ctm')
            applied.append(op)
    return applied


STALE_GOAL_DAYS = 14


def root_checks(store, tree, now):
    """Root stability (3.3): the understanding of the user stays within its size limit (CTM proposes merging or dropping
    low-confidence entries); an overall goal with no related activity for long is put to the user for confirmation, never
    rewritten by CTM."""
    out = []
    if R.understanding_text(store, now)['over_limit'] and not [p for p in store.items('pending', about='ROOT', at=now)
                                                               if p['data'].get('kind') == 'trim_understanding' and p['data'].get('status') == 'open']:
        pid = store.add('pending', {'kind': 'trim_understanding', 'status': 'open', 'what': 'The understanding of the user is over its length limit: I suggest merging entries or dropping the least certain ones.'}, at=now, source='maintenance')
        store.link(pid, 'about', 'ROOT', at=now, source='maintenance'); out.append({'op': 'trim_understanding', 'proposal': pid})
    since = now - STALE_GOAL_DAYS * 86400
    for g in store.items('overall_goal', at=now, current_only=True):
        if g['at'] > since: continue
        goals = [x for (x,) in store.db.execute("select src from edges where rel='serves_goal' and dst=?", (g['id'],)).fetchall()]
        sub = set()
        for x in goals:
            todo = [x]
            while todo:
                y = todo.pop(); sub.add(y); todo += store.children(y, now)
        active = any(store.db.execute("select 1 from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? where i.type='segment' and i.at > ? limit 1",
                                      (y, since)).fetchone() for y in sub)
        asked = store.db.execute("select 1 from events where item=? and kind='confirm_asked' and at > ?", (g['id'], since)).fetchone()
        if not active and not asked:
            pid = store.add('pending', {'kind': 'confirm_overall_goal', 'status': 'open', 'what': f"The overall goal \"{g['data'].get('text', '')}\" has had no work recently. Does it still hold?"},
                            at=now, source='maintenance')
            store.link(pid, 'about', 'ROOT', at=now, source='maintenance'); store.event(g['id'], 'confirm_asked', at=now, source='maintenance')
            out.append({'op': 'confirm_overall_goal', 'proposal': pid})
    return out


def attach_research(store, tree, rid, parent, *, at, why=''):
    """A research item turned out to be part of a work: it becomes a task node under that work; its messages, requirements,
    progress, documents and executor move with it."""
    r = store.get(rid)
    nid = tree.add(r['data'].get('title') or rid, 'Research: ' + (r['data'].get('title') or ''), parent, None, r['turn'] or 0, at, source='maintenance')
    for typ in ('segment', 'constraint', 'guidance', 'progress', 'document', 'decision', 'mention'):
        for x in store.items(typ, about=rid, at=at):
            store.unlink(x['id'], 'about', rid, at=at); store.link(x['id'], 'about', nid, at=at, source='maintenance')
    for (run,) in store.db.execute("select src from edges where rel='serves' and dst=? and valid_to is null", (rid,)).fetchall():
        store.unlink(run, 'serves', rid, at=at); store.link(run, 'serves', nid, at=at, source='maintenance')
        if (store.get(run) or {}).get('data', {}).get('mode') == 'research': store.patch(run, {'mode': 'session'}, at=at, source='maintenance')
    store.link(rid, 'became', nid, at=at, source='maintenance')
    store.patch(rid, {'status': 'attached'}, at=at, source='maintenance', reason=why)
    return nid


def move_turns(store, tree, turns, to, *, at, why=''):
    """Maintenance moves messages to the work they belong to: each message's segments and what was written from it (constraints,
    decisions, guidance, mentions, the run summary and query records of that turn) follow it. Segments the user re-attached in the
    UI stay. Returns the turns moved."""
    moved, last = [], None
    for t in turns:
        segs = [r for r in store.items('segment', at=at) if r['turn'] == t]
        for sg in segs:
            if store.db.execute("select 1 from events where kind='ui_edit' and data like ? limit 1", (f'%"segment": "{sg["id"]}"%',)).fetchone():
                continue
            olds = [o for o in store.about(sg['id'], at) if o in tree.nodes and o != to]
            if not olds: continue
            for o in olds: store.unlink(sg['id'], 'about', o, at=at)
            store.link(sg['id'], 'about', to, at=at, source='maintenance')
            for typ in ('constraint', 'decision', 'guidance', 'mention', 'progress', 'query'):
                for o in olds:
                    for r in store.items(typ, about=o, at=at):
                        if r['turn'] == t:
                            store.unlink(r['id'], 'about', o, at=at); store.link(r['id'], 'about', to, at=at, source='maintenance')
            store.event(to, 'move_messages', at=at, source='maintenance', data={'turn': t, 'segment': sg['id'], 'from': olds, 'why': why})
            if t not in moved: moved.append(t)
            last = max(last or 0, sg['at'])
    if moved and last and last > tree.nodes[to].last_time: tree.touch(to, max(moved), last)
    return moved


MAX_LEVEL = 150
MIN_NEW_WORKS = 2


def changed_levels(store, tree, nodes):
    """Levels (parent, working_dir) of the given nodes that gained at least MIN_NEW_WORKS works (new, or moved in) since the
    last structure judgment of that level and have at least 3 works. Bookkeeping only: which levels to look at again; whether
    anything belongs together is the structure judgment's call."""
    last = {}
    for (data, at) in store.db.execute("select data, at from events where item='ROOT' and kind='structure'"):
        d = json.loads(data) if isinstance(data, str) else (data or {})
        key = (d.get('parent'), None)
        last[key] = max(last.get(key, -1.0), at)
    out = []
    for key in dict.fromkeys(level_of(tree, n) for n in nodes if n in tree.nodes):
        ids = level_works(tree, key[0], key[1])
        if len(ids) < 3: continue
        since = last.get(key, -1.0)
        new = sum(1 for i in ids if (store.get(i) or {}).get('at', 0) > since or store.db.execute(
            "select 1 from edges where rel='child' and dst=? and at > ? limit 1", (i, since)).fetchone())
        if new >= MIN_NEW_WORKS: out.append(key)
    return out


def tree_shape(tree):
    """Root-level works per working directory, the largest number of children, and the depth distribution."""
    from collections import Counter
    kids = Counter(n.parent for n in tree.nodes.values() if n.parent in tree.nodes)
    def depth(n):
        d, seen = 0, set()
        while tree.nodes[n].parent in tree.nodes and n not in seen: seen.add(n); n = tree.nodes[n].parent; d += 1
        return d
    tops = Counter(wd_key(n.working_dir) for n in tree.nodes.values() if n.parent not in tree.nodes)
    return {'nodes': len(tree.nodes), 'top_level': sum(tops.values()), 'top_level_by_dir': dict(tops.most_common(12)),
            'max_children': max(kids.values()) if kids else 0, 'depth': dict(sorted(Counter(depth(n) for n in tree.nodes).items()))}


def wd_key(wd):
    """One spelling of a working directory (case, slash direction, trailing slash) so a project is one root level."""
    return (wd or '').replace(chr(92), '/').rstrip('/').lower()


def level_of(tree, node):
    """The level a node sits on: (parent, None); the root is one level for all goals (a goal may span directories)."""
    n = tree.nodes[node]
    return (n.parent if n.parent in tree.nodes else None, None)


def level_works(tree, parent, working_dir):
    if parent is not None:
        ids = [n.id for n in tree.nodes.values() if n.parent == parent]
    elif working_dir is not None:                      # one project's root works (the import's organize, kept for comparison)
        ids = [n.id for n in tree.nodes.values() if n.parent not in tree.nodes and wd_key(n.working_dir) == wd_key(working_dir)]
    else:
        ids = [n.id for n in tree.nodes.values() if n.parent not in tree.nodes]
    return sorted(ids, key=lambda x: (tree.nodes[x].created_turn or 0, x))


def raised_during(store, tree, n):
    """The title of the work the user was doing when this one was raised (recorded at creation), if it is still in the tree."""
    r = store.get(n)
    w = (r or {}).get('data', {}).get('raised_during')
    return tree.nodes[w].title if w in tree.nodes and w != n else None


def work_card(store, tree, n, now):
    import datetime
    r = store.db.execute("select min(i.at), max(i.at), count(*) from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? "
                         "where i.type='segment'", (n,)).fetchone()
    fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d') if t else None
    kids = [c.id for c in tree.nodes.values() if c.parent == n]
    last = store.db.execute("select i.data from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? where i.type='progress' "
                            "order by i.at desc limit 1", (n,)).fetchone()
    done = (json.loads(last[0]).get('done') or '')[:200] if last else ''
    return {'id': n, 'title': tree.nodes[n].title, 'purpose': (tree.nodes[n].purpose or '')[:200], 'from': fmt(r[0]), 'to': fmt(r[1]),
            'messages': r[2] or 0, 'status': L.status(store, n), 'n_children': len(kids),
            'children': [tree.nodes[c].title for c in kids[:8]], 'last_result': done, 'user_edited': UI.user_edited(store, n),
            'working_dir': wd_key(tree.nodes[n].working_dir) if tree.nodes[n].working_dir else '', 'raised_during': raised_during(store, tree, n)}


def structure_payload(store, tree, now, *, parent=None, working_dir=None, trigger='maintenance', focus=(), why=''):
    ids = level_works(tree, parent, working_dir)
    if len(ids) > MAX_LEVEL:                              # keep the focus and the most recent ones
        rest = [i for i in ids if i not in focus]
        ids = [i for i in ids if i in focus] + rest[-(MAX_LEVEL - len([i for i in ids if i in focus])):]
    lvl = {'parent': {'id': parent, 'title': tree.nodes[parent].title, 'purpose': tree.nodes[parent].purpose} if parent else None,
           'project': None if parent else (working_dir or '(no directory)')}
    return ids, {'trigger': trigger, 'why': why, 'level': lvl, 'focus': [f for f in focus if f in ids],
                 'works': [work_card(store, tree, n, now) for n in ids]}


def apply_structure(store, tree, out, ids, now, *, parent=None, working_dir=None, trigger='maintenance', focus=(), why=''):
    """Apply the judgment's groups within the level. Code only checks what keeps the tree valid: the ids are of this level,
    user-edited works stay, no cycle; a judgment triggered by a new work only changes groups involving it."""
    level = set(ids); focus = set(focus)
    movable = lambda n: n in tree.nodes and _edited_ok(store, n, None)
    on_level = lambda n: n in tree.nodes and n in level and (tree.nodes[n].parent == parent if parent else tree.nodes[n].parent not in tree.nodes)
    applied, moved = [], set()
    for g in (out or {}).get('groups') or []:
        if not isinstance(g, dict) or not (g.get('title') or '').strip(): continue
        ch = [c for c in dict.fromkeys(g.get('children') or []) if isinstance(c, str) and on_level(c) and movable(c) and c not in moved]
        if len(ch) < 2 or (trigger == 'new_work' and not focus & set(ch)): continue
        title = g['title'].strip()[:40]
        same = [c for c in ch if tree.nodes[c].title == title]
        if same:                                          # titled like one of the works: that work is the larger one
            gid = same[0]; ch = [c for c in ch if c != gid]
        else:
            first = min(ch, key=lambda c: (tree.nodes[c].created_turn or 0, c))
            gid = tree.add(title, (g.get('purpose') or '').strip(), parent, None, tree.nodes[first].created_turn or 0, now,
                           working_dir=tree.nodes[first].working_dir, source='maintenance')
            L.set_status(store, gid, 'running', at=now, source='maintenance', reason='structure judgment')
        for c in ch:
            if not _creates_cycle(tree, c, gid):
                tree.set_parent(c, gid, at=now, source='maintenance', reason='structure judgment: ' + (g.get('why') or '')[:100]); moved.add(c)
        _parent_status(store, gid, now + 1e-3)
        applied.append({'op': 'group' if not same else 'group_under', 'node': gid, 'title': title, 'children': ch, 'why': g.get('why')})
    store.event('ROOT', 'structure', at=now, source='maintenance',
                data={'trigger': trigger, 'why': why, 'parent': parent, 'working_dir': working_dir, 'focus': sorted(focus), 'ops': applied})
    return applied


def structure(store, tree, now, *, model, parent=None, working_dir=None, trigger='maintenance', focus=(), why='', ask_fn=None):
    """One structure judgment over one level (signalled by delivery or maintenance). Returns the applied operations."""
    ids, payload = structure_payload(store, tree, now, parent=parent, working_dir=working_dir, trigger=trigger, focus=focus, why=why)
    if len(ids) < 2: return []
    out, _ = (ask_fn or ask)(STRUCTURE, payload, model=model, effort='medium', max_out=20000, role='structure')
    return apply_structure(store, tree, out, ids, now, parent=parent, working_dir=working_dir, trigger=trigger, focus=focus, why=why)


def _parent_status(store, gid, at):
    sts = [L.status(store, c) for c in store.children(gid, at)]
    new = 'reported_done' if sts and all(x in L.FINISHED for x in sts) else 'running' if 'running' in sts else 'paused'
    if L.status(store, gid) != new: L.set_status(store, gid, new, at=at, source='maintenance', reason='by the status of the works below')


GOAL_BATCH = 80


def goal_card(store, tree, g):
    kids = [c for c in tree.nodes.values() if c.parent == g]
    sub, todo = [], list(kids)
    while todo:
        c = todo.pop(); sub.append(c); todo += [x for x in tree.nodes.values() if x.parent == c.id]
    return {'id': g, 'title': tree.nodes[g].title, 'purpose': (tree.nodes[g].purpose or '')[:160], 'n_works': len(kids),
            'recent_works': [c.title for c in sorted(kids, key=lambda c: -(c.last_time or 0))[:6]],
            'working_dirs': sorted({wd_key(c.working_dir) for c in sub if c.working_dir})[:4]}


def stray_works(tree):
    """Works at the root that are not goals (they still need the goal they serve), oldest first."""
    return [n.id for n in sorted(tree.nodes.values(), key=lambda x: (x.created_turn or 0, x.id))
            if n.parent not in tree.nodes and n.kind != 'goal']


def assign_goals(store, tree, now, *, model, works=None, batch=GOAL_BATCH, why='', ask_fn=None):
    """Put works that are not under a goal under the goal they serve (concept 3.4). Returns the applied operations."""
    todo = stray_works(tree) if works is None else list(works)
    applied = []
    for i in range(0, len(todo), batch):
        chunk = [w for w in todo[i:i + batch] if w in tree.nodes and tree.nodes[w].parent not in tree.nodes and tree.nodes[w].kind != 'goal']
        if not chunk: continue
        goals = sorted([n.id for n in tree.nodes.values() if n.kind == 'goal'], key=lambda g: -(tree.nodes[g].last_time or 0))
        cards = []
        for w in chunk:
            c = work_card(store, tree, w, now); c.pop('user_edited', None); cards.append(c)
        payload = {'goals': [goal_card(store, tree, g) for g in goals[:150]], 'works': cards}
        out, _ = (ask_fn or ask)(GOALS, payload, model=model, effort='medium', max_out=20000, role='goals')
        out = out if isinstance(out, dict) else {}
        keymap = {}
        for g in out.get('new_goals') or []:
            if not isinstance(g, dict) or not (g.get('title') or '').strip() or not g.get('key'): continue
            members = [a.get('work') for a in out.get('assign') or [] if isinstance(a, dict) and a.get('goal') == g['key'] and a.get('work') in tree.nodes]
            if not members: continue
            first = min(members, key=lambda w: (tree.nodes[w].created_turn or 0, w))
            gid = tree.add(g['title'].strip()[:40], (g.get('purpose') or '').strip(), None, None, tree.nodes[first].created_turn or 0, now,
                           kind='goal', working_dir='', source='maintenance')
            store.patch(gid, {'summarized': True}, at=now, source='maintenance')        # CTM summarized it; the user may change it
            L.set_status(store, gid, 'running', at=now, source='maintenance', reason='goal')
            keymap[g['key']] = gid
            applied.append({'op': 'new_goal', 'node': gid, 'title': g['title'], 'why': g.get('why')})
        for a in out.get('assign') or []:
            if not isinstance(a, dict): continue
            w, g = a.get('work'), a.get('goal')
            g = keymap.get(g) or (tree.resolve(g) if isinstance(g, str) else None)
            if w not in chunk or g not in tree.nodes or tree.nodes[g].kind != 'goal': continue
            if not _edited_ok(store, w, None) or _creates_cycle(tree, w, g): continue
            tree.set_parent(w, g, at=now, source='maintenance', reason='under the goal it serves' + ((': ' + why) if why else ''))
            applied.append({'op': 'to_goal', 'node': w, 'goal': g})
        for pair in out.get('merge_goals') or []:
            if not (isinstance(pair, list) and len(pair) >= 2): continue
            keep = tree.resolve(pair[0])
            for drop in pair[1:]:
                drop = tree.resolve(drop)
                if keep in tree.nodes and drop in tree.nodes and keep != drop and tree.nodes[keep].kind == 'goal' and tree.nodes[drop].kind == 'goal' \
                        and _edited_ok(store, drop, None):
                    tree.merge(keep, drop, at=now, source='maintenance', reason='the same long-term goal')
                    applied.append({'op': 'merge_goals', 'keep': keep, 'drop': drop})
    store.event('ROOT', 'goals', at=now, source='maintenance', data={'ops': applied, 'works': len(todo)})
    return applied


RECLASS_GUIDANCE = '''You are checking what CTM recorded as "guidance". CTM gives the user's requirements to executors in two kinds: a constraint is a limit this work must respect or a step it must take (scope, method, format, confirm before acting),
which the executor follows and stops to ask about before going against it; guidance is advice on approach and plan (what to refer to, what to watch for, how to do it better), which the executor considers, not a hard limit.
The cost of the wrong kind: a hard requirement of the user recorded as guidance may not be followed - the executor acts where it should have asked the user first, deletes what should have been kept; advice recorded as a constraint restricts the executor needlessly.
Each item below is one sentence CTM recorded as guidance (statement), with the user's words at the time (user_words) and the work being done then. First analyse whether the user's words require the executor to do it this way (or forbid another way),
or advise it to consider this; then judge. Output JSON only: {"items":[{"id":"GU1","analysis":"..","class":"guidance|constraint"}]}'''


def reclassify_guidance(store, items, *, model, apply=False, at=None, batch=20):
    """Imported guidance that is really a hard requirement becomes a constraint on the same work (a new constraint replaces the
    guidance item, so the history stays). items: [{'id','statement','user_words','work'}]. Returns {id: class}."""
    out_all = {}
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        out, _ = ask(RECLASS_GUIDANCE, {'items': chunk}, model=model, effort='medium', max_out=12000, role='reclass-guidance')
        for x in out.get('items') or []:
            if isinstance(x, dict) and x.get('id') in {c['id'] for c in chunk}: out_all[x['id']] = x.get('class')
    if apply:
        at = at if at is not None else time.time()
        for gid, cls in out_all.items():
            g = store.get(gid)
            if cls != 'constraint' or not g or g['replaced_at'] is not None: continue
            cid = store.add('constraint', {'statement': g['data'].get('statement'), 'kind': 'task', 'from_guidance': gid}, at=at, source='maintenance', turn=g['turn'])
            for n in store.about(gid): store.link(cid, 'about', n, at=at, source='maintenance')
            store.replace(gid, cid, at=at, source='maintenance')
            store.event(cid, 'reclassified', at=at, source='maintenance', data={'from': 'guidance', 'guidance': gid})
    return out_all


# Tree operations shared with the structure judgments (formerly in the superseded maintain.py)
def _apply(tree, ops):
    applied = []
    for op in ops:
        kind = op.get('op')
        if kind == 'set_parent' and op.get('node') in tree.nodes and op.get('parent') in tree.nodes and not _creates_cycle(tree, op['node'], op['parent']):
            tree.set_parent(op['node'], op['parent'], source='maintenance', reason=op.get('why', '')); applied.append(op)
        elif kind in ('propose_parent', 'create_goal', 'create_parent'):
            kids = [c for c in op.get('children') or [] if c in tree.nodes]
            if len(kids) >= (1 if kind == 'create_goal' else 2):
                last = max(tree.nodes[c].last_turn for c in kids)
                when = max(tree.nodes[c].last_time for c in kids)
                parent = op.get('parent') if op.get('parent') in tree.nodes else None
                nid = tree.add(op.get('title') or '', op.get('purpose') or '', parent, None, last, when,
                               kind='goal' if kind == 'create_goal' else 'task', working_dir=tree.nodes[kids[0]].working_dir)
                tree.nodes[nid].proposed = kind == 'propose_parent'
                for c in kids:
                    if not _creates_cycle(tree, c, nid): tree.set_parent(c, nid, source='maintenance', reason=op.get('why', ''))
                applied.append(dict(op, created=nid))
        elif kind == 'merge' and op.get('keep') in tree.nodes and op.get('drop') in tree.nodes and op['keep'] != op['drop']:
            tree.merge(op['keep'], op['drop']); applied.append(op)
        elif kind == 'rename' and op.get('node') in tree.nodes and op.get('title'):
            tree.rename(op['node'], op['title'], source='maintenance', reason=op.get('why', '')); applied.append(op)
    return applied


def _creates_cycle(tree, node, parent):
    p = parent
    while p:
        if p == node: return True
        p = tree.nodes[p].parent if p in tree.nodes else None
    return False
