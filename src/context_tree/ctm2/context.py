"""Execution context (concept model v2, 5.2 items 2 and 3; implementation plan S5).

A new executor gets an initial context assembled from memory as known at dispatch time, in a fixed order (stable parts first
for prompt caching, this dispatch's parts last). Its scope is the task's own scene: the path from the root to the task (and the
task's own subtree), plus the siblings executed most recently - their results, decisions and recent exchanges, not their
constraints or guidance (constraints on a sibling are isolated from this task on purpose).
  fixed clauses -> task state (path as L1 cards, purpose, working directory and environment, status, pending items, results
  handed over by children and predecessors) -> constraints and decisions in force on the path (root preferences and global
  constraints included; object rules reach the executor through the fixed clause to read annotations and ctm.md) -> guidance
  -> decisions and research used from elsewhere -> replaced or rejected approaches ("do not use") -> documents and files ->
  recent progress -> the task's and its ancestors' recent exchanges in original text -> the recently executed siblings ->
  agent behavior guidance index -> what the user pointed to -> askable items -> the goal: the user's own words for this task.
CTM does not rewrite the user's words, add requirements, or tighten or widen authorization. Persona and CTM's understanding of the
user are never included.
A reused session receives only what is new since the last forward: the user's words, constraints, guidance and decisions on the
path not yet forwarded, approaches replaced or rejected, notices (files changed elsewhere, CTM's answers, moved constraints,
behavior guidance updates) and query conclusions answered in forks of the session, plus what the user pointed to.
A research item (in the query list, not in the tree) gets a research context: its own requirements, earlier conclusions and
exchanges, the work it relates to, the behavior guidance index and the user's words.
"""
import json
import re

from . import documents as D
from . import lifecycle as L

NL = chr(10)
FIXED = '''## Working agreement
- The user's own words decide the goal and the authorization; where they say nothing, keep this task's earlier authorization and the limits still in force, without tightening or loosening them yourself. Irreversible actions such as commit, push, deploy or delete only when the user explicitly asks for them.
- Before changing a file, read and follow the constraint comments in it and every ctm.md on the path from the project root to the file's directory; never delete or edit them. When the user's request this time goes against one of them and the user has not said to change that rule, do not make the change: stop and report the conflict (which rule, which change was asked for) to CTM; the user decides whether it is an exception this time or the rule changes.
- ctm.md is maintained by CTM (object rules recorded on this machine): read only - do not edit, stage or commit it, and do not put it in a PR or push it; if you think an entry is wrong or out of date, say so in your reply.
- When moving, renaming, splitting or deleting a file with constraint comments, move the comments to the new place; list the ones you are unsure still apply in your reply for the user to decide, and do not delete them. When you touch an object named in ctm.md (move, rename, delete), say so in your reply; CTM updates the entries.
- When the user's words this time differ from an earlier task constraint, decision or guidance below, the words this time win (what the user says later replaces what was said earlier): follow them and say so in your reply; stop only for a conflict with the constraint comments or ctm.md above.
- When information is missing, look first in this context, the related documents and files, and the scene; the scene may have been changed by later work, so trust what you actually read. Ask CTM (see the items you can ask about below) only when none of these settles it and a wrong guess would cause rework or an irreversible result: every question interrupts the user, so do not ask what you can find out yourself.
- Do only what the user's words ask: do not add deliverables, steps, checks or obligations of your own, and do not narrow the scope yourself; what you think is needed goes into the open items of your reply for the user to decide.
- Put long content into documents; keep the reply brief: what you did, which files and documents you changed, how it was verified (with traces, or inferred), open questions, what the user needs to decide.
- In documents, keep verified and unverified statements apart and give the grounds of verified ones (command output, file version, test); update knowledge documents section by section, without rewriting the whole; cite decisions by their ids.
- The "constraints and decisions in force" below are authoritative; earlier statements in the exchanges may have been replaced.'''
READONLY = '''- This is a read-only query: only answer the user's question; do not change any file, configuration or external state. If answering needs a change, say so first and do not make it.'''
RESEARCH = '''- This is a research: only read the files and resources of the project, change nothing; write the conclusions (verified and unverified kept apart) into this research's document, and give the main points and the document's location in your reply.'''
# pending items an executor should see (CTM's own proposals to the user - maintenance, preferences, annotations - are not)
EXECUTOR_PENDING = ('decision', 'question', 'out_of_scope', 'ask_user', 'question_to_reply', 'document_tidy')
SIBLINGS = 7          # the recently executed siblings (roughly what a person keeps in mind of the surrounding work)
UNCLES = 3            # and the parent task's recently executed siblings


