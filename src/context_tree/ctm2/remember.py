"""Memory (concept model 5.1 step 5): after delivery, record what the message states that later work still needs.

Delivery already decided which work each part of the message went to, so the call sees exactly the items in force on
those works' lines, their objects and the root, and in one pass extracts constraints, guidance, decisions, facts and
behavior guidance, places them and says which current items each new one replaces (3.5, 3.6, section 4).
"""
from .model import ask
from . import documents as D
from . import lifecycle as L
from . import root as R
from .writeback import in_force, object_keys, project_of, _write_fact, ROOT

NL = chr(10)

# 2026-11-18: block B recall and wrong replacements as V5 (two judges); MemoryCode conventions recorded as
PROMPT = '''You are CTM: the assistant between the user and several executor agents. This user message has been delivered (deliveries: which work each part of the original words went to). Now record what in it will keep taking effect later.
What you write is used again and again. First think through how each kind is used and what recording it wrongly costs, then decide which kind it is and where it goes. Record only what the user says in this message; do not extract from the agent's replies, and do not guess what the user did not say.
Stay faithful to the user's words: do not add names, values, reasons, scopes or exclusions the user did not say - executors carry out every record as what the user meant, and anything added becomes a requirement the user never made. Write each statement in the user's own words and language. The user clarifying their own meaning is not the user rejecting what the agent said. Record one thing in one place only, not in two kinds.

Constraints (constraints): limits or rules the work must follow - scope, methods and tools, process and pace, format. CTM attaches a constraint to the work and gives it to every later execution of this work and all its parts; executors must follow it, and a new request contrary to it leads to a confirmation with the user. Recorded as a constraint by mistake: every later execution is restricted by it and the user has to come and lift it; missed: later executions violate it and the user has to say it again.
  Ask yourself: if a later execution of this work went against it, would the user consider that a mistake? If yes, it is a constraint; if the user only wants it considered and the executor may depart from it with good reason, it is guidance.
  Not constraints: the environment and the current state (facts); judgments about causes or directions (decisions); the thing to be done this time, and requests to wrap up or start the next step (the work itself, not recorded); limits that hold only for this message; corrections of an earlier approach (decisions: the corrected approach as rejected, the new one as decision).
  kind: object - a rule that always holds for an object itself and that any later work touching it should follow without being told again (how a file is written, the design of a product, what a test should verify, principles for changing a whole project); CTM writes it next to the object (comments in the object's file, the ctm.md of its directory), where every executor touching the object reads it, and scope names the object - so it is about one concrete object: a file, module, interface or product in a project. A rule about a way of writing all the user's code or all their work, with no concrete object (for example a requirement for every function the user writes), has no file to live in; recorded as object it would reach no executor, so record it as global or task, by the reach of the user's words. task - only about this work's output or approach; it ends with this work. global - a personal preference, prohibition or way of writing that holds for all the user's work. The cost of the wrong kind: an object rule recorded as a task constraint is unknown to other works that touch the object; a task constraint recorded as an object or global constraint restricts unrelated work.
  What the user prescribes for a product (interface and layout, interface and data conventions, defaults, the format and content of an output, how a file is written, what a test should verify) holds as long as the product exists: it is an object constraint, even when said as a choice of approach; once recorded as an object constraint, do not restate it as a decision - only the old approach it replaces gets its own rejected entry.
  validity: work (until this work ends) / long_term.

Guidance (guidance): the user's guidance on approach and plan - what to consider, what to watch for, how to arrange things - that keeps taking effect in later rounds of this work but is not a hard limit. The thing to be done this time is not guidance; an approach for this one request only (what to check first this time, which method, in what order) goes to the executor with the user's words and need not be recorded; it is guidance only when the user wants it considered in later rounds too.
Decisions (decisions): what the user settles, rejects or questions in this message - an approved, chosen or rejected approach, a judgment about a cause or a direction, acceptance of a result, doubt about an agent's conclusion (type: decision / rejected / questioned). A new request itself (what the user wants done this time) is not a decision: only settling something among several approaches, or approving, rejecting or questioning what the agent proposed, is a decision. CTM gives decisions to every later execution of this work, with rejected approaches listed separately as "do not use again"; later "as we decided" and "how did we decide then" are also found through them. The cost of missing one: with another executor or after some time, the executor redoes an approach the user rejected, or asks again about a choice the user already answered, and the user has to say it again; one too many costs only one more record. So whatever the user's words settle, record it.
  Ask yourself: on what does the user take a position in this message (agree, reject, choose, dispose of, accept, correct)? Would a later executor who does not know this go wrong or ask again? First list these positions one by one in your head, then decide what each becomes.
  The user's positions often do not come as statements: rejecting the agent's claim or approach with a rhetorical question or a challenge while saying what to do instead - the rejected one is rejected, the approach given is decision; only questioning the grounds of the agent's conclusion (asking how it knows, on what basis, whether it got it wrong), without saying it is wrong or what to do - record questioned, naming the conclusion questioned, not as a rejection or a prohibition (later executors verify it before using it; once it is confirmed or refuted, the new statement replaces it); disposing of the agent's listed items one by one (do now, only give a plan, later, ignore) - one entry for each item's disposition; confirming that a result is as expected and acceptable - record what is accepted; choosing one of the approaches the agent offered, or rejecting the object, location, name or version the agent used and naming another - record what was chosen. For a short approval such as "ok" or "go ahead", write what is approved (see recent_conversation and open_pending).
Facts (facts): concrete facts needed when the work goes on: environment (environments and addresses), location (file and directory locations), identifier (branches, PR numbers, versions, IDs), procedure (how to run, test, query), state (the current state, volatile), deadline. common is true for an environment shared by several projects. Never write a secret itself, only where it is.
Agent behavior guidance (behavior): how agents should generally do a kind of operation, not limited to this work (ask yourself: in an unrelated work doing the same kind of operation, would the user ask for this too?). Write when it applies. An approach only for this work is its guidance or constraint.
Settings (settings): statements of the overall goals and priorities (overall_goal), requirements for the assistant itself (persona).

Place (node): usually the work this part of the words was delivered to (nodes lists it and the works above it); when the user's words cover a larger scope (from now on, all, the whole feature or project), the work above that is covered; ROOT for what holds for all work. Whatever node it is attached to, it applies to every work under that node: attached too high, it reaches unrelated work; too low, parts that should follow it miss it; when unsure, attach it lower. For a constraint that holds only for part of this work, local_part names that part (CTM makes that part a subtask).
Which earlier items a new item replaces is judged one by one by the next step; do not judge it here.
Each kind is empty when there is none.
Output JSON only: {"constraints":[{"statement":"..","kind":"task|object|global","scope":"..","validity":"work|long_term","node":"N3","local_part":null}],
"guidance":[{"statement":"..","node":"N3"}],"decisions":[{"statement":"..","type":"decision|rejected|questioned","node":"N3"}],
"facts":[{"statement":"..","kind":"..","volatile":false,"common":false,"node":"N3"}],"behavior":[{"statement":"..","use_when":".."}],
"settings":[{"type":"overall_goal|persona","statement":".."}]}'''