def _lines(xs):
    return NL.join(f'- {x}' for x in xs) if xs else '- (none)'


def _title(store, n):
    return (store.get(n) or {}).get('data', {}).get('title', n)


def subtree(store, node, at):
    out, todo = [], [node]
    while todo:
        x = todo.pop(); out.append(x); todo += store.children(x, at)
    return out


def _activity(store, nodes, at):
    r = store.db.execute(f"select max(i.at) from items i join edges e on e.src=i.id and e.rel='about' where i.type in ('segment','progress') "
                         f"and i.at <= ? and e.dst in ({','.join('?' * len(nodes))})", (at, *nodes)).fetchone()
    return r[0] or 0


def recent_siblings(store, task, at, k=SIBLINGS):
    """Siblings executed most recently before now (each with its subtree): the scene the task works in. A task directly under
    the root has no siblings in this sense (other top-level works are unrelated)."""
    par = store.parent(task, at)
    if not par: return []
    sibs = [c for c in store.children(par, at) if c != task]
    scored = sorted(((_activity(store, subtree(store, c, at), at), c) for c in sibs), reverse=True)
    return [c for t, c in scored if t > 0][:k]


def recent_uncles(store, task, at, k=UNCLES):
    """The parent task's most recently executed siblings (when the parent itself sits under a work, not directly under the root)."""
    par = store.parent(task, at)
    return recent_siblings(store, par, at, k) if par else []


def task_segments(store, task, turn):
    """The user's own words for this task in this message (segments placed on it), in order."""
    rows = store.db.execute("select i.data from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? "
                            "where i.type='segment' and i.turn=? order by i.id", (task, turn)).fetchall()
    return [json.loads(r[0]).get('text', '') for r in rows]


def user_points(store, turn):
    """What the user pointed to in the previous reply or in displayed items (stored with the turn)."""
    r = store.db.execute("select data from items where type='turn' and turn=? limit 1", (turn,)).fetchone()
    return [p for p in (json.loads(r[0]).get('points') or [] if r else []) if p]


RECENT_CONVERSATION = 6     # block D: last turns of the conversation (any work) in a new executor's context
BUDGET = 32000              # 2026-11-19 (was 24000; with progress V4 the farthest sibling exchanges were cut) characters of a new executor's initial context; above it the farthest parts go to lower resolution
                            # (block D: no loss at 24k on t1, a drop at 16k; most labeled contexts are below both)


def conversation_turns(store, before, k=RECENT_CONVERSATION):
    """The conversation's last k user turns before this one, old to new."""
    rows = store.db.execute("select distinct turn from items where type='turn' and source='user' and turn < ? order by turn desc limit ?", (before, k)).fetchall()
    return sorted(r[0] for r in rows)


def _turns(store, nodes, before):
    return sorted({r[0] for n in nodes for r in store.db.execute(
        "select i.turn from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? where i.type='segment' and i.turn < ?", (n, before)).fetchall()})


def _complete(store, i, thread_text, ulen=2000, alen=1500):
    """Whether turn i shown at this size carries everything: a reply was kept and neither side is clipped."""
    u, a = thread_text(i) if thread_text else _stored_exchange(store, i)
    return bool((a or '').strip()) and len(u or '') <= ulen and len(a or '') <= alen


_HEADING = re.compile(r'(?m)^([ 	]*)(#{1,6})(?=[ 	])')


def _flat(text):
    """Raw text quoted into the context (user words, executor replies) keeps its markdown headings from opening sections of
    the context: '## Please confirm' inside a quoted reply read as CTM's own section (2026-11-20)."""
    return _HEADING.sub(lambda m: m.group(1) + chr(92) + m.group(2), text or '')


def _exchange(store, i, thread_text, ulen=2000, alen=1500):
    u, a = thread_text(i) if thread_text else _stored_exchange(store, i)
    return f"[turn {i}][user]{_flat((u or '')[:ulen])}" + NL + f"[executor reply, end]{_flat((a or '')[-alen:])}"