# 2026-11-19: on unused data (w1113 r4) agreed wrong 7 -> 3, valid 11 -> 9; no rule or example from errors
REPLACE = '''The new items the user just stated (new) have been recorded; each comes with the current items most similar to it (similar, with id, type and turn). Judge how each new item relates to them:
- replaces: the new item is about the same thing as a current item, and the user changed it - a value, direction, scope, approach or object changed, the user withdrew it, or changed their mind. A replaced item is no longer given to executors, and every sentence in it stops taking effect.
- repeats: the new item only repeats a current item (the same meaning, nothing changed); give that item's id, and the new item is not recorded again.
The two errors cost differently. Judged a replacement by mistake: requirements in the old item that still hold, including the parts the new item does not mention, no longer reach executors until the user notices and says them again. Missed: both items go to executors, the context lists them by time and says the newer one wins, and the executor mostly follows the newer one - a much smaller cost.
So analyse first: which things the old item says, which of them the new item changes, and whether it overturns all of it; whether the new item only adds detail, a requirement on another aspect, a way of carrying out the old one, or a one-off action. A replacement makes every sentence of the old item stop taking effect, so write replaces only when the old item as a whole is changed or withdrawn; when only part of it changes, keep both.
Output JSON only: {"analysis":"..","items":[{"new":0,"replaces":["CO3"],"repeats":null}]}'''


                            # global directly, rules of a project without files kept on its work