def _progress_line(r):
    d = r['data']
    if d.get('note'): return f"[turn {r['turn']}, then, the user's note]{d['note']}"
    return (f"[turn {r['turn']}, then]{d.get('done', '')}; changed: {', '.join(d.get('changed') or []) or 'none'}; verified: {d.get('verified') or 'not stated'}"
            f"; open: {'; '.join(d.get('open') or []) or 'none'}" + (f"; failed: {'; '.join(d['failed'])}" if d.get('failed') else ''))


def _used(store, task, at):
    used = []
    for (x, d) in store.db.execute("select dst, data from edges where src=? and rel='uses' and at <= ? and valid_to is null", (task, at)).fetchall():
        r = store.get(x)
        if not r: continue
        if r['type'] == 'decision':
            cur = r if r['replaced_at'] is None or r['replaced_at'] > at else store.get(r['replaced_by'])
            used.append(f"[turn {cur['turn']}, from \"{_title(store, (store.about(cur['id']) or [''])[0])}\"]{cur['data'].get('statement', '')}")
        elif r['type'] == 'query':
            used.append(f"[turn {r['turn']}, query result] Q: {r['data'].get('question', '')[:200]} A: {(r['data'].get('answer') or '(see the execution record)')[:600]}")
        elif r['type'] == 'research':
            used.append(f"Conclusions of the research \"{r['data'].get('title', '')}\": {research_summary(store, x, at)[:800]} (document {r['data'].get('doc') or ''})")
        elif r['type'] in ('task', 'goal'):
            recent = store.items('progress', about=x, at=at)[-2:]
            used.append(f"Results of the work \"{r['data'].get('title', '')}\": {'; '.join(p['data'].get('done', '') or p['data'].get('note', '') for p in recent)}")
    return used


def _facts(store, nodes, at):
    """Environment and location facts in force on these works (the scene; unlike constraints they are not isolated)."""
    rows = sorted((r for n in nodes for r in store.items('environment', about=n, at=at, current_only=True)), key=lambda r: r['at'])
    return [(f"[turn {r['turn']}]" if r['turn'] is not None else '') + (r['data'].get('statement') or '') for r in rows]


def _asked(store, nodes, at):
    """Answered queries the user asked about this work (or the work above it): their conclusions are knowledge about it."""
    rows = sorted((r for n in nodes for r in store.items('query', about=n, at=at) if r['data'].get('answered')), key=lambda r: r['at'])
    return [f"[turn {r['turn']}] Q: {r['data'].get('question', '')[:200]} A: {(r['data'].get('answer') or '')[:400]}" for r in rows]


def _gone(store, nodes, at, since=None):
    gone = []
    for n in nodes:
        for typ in ('constraint', 'decision', 'environment', 'guidance'):
            for r in store.items(typ, about=n, at=at):
                if r['replaced_at'] is not None and r['replaced_at'] <= at and (since is None or r['replaced_at'] >= since):
                    new = store.get(r['replaced_by'])
                    gone.append((r['replaced_at'], f"[turn {r['turn']}]{r['data'].get('statement', '')} -> replaced in [turn {new['turn']}] by: {new['data'].get('statement', '')}"))
                elif typ == 'decision' and r['data'].get('type') == 'rejected' and (since is None or since <= r['at'] < at):
                    gone.append((r['at'], f"[turn {r['turn']}]rejected: {r['data'].get('statement', '')}"))
    return [g for _, g in sorted(gone)]


def initial_context(store, task, *, turn, at, message, thread_turns=6, thread_text=None, readonly=False):
    """A new executor's context: the task's path and subtree plus the recently executed siblings (concept 5.2).
    thread_text(turn) -> (user words, executor reply end) for original-text exchanges; defaults to stored turn/run text."""
    at_ = at          # memory as known at dispatch: this message's own write-back is included; the thread stops before this turn
    w = (store.get(task) or {}).get('data', {})
    path = [task] + store.ancestors(task, at_)
    own = list(dict.fromkeys(subtree(store, task, at_) + path))          # the task, its subtree and its ancestors
    sibs = recent_siblings(store, task, at_) + recent_uncles(store, task, at_)
    sib_nodes = [n for s in sibs for n in subtree(store, s, at_)]
    cards = [f"{_title(store, n)}: {(store.get(n) or {}).get('data', {}).get('purpose', '')}" for n in reversed(path[1:])]
    env = [(f"[turn {r['turn']}]" if r['turn'] is not None else '') + (r['data'].get('statement') or '')
           for n in path + ['ROOT'] for r in store.items('environment', about=n, at=at_, current_only=True)]
    pend = [f"[turn {r['turn']}]{r['data'].get('what') or r['data'].get('statement', '')}" for r in store.items('pending', about=task, at=at_)
            if r['data'].get('status', 'open') == 'open' and r['data'].get('kind') in EXECUTOR_PENDING]
    results = [f"[turn {r['turn'] or ''}]{r['data'].get('statement', '')}" for r in store.items('result', about=task, at=at_)]
    path_cons = [(n, r) for n in ['ROOT'] + list(reversed(path)) for r in store.items('constraint', about=n, at=at_, current_only=True)]
    excepted = {x for (_, r) in path_cons for (x,) in store.db.execute("select dst from edges where src=? and rel='exception_of' and at <= ?", (r['id'], at_)).fetchall()}
    cons = []
    for n, r in path_cons:
        if r['id'] in excepted: continue                    # overridden on this path by a user-stated exception deeper down
        exc = store.db.execute("select dst from edges where src=? and rel='exception_of'", (r['id'],)).fetchone()
        where = '(global) ' if n == 'ROOT' else ('(' + _title(store, n) + ') ' if n != task else '')
        cons.append(f"[turn {r['turn']}]{where}{r['data'].get('statement', '')}" + (f" (an exception to the constraint above: \"{store.get(exc[0])['data'].get('statement', '')}\")" if exc else ''))
    decs = [f"[turn {r['turn']}]{r['data'].get('statement', '')}" for n in path for r in store.items('decision', about=n, at=at_, current_only=True)
            if r['data'].get('type') not in ('rejected', 'questioned')]
    doubted = [f"[turn {r['turn']}]{r['data'].get('statement', '')}" for n in path for r in store.items('decision', about=n, at=at_, current_only=True)
               if r['data'].get('type') == 'questioned']
    cons += [f"[turn {r['turn']}](only for the part \"{_title(store, c)}\") {r['data'].get('statement', '')}"
             for c in store.children(task, at_) for r in store.items('constraint', about=c, at=at_, current_only=True)]
    for (cid,) in store.db.execute("select dst from edges where src=? and rel='uses' and at <= ? and valid_to is null", (task, at_)).fetchall():
        r = store.get(cid)                            # a sibling's constraint CTM judged to apply here too (scope.inherit_for_new_work)
        if r and r['type'] == 'constraint' and (r['replaced_at'] is None or r['replaced_at'] > at_):
            cons.append(f"[turn {r['turn']}](CTM judges it applies here too; originally a requirement of \"{_title(store, (store.about(cid, at_) or [''])[0])}\") {r['data'].get('statement', '')}")
    guide = [f"[turn {r['turn']}]{'(' + _title(store, n) + ') ' if n != task else ''}{r['data'].get('statement', '')}"
             for n in ['ROOT'] + list(reversed(path)) for r in store.items('guidance', about=n, at=at_, current_only=True)]
    gone = _gone(store, own + sib_nodes, at_)
    docs, files = D.index(store, own + sib_nodes, at_)
    doc_lines = [f"{d['title']} ({d['kind']}; use: {d.get('use_when') or ''}{'; out of date, update it when you use it' if d['stale'] else ''})" for d in docs[-10:]]
    prog_t = [(r['turn'], _progress_line(r)) for r in store.items('progress', about=task, at=at_)]
    prog = [x for _, x in prog_t]
    all_own_turns = _turns(store, own, turn)
    conv_turns = conversation_turns(store, turn, RECENT_CONVERSATION)
    sib_info = []
    sib_prog_t = {}
    for s in sibs:
        sd = (store.get(s) or {}).get('data', {})
        nodes = subtree(store, s, at_)
        sp_t = [(r['turn'], _progress_line(r)) for n in nodes for r in store.items('progress', about=n, at=at_)]
        sp = [x for _, x in sp_t][-2:]
        sdec = [f"[turn {r['turn']}]{r['data'].get('statement', '')}" for n in nodes for r in store.items('decision', about=n, at=at_, current_only=True)
                if r['data'].get('type') not in ('rejected', 'questioned')][-4:]
        sres = [r['data'].get('statement', '') for r in store.items('result', about=s, at=at_)][-2:]
        rel_ = "parent's sibling" if s not in store.children(store.parent(task, at_) or '', at_) else 'sibling'
        sib_info.append((s, sd, nodes, sp, sdec, sres, rel_))
        sib_prog_t[s] = sp_t
    # the nearest sibling: the work this one comes after, else the sibling executed most recently (siblings are ordered by recency)
    nearest = w.get('after') if w.get('after') in sibs else next((x for x in sibs if x in store.children(store.parent(task, at_) or '', at_)), None)
    sib_more = {s_: (_asked(store, nodes, at_), _facts(store, nodes, at_), _turns(store, nodes, turn)) for s_, _, nodes, *_ in sib_info}
    askable = [_title(store, n) for n in path[1:]] + [d['title'] for d in docs[:-10]] + [f"the full progress and execution record of the task \"{w.get('title', '')}\""]
    words = task_segments(store, task, turn) or [message]

    def assemble(lv):
        # resolution by budget (concept 3.2): lv 0 is the full context; each level lowers the farthest parts first --
        # 1 siblings without their exchanges (L1 cards), 2 shorter recent conversation, 3 fewer own exchanges,
        # 4 siblings as handles (L0), 5 fewer recent turns. The task, its constraints and decisions, the user's words stay.
        own_turns = all_own_turns[-(3 if lv >= 3 else thread_turns):]
        thread = [_exchange(store, i, thread_text) for i in own_turns]
        # block D: a new request often builds directly on what was just done in another work (the user alternates works in
        # one conversation); the tree-based scope does not reach it, so the conversation's last turns go in verbatim, marked
        recent_conv = [_exchange(store, i, thread_text, *((600, 400) if lv >= 2 else (1500, 1500)))
                       for i in (conv_turns[-3:] if lv >= 5 else conv_turns) if i not in own_turns]
        sib_parts = []
        for s, sd, nodes, sp, sdec, sres, rel_ in sib_info:
            near = s == nearest
            head = f"### {sd.get('title', s)} ({rel_}{', the step just done' if near and s == w.get('after') else ''}; {L.status(store, s)})"
            asked, facts, sturns = sib_more[s]
            # resolution by distance (concept 3.2): the nearest sibling keeps its original exchanges longest, the others lose them first
            if near:
                n_x, ul, al = ((4, 2000, 2500) if lv < 2 else (2, 1500, 1500) if lv < 4 else (0, 0, 0))
            else:
                n_x, ul, al = ((2, 1000, 800) if lv < 1 else (0, 0, 0))
            if lv >= 4 and not near:
                sib_parts.append(head); continue
            sx_turns = sturns[-n_x:] if n_x else []
            sx = [_exchange(store, i, thread_text, ul, al) for i in sx_turns]
            full = {i for i in sx_turns if _complete(store, i, thread_text, ul, al)}   # concept 3.2: one resolution per turn --
            sp = [x for t_, x in sib_prog_t[s] if t_ not in full][-2:]                 # a turn shown in original text needs no summary
            sib_parts.append(NL.join([head, 'Results and progress:', _lines(sres + sp), 'Decisions made:', _lines(sdec),
                                      'Environment and locations:', _lines(facts[-(8 if near else 4):])]
                                     + (['Questions asked (conclusions):', _lines(asked[-(3 if near else 2):])] if asked and lv < 4 else [])
                                     + ((['Latest exchanges (original text):'] + sx) if sx else [])))
        parts = [FIXED + (NL + READONLY if readonly else ''),
                 '## The task now', f"Task: {' / '.join(_title(store, n) for n in reversed(path))}", f"Purpose: {w.get('purpose', '')}",
                 f"Working directory: {w.get('working_dir', '')}", f"Status: {L.status(store, task)}" + (f"; deadline: {w['deadline']}" if w.get('deadline') else ''),
                 'Works above:', _lines(cards), 'Environment and locations:', _lines(env[-15:]), 'Pending items:', _lines(pend[-8:]), 'Results from predecessors or subtasks:', _lines(results[-8:]),
                 '## Constraints and decisions in force (from global to this task; deeper and newer win)', _lines(cons[-30:] + decs[-20:]),
                 "## The user's guidance on approach and plan (consider it; not a hard limit)", _lines(guide[-12:]),
                 *(['## Conclusions the user questioned, not yet verified (verify before use)', _lines(doubted[-8:])] if doubted else []),
                 '## Decisions, research and results from elsewhere that this work uses', _lines(_used(store, task, at_)[-8:]),
                 '## Queries the user asked about this work (conclusions)', _lines(_asked(store, path, at_)[-3:]),
                 '## Replaced or rejected approaches (do not use again)', _lines(gone[-8:]),
                 '## Related documents (read them yourself or ask CTM when needed)', _lines(doc_lines), '## Files changed by this task and its latest siblings', _lines([f['path'] for f in files[-15:]]),
                 '## Latest progress (brief summaries, each the state at that time)', _lines([x for t_, x in prog_t if not (t_ in set(own_turns) and _complete(store, t_, thread_text))][-5:]),
                 '## Latest exchanges of this task and the works above it (original text, oldest first)'] + (thread or ['- (none)']) + [
                 "## Recently executed sibling tasks and the parent's siblings (the scene; their constraints do not apply to this task)"] + (sib_parts or ['- (none)']) + [
                 '## Agent behavior guidance (read before doing the matching kind of thing)', _lines(D.behavior_index(store, at_)),
                 *(['## The latest turns of the conversation (original text, oldest first; they may belong to other works - use them only to understand what this message refers to; their requirements belong to their own works)'] + recent_conv
                   if recent_conv else []),
                 '## What the user points to this time', _lines(user_points(store, turn)),
                 '## Items you can ask CTM about' + (' (for length, farther works and exchanges are given only as summaries or titles; ask CTM for them when needed)' if lv else ''), _lines(askable),
                 "## The goal: the user's words this time", _flat(NL.join(words))]
        return NL.join(parts)

    text = assemble(0)
    lv = 0
    while BUDGET and len(text) > BUDGET and lv < 5:   # over budget: lower the resolution of the farthest parts first
        lv += 1
        text = assemble(lv)
    return text