def current_items(store, tree, targets, at, working_dir):
    """User-stated items in force on the target works' lines, their objects and the root (oldest first, no duplicates)."""
    keys = object_keys(store, working_dir)
    seen, cur = set(), []
    for n in targets:
        own = [r for typ in ('constraint', 'guidance', 'decision') for r in store.items(typ, about=n, at=at, current_only=True)] \
            if _research(store, n) else []           # a research item's own requirements (it is not on the tree)
        for r in in_force(store, tree, n, at, keys) + own:
            if r['id'] not in seen: seen.add(r['id']); cur.append(r)
    if not targets:      # a message delivered to no work (chat, a side question) can still change a global or object rule
        rows = [r for key in [ROOT, *keys] for r in store.items('constraint', about=key, at=at, current_only=True)]
        rows += store.items('environment', about=ROOT, at=at, current_only=True)
        for r in sorted(rows, key=lambda r: r['at']):
            if r['id'] not in seen and r['source'] == 'user': seen.add(r['id']); cur.append(r)
    return cur


def _research(store, n):
    return isinstance(n, str) and (store.get(n) or {}).get('type') == 'research'


def remember(store, tree, *, message, deliveries, recent, at, working_dir, model, effort='low', pending=None, prompt=None):
    """deliveries: [{'part','node'}] with node a work in the tree or a research item; recent: last turns [{'user','agent_end'}]."""
    research = [d['node'] for d in deliveries if _research(store, d.get('node'))]
    targets = [d['node'] for d in deliveries if d.get('node') in tree.nodes]
    cur = current_items(store, tree, targets + research, at, working_dir)[-60:]
    nodes = [{'id': r, 'title': 'Research: ' + store.get(r)['data'].get('title', '')} for r in research]
    for n in targets:
        for x in [n] + tree.ancestors(n):
            nodes.append({'id': x, 'title': tree.nodes[x].title})
    payload = {'message': message[:6000], 'deliveries': [{'part': (d.get('part') or 'all')[:1500], 'node': d.get('node'),
                                                          'work': tree.path(d['node']) if d.get('node') in tree.nodes else
                                                          ('Research: ' + store.get(d['node'])['data'].get('title', '') if d.get('node') in research else None)}
                                for d in deliveries],
               'nodes': list({x['id']: x for x in nodes}.values()) + [{'id': ROOT, 'title': 'root (all work)'}],
               'current': [{'id': r['id'], 'type': r['type'], 'statement': r['data'].get('statement', ''), 'on': (store.about(r['id'], at) or [ROOT])[0],
                            'turn': r['turn']} for r in cur],
               'recent_conversation': recent, 'open_pending': pending or []}
    payload.pop('current', None)                     # replacements are judged afterwards (check_replacements)
    return ask(prompt or PROMPT, payload, model=model, effort=effort, role='remember'), {r['id'] for r in cur}


# New items carry their polarity like the similar current items (2026-11-24). Without it a rejected approach reads as a
# requirement: when the user restates a rule the executor misread, the rejected misreading 'contradicts' the rule and replaced
# it (11 of 14 agreed losses on unused data, research/blk3rep; the live case of 11-24 too). On other unused data (blk3pol):
# agreed losses 10 -> 3, right replacements 5 -> 2, misses 5 -> 8 (a miss leaves both items, newest first: the cheaper error).
_MARK = {'rejected': ' (rejected)', 'questioned': ' (questioned)'}