def research_summary(store, rid, at):
    did = (store.get(rid) or {}).get('data', {}).get('doc')
    v = D.latest(store, did) if did else None
    secs = (v or {}).get('data', {}).get('sections') or {}
    return NL.join(f"{k}: {t[-600:]}" for k, t in list(secs.items())[-2:]) if secs else ''


def research_context(store, rid, *, turn, at, message, thread_text=None, thread_turns=6):
    """Context for a research item (query list, not the tree)."""
    r = (store.get(rid) or {}).get('data', {})
    related = [x for x in store.about(rid, at) if x not in ('ROOT',) and (store.get(x) or {}).get('type') in ('task', 'goal')]
    rel = [f"{' / '.join(_title(store, n) for n in reversed([x] + store.ancestors(x, at)))}: {(store.get(x) or {}).get('data', {}).get('purpose', '')}" for x in related]
    cards = []                                    # the research serves these works: what they are and where they stand (their constraints stay theirs)
    for x in related:
        nodes = subtree(store, x, at)
        prog = [_progress_line(r) for n in nodes for r in store.items('progress', about=n, at=at)][-2:]
        decs = [f"[turn {r['turn']}]{r['data'].get('statement', '')}" for n in nodes for r in store.items('decision', about=n, at=at, current_only=True)
                if r['data'].get('type') not in ('rejected', 'questioned')][-4:]
        xs = [_exchange(store, i, thread_text, 1000, 1000) for i in _turns(store, nodes, turn)[-2:]]
        cards.append(NL.join([f"### {' / '.join(_title(store, n) for n in reversed([x] + store.ancestors(x, at)))}",
                              f"Purpose: {(store.get(x) or {}).get('data', {}).get('purpose', '')}", 'Latest progress:', _lines(prog), 'Decisions made:', _lines(decs),
                              'Environment and locations:', _lines(_facts(store, nodes, at)[-6:])] + (['Latest exchanges (original text):'] + xs if xs else [])))
    reqs = [f"[turn {c['turn']}]{'(guidance) ' if c['type'] == 'guidance' else ''}{c['data'].get('statement', '')}"
            for typ in ('constraint', 'guidance') for c in store.items(typ, about=rid, at=at, current_only=True)]
    glob = [f"(global) {c['data'].get('statement', '')}" for c in store.items('constraint', about='ROOT', at=at, current_only=True)]
    thread = [_exchange(store, i, thread_text) for i in _turns(store, [rid], turn)[-thread_turns:]]
    words = task_segments(store, rid, turn) or [message]
    parts = [FIXED + NL + RESEARCH, '## Research', f"Research: {r.get('title', '')}", f"Document: {r.get('doc') or '(new)'}",
             'Related works (background only):', _lines(cards), "## This research's requirements", _lines(glob + reqs),
             '## Conclusions of earlier rounds', research_summary(store, rid, at) or '- (none)',
             "## This research's latest exchanges (original text, oldest first)"] + (thread or ['- (none)']) + [
             '## Agent behavior guidance (read before doing the matching kind of thing)', _lines(D.behavior_index(store, at)),
             '## The latest turns of the conversation (original text, oldest first; they may belong to other works - use them only to understand what this message refers to)',
             *[_exchange(store, i, thread_text, 1500, 1500) for i in conversation_turns(store, turn, RECENT_CONVERSATION)
               if i not in _turns(store, [rid], turn)],
             '## What the user points to this time', _lines(user_points(store, turn)),
             "## The goal: the user's words this time", _flat(NL.join(words))]
    return NL.join(parts)