def check_replacements(store, out, *, current, embed, model, effort='low', k=5, prompt=None):
    """Focused replacement judgment (5.1 step 5): every new item against the k current items most similar to it.
    Sets each new item's 'replaces'; items that only repeat a current one are dropped. Returns (out, usage or None)."""
    out = out if isinstance(out, dict) else {}
    new = [(fld, x) for fld in ('constraints', 'guidance', 'decisions') for x in out.get(fld) or [] if x.get('statement')]
    cur = [r for r in current if r['type'] in ('constraint', 'guidance', 'decision') and r['data'].get('statement')]
    if not new or not cur:
        return out, None
    import numpy as np
    m = np.array(embed([r['data']['statement'][:500] for r in cur]), dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    payload = []
    for i, (fld, x) in enumerate(new):
        v = np.asarray(embed([x['statement'][:500]])[0], dtype=np.float32); v /= np.linalg.norm(v) + 1e-9
        top = np.argsort(-(m @ v))[:k]
        mark = _MARK.get(x.get('type'), '') if fld == 'decisions' else ''
        payload.append({'i': i, 'type': {'guidance': 'guidance'}.get(fld, fld[:-1]) + mark, 'statement': x['statement'],
                        'similar': [{'id': cur[t]['id'], 'type': cur[t]['type'] + _MARK.get(cur[t]['data'].get('type'), ''),
                                     'statement': cur[t]['data']['statement'], 'turn': cur[t]['turn']} for t in top]})
    res, usage = ask(prompt or REPLACE, {'new': payload}, model=model, effort=effort, role='replace')
    def _idx(v):
        try: return int(v)
        except (TypeError, ValueError): return None
    by = {_idx(r.get('new')): r for r in (res.get('items') or []) if isinstance(r, dict)}
    allowed = {c['id'] for p in payload for c in p['similar']}
    keep = {fld: [] for fld in ('constraints', 'guidance', 'decisions')}
    curd = {r['id']: r for r in cur}
    for i, (fld, x) in enumerate(new):
        r = by.get(i) or {}
        rep = r.get('repeats')
        rep = (rep[0] if rep else None) if isinstance(rep, list) else rep          # models sometimes return a list here
        replaces = r.get('replaces') if isinstance(r.get('replaces'), list) else ([r['replaces']] if isinstance(r.get('replaces'), str) else [])
        if isinstance(rep, str) and rep in allowed and not replaces:
            continue
        reps = [c for c in replaces if isinstance(c, str) and c in allowed]
        keep[fld].append(dict(x, replaces=reps))
        rem = r.get('remaining') if isinstance(r.get('remaining'), dict) else {}
        for old_id, text in rem.items():              # the unchanged rest of a partly replaced item stays current
            if old_id in reps and isinstance(text, str) and text.strip() and old_id in curd:
                o = curd[old_id]; ofld = {'constraint': 'constraints', 'guidance': 'guidance', 'decision': 'decisions'}[o['type']]
                keep[ofld].append({'statement': text.strip(), 'node': x.get('node'), 'replaces': [], 'kind': o['data'].get('kind'),
                                   'type': o['data'].get('type'), 'remaining_of': old_id})
    return dict(out, **keep), usage


def write(store, tree, out, *, turn, at, working_dir, model, current_ids, default_node=None):
    """Write the memory call's output: items on their nodes, object rules into the object index, replacements and exceptions."""
    log = {'replaced': [], 'exceptions': [], 'created': [], 'behavior': None}
    out = out if isinstance(out, dict) else {}

    def node_of(x):
        if x.get('node') == ROOT: return ROOT
        if _research(store, x.get('node')): return x['node']          # a research item's own requirement
        n = tree.resolve(x.get('node')) if x.get('node') else None
        return n if n in tree.nodes else (default_node if default_node in tree.nodes or _research(store, default_node) else ROOT)

    def replace(new_id, olds):
        for old in olds or []:
            if old not in current_ids or not store.get(old) or store.get(old)['replaced_at'] is not None: continue
            old_nodes, new_nodes = store.about(old), store.about(new_id)
            if store.get(old)['type'] == 'constraint' and new_nodes and old_nodes and all(
                    o in store.ancestors(nn) for nn in new_nodes for o in old_nodes):
                store.link(new_id, 'exception_of', old, at=at, source='ctm'); log['exceptions'].append((old, new_id)); continue
            store.replace(old, new_id, at=at, source='ctm'); log['replaced'].append((old, new_id))
            if store.get(old)['type'] == 'decision':
                D.mark_stale_on_decision(store, old, at=at)
                L.recheck_on_replaced_decision(store, old, at=at)
    for c in out.get('constraints') or []:
        if not c.get('statement'): continue
        kind = c.get('kind') if c.get('kind') in ('task', 'object', 'global') else 'task'
        stated_kind = kind
        if kind == 'object' and not (working_dir or '').strip():
            # an object rule needs a carrier: executors read object rules from the files of the object's directory; with no project
            # directory there is no file and the rule would reach no executor (MemoryCode 20 sessions, 2026-11-18). It stays on the
            # work it was said for until the object has files (concept 3.5)
            kind = 'task'
        cid = store.add('constraint', {'statement': c['statement'], 'kind': kind, 'scope': c.get('scope'), 'validity': c.get('validity'),
                                       'local_part': c.get('local_part'), **({'stated_kind': stated_kind} if stated_kind != kind else {})},
                        at=at, source='user', turn=turn)
        if kind == 'object':
            D.index_object_constraint(store, constraint=cid, obj=c.get('scope') or project_of(working_dir), working_dir=working_dir, at=at)
        else:
            n = ROOT if kind == 'global' else node_of(c)
            if kind == 'task' and c.get('local_part') and n in tree.nodes:      # a constraint for one part of the work: that part becomes a subtask
                n = tree.add(c['local_part'][:60], c['local_part'], n, None, turn, at, working_dir=working_dir)
                log['created'].append(n)
            store.link(cid, 'about', n, at=at, source='ctm')
        replace(cid, c.get('replaces')); log.setdefault('ids', []).append(cid)
    for g in out.get('guidance') or []:
        if not g.get('statement'): continue
        gid = store.add('guidance', {'statement': g['statement']}, at=at, source='user', turn=turn)
        store.link(gid, 'about', node_of(g), at=at, source='ctm'); replace(gid, g.get('replaces'))
    for d in out.get('decisions') or []:
        if not d.get('statement'): continue
        typ = d.get('type') if d.get('type') in ('decision', 'rejected', 'questioned') else 'decision'
        did = store.add('decision', {'statement': d['statement'], 'type': typ}, at=at, source='user', turn=turn)
        store.link(did, 'about', node_of(d), at=at, source='ctm'); replace(did, d.get('replaces'))
    for f in out.get('facts') or []:
        n = node_of(f)
        _write_fact(store, tree, f, n if n in tree.nodes else None, turn, at, source='user')
    for st in out.get('settings') or []:
        if st.get('type') == 'overall_goal' and st.get('statement'):
            R.add_overall_goal(store, st['statement'], at=at, source='user')
        elif st.get('type') == 'persona' and st.get('statement'):
            old = store.items('persona', at=at, current_only=True)
            pid = store.add('persona', {'text': (old[-1]['data']['text'] + NL if old else '') + st['statement']}, at=at, source='user', turn=turn)
            store.link(pid, 'about', ROOT, at=at, source='ctm')
            if old: store.replace(old[-1]['id'], pid, at=at, source='user')
    if out.get('behavior'):
        log['behavior'] = D.file_behavior(store, out['behavior'], at=at, turn=turn, model=model)
    return log