def _stored_exchange(store, i):
    t = store.db.execute("select data from items where type='turn' and turn=? limit 1", (i,)).fetchone()
    r = store.db.execute("select data from items where type in ('exchange','run') and turn=? and data like '%\"reply\"%' order by at desc limit 1", (i,)).fetchone()
    return (json.loads(t[0]).get('text', '') if t else '', (json.loads(r[0]).get('reply', '') if r else ''))


def _turn_text(store, turn):
    r = store.db.execute("select data from items where type='turn' and turn=? and source='user' limit 1", (turn,)).fetchone()
    return json.loads(r[0]).get('text', '') if r else ''


def attempts_text(store, task, *, at, phrases, limit=30):
    """The work's earlier executions with their time, result and failures, when the user's words name a time ("last time", "yesterday's",
    "the first version", "before the fix"): the executor reads the words and picks the attempt they mean (concept 4: a reference resolves to a
    concrete attempt; the first ones are kept because "the first version" is often meant)."""
    import datetime
    rows = []
    for n in [task] + [c for c in store.children(task, at)]:
        for r in store.items('progress', about=n, at=at):
            d = r['data']
            if not (d.get('done') or d.get('failed')): continue
            rows.append((r['at'], n, d))
    if not rows: return ''
    rows.sort(key=lambda x: x[0])
    keep = rows if len(rows) <= limit else rows[:3] + rows[-(limit - 3):]
    fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M')
    lines = []
    for t, n, d in keep:
        f = d.get('failed') or []
        lines.append(f"- {fmt(t)}{'' if n == task else ' (subtask ' + n + ')'}: {(d.get('done') or '')[:300]}"
                     + (('; did not work: ' + '; '.join(str(x) for x in f)[:200]) if f else ''))
    said = ', '.join(f'"{p}"' for p in phrases[:3])
    return NL + NL + NL.join([f"## Earlier executions of this work (the user's words mention {said}, which may mean one of them; judge which from the words)", *lines])


def forward_text(store, task, *, run, turn, at, readonly=False, thread_text=None):
    """What the task's session receives with a new message (no re-assembly of the whole context). The user alternates works
    in one conversation: the session also gets what was said elsewhere after its own last turn (S3; blk4fwd)."""
    at_ = at - 1e-6
    since = store.get(run)['at']
    last = store.db.execute("select max(e.at) from edges e join items i on i.id=e.src where e.dst=? and e.rel='forwarded_to' and i.type='turn' "
                            "and e.at < ?", (run, at)).fetchone()[0] or since
    words = task_segments(store, task, turn) or [s for s in [_turn_text(store, turn)] if s]
    path = [task] + store.ancestors(task, at_)
    new_items = []
    for n in path + ['ROOT']:
        for typ in ('constraint', 'guidance', 'decision'):
            for r in store.items(typ, about=n, at=at, current_only=True):
                if r['at'] >= since and not store.db.execute(
                        "select 1 from edges where src=? and rel='forwarded_to' and dst=?", (r['id'], run)).fetchone():
                    new_items.append(r)
    for c in store.children(task, at_):           # parts of this work with their own requirements (local constraints)
        for r in store.items('constraint', about=c, at=at, current_only=True):
            if r['at'] >= since and not store.db.execute("select 1 from edges where src=? and rel='forwarded_to' and dst=?", (r['id'], run)).fetchone():
                new_items.append(dict(r, data=dict(r['data'], statement=f"(only for the part \"{_title(store, c)}\") {r['data'].get('statement', '')}")))
    parts = ["## The user's new message about this task (original words)" + (' (read-only query: only answer, change nothing)' if readonly else ''), _flat(NL.join(words)) or '- (none)']
    if new_items:
        parts += ['## Constraints, guidance and decisions for this task not yet passed on (including ones set elsewhere)',
                  _lines([f"[turn {r['turn']}]{'(guidance) ' if r['type'] == 'guidance' else ''}"
                          f"{ {'rejected': '(rejected) ', 'questioned': '(questioned by the user; verify before use) '}.get(r['data'].get('type'), '') if r['type'] == 'decision' else ''}"
                          f"{r['data'].get('statement', '')}" for r in new_items])]
    wd = (store.get(task) or {}).get('data', {}).get('working_dir') or ''
    objs = [o for (o,) in store.db.execute("select id from items where type='object' and id like ?", (f"OBJ:{D.norm_path(wd).lower()}::%",)).fetchall()] if wd else []
    gone = _gone(store, list(dict.fromkeys(subtree(store, task, at_) + path)) + objs, at_, since=last)   # object rules of its directory too
    if gone: parts += ['## Approaches replaced or rejected in the meantime (do not use again)', _lines(gone[-8:])]
    notes = [store.get(i)['data'].get('text', '') for (i,) in store.db.execute(
        "select e.src from edges e join items i on i.id=e.src where e.dst=? and e.rel='forwarded_to' and i.type='notice' and e.at > ? and e.at <= ?",
        (run, last, at)).fetchall()]
    if notes: parts += ['## Changes in the meantime', _lines(list(dict.fromkeys(notes))[-10:])]
    qs = []
    for (q, fk) in store.db.execute("select e.src, e.dst from edges e join edges f on f.src=e.dst and f.rel='forked_from' and f.dst=? "
                                    "where e.rel='answered_by' and e.at > ? and e.at < ?", (run, last, at)).fetchall():
        d = store.get(q)['data']
        if d.get('answer'): qs.append(f"[turn {store.get(q)['turn']}] Q: {d.get('question', '')[:200]} A: {d['answer'][:800]}")
    for n in list(dict.fromkeys(subtree(store, task, at_) + path)):   # queries about this work answered from memory: the user saw the answer (S3)
        for r in store.items('query', about=n, at=at):
            d = r['data']; line = f"[turn {r['turn']}] Q: {d.get('question', '')[:200]} A: {(d.get('answer') or '')[:800]}"
            if r['at'] > last and d.get('answer') and (r['turn'] is None or r['turn'] < turn) and line not in qs: qs.append(line)
    if qs: parts += ['## Questions answered in queries in the meantime (the user saw these answers)', _lines(qs[-5:])]
    # the session has not seen what the user said to other works since its last turn; a new executor gets the recent
    # conversation, a reused one gets the part of it after its own last turn
    mine = set(_turns(store, list(dict.fromkeys(subtree(store, task, at_) + [task])), turn))
    seen = store.db.execute("select max(i.turn) from edges e join items i on i.id=e.src where e.dst=? and e.rel='forwarded_to' and i.type='turn' "
                            "and e.at < ?", (run, at)).fetchone()[0]
    seen = seen if seen is not None else (store.get(run) or {}).get('turn')
    other = [i for i in conversation_turns(store, turn, RECENT_CONVERSATION) if i not in mine and seen is not None and i > seen]
    if other: parts += ['## What was just said in the conversation and this message follows on (original text; it may belong to other works - use it only to understand this message; its requirements belong to their own works)',
                        NL.join(_exchange(store, i, thread_text, 1500, 1500) for i in other)]
    pts = user_points(store, turn)
    if pts: parts += ['## What the user points to this time', _lines(pts)]
    return NL.join(parts), [r['id'] for r in new_items]
