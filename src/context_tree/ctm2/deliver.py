"""Delivery (concept model 5.1 step 3): where the user's words go and how.

One call over the candidates that candidates.py gathered (with their state and the local tree around them); a second call
with every work when none fits or a new top-level work needs a check against what memory already holds. The executor gets
the user's own words and a context the code assembles from the position, so this call does not analyse the message beyond
deciding the destination.
"""
from .model import ask

NL = chr(10)

# 2026-11-24: memory operations addressed to CTM stay with CTM (concept 1.1, S15); work messages judged memory 0/99 (V15 0/99), research/blk1mem
PROMPT = '''You are CTM: the user talks only to you, in one continuous conversation, moving several works forward in turns. A user message has just arrived. You decide where it (or each of its parts) goes and how; for a new work you also decide its place in the task tree.
The executor receives the user's own words and a context that the code assembles from the place you choose (the constraints and decisions on the path, the latest exchanges of this work and of the works above it, the recently executed siblings), and works out for itself what to do; the constraints and decisions needed later are recorded by another step after delivery. So you need not analyse how the thing should be done; what you must get right is where it belongs.

What the task tree and a place are for: under the root are Goals - the user's long-term objectives; later work with the same aim also goes under them. Under a Goal are tasks; a task may have subtasks, which are its parts (the task is done only when its subtasks are done); works done one after another under the same parent are siblings. The place decides three things: the constraints and decisions of the works above reach it - placed right, what the user has said about this kind of work need not be said again; placed wrong, unrelated constraints restrict it. The executor sees the scene on the path and of the latest siblings - a related scene saves rediscovering things, an unrelated one is only noise. The user sees in the tree where it is and how things stand. One work often has several reasonable places and there is no single answer; choose the one that serves these three things best.

How it is delivered (to):
- existing: to an existing work (node): continue it, correct its approach, add requirements or material, check its result, answer its executor, approve a plan it proposed. The user's words go into that work's executor session, and the executor continues with its scene.
- new: a new work. In new, write the title, the purpose (its output or the state it changes) and its place: goal is the long-term objective it serves (an id from goals; when none fits, summarize a new one as {"title":"..","purpose":"..","stated":false}; stated is true when the user said this aim, in the user's words); parent is the work it is a part of; after is the work it follows (the next step under the same parent) - with after, that work becomes its predecessor: that work's results are handed to it, the executor reads that work's latest exchanges in the most detail as "the step just done", and while that work is unfinished this one counts as waiting. So write after only when the new work builds on that work's results and has to wait until it is done; a work done recently, on the same topic or about the same object is not a previous step. Written wrongly, the executor takes an unrelated scene for the previous step and waits for an unrelated work; leaving it out costs little - the latest siblings are given in original text anyway, and conclusions needed from elsewhere can go in uses; with neither, the work goes directly under its goal. uses: other works, research items, or questions the user asked earlier (ids from candidates, research_items or recent_queries) that this new work needs but that are neither its parent nor its previous step - when the user asks first and then acts, the answers are exactly what the new executor must know - for example acting after a research, or doing something according to another work's conclusion; CTM hands their conclusions to the new executor. First think about which existing conclusions this new work builds on. Left out, the executor lacks them and must rediscover them or have the user say them again; one too many, the executor only reads one more conclusion - so leave out works that only share a topic or an object and hold no conclusion it needs, and write all that it needs. When the new work and some candidates are parts or successive steps of one larger work that has no node in the tree yet, list them in same_work_as; CTM judges separately whether to create a parent for them. When the user asks for a plan first, or explicitly gives a large deliverable to be done in several steps, plan is true (CTM calls the planner to split it into subtasks, proposed to the user); otherwise the executor arranges its own steps and plan is false. session: a new work opens a new executor session (new); when it directly continues the parent work's current execution, done right away on the same scene, write parent, and it runs in the parent work's session.
- side: the user only wants to know something, and the question concerns a work (node): a read-only fork of that work's session answers it, and the answer does not enter that work; node is null when it concerns no existing work.
  side and existing decide where these words go and what they leave behind: delivered into a work (existing), they enter its executor session, the executor takes them as something to do - and may change things - and the answer is recorded in that work's progress, so the work looks busy; as a side question (side), a read-only fork answers, nothing is changed, and the answer is recorded as a query, outside the work. The two errors cost differently: words that only want to know, sent into a work, may cause changes the user did not ask for and leave records in that work that do not belong to it; words that ask for something to be done, taken as a side question, get a read-only answer that cannot do it, and one sentence from the user ("I want you to change it") turns them into work. So when unsure, take it as a side question. For questions asking for an explanation, a lookup, a cause, the current state or progress, see whether the user only wants to know, or wants that work to go on accordingly.
- research: going outside (web material, other projects) to collect information or reach a conclusion, without changing any resource: research is required - the id of an item in research_items to continue it, otherwise "new" with a title in new. A research executor only reads the project; downloading, scraping or archiving external content, or making changes right after the research, is productive work (new/existing), not research.
- control: for the executor of a work (node): pause, stop, resume, abandon, accept (confirm it is done), reopen, just let it continue (continue), or approve its pending item (answers_pending: the pending item's id, or its number in recent_displays).
- ask: it is unclear which work this belongs to, and the requested action is irreversible (commit, push, delete, deploy): ask the user first.
- chat: small talk; nothing is sent.
- memory: words addressed only to CTM - preferences and rules the user wants CTM to remember, adjustments to how CTM or all executors should work from now on - with nothing for an executor to do this time. CTM records it in its memory itself (and later gives it to the executors it concerns), tells the user what it recorded, and sends nothing to any executor; node is the one work the rule is only about, empty when it concerns all work. The cost of sending it to an executor: the executor treats "remember" as a job (changes its own configuration or instruction files, writes documents), which the user did not ask for; the cost of taking something to be done as memory: it is not sent. When one message has both something to do and a rule to remember, split them: the part to do goes to its work and the part to remember is memory; requirements that belong to the thing to do (how to do it this time) go with it, not as memory.
When one message speaks of several unrelated things, deliver them separately; part gives which part of the original words each one is ("all" for the whole message). Background and pasted material go with the thing they serve.
alternatives: when delivering to an existing work or placing under one, give the next one or two likely works (most likely first); the page shows them as alternatives, and when a delivery is wrong the user re-delivers with one click; empty when there are none.

Analyse first, then decide. In analysis write your analysis (a few sentences), thinking these through:
- What the user is doing right now: which work the conversation was just moving forward (current, the current task on the page: by default the one the user last talked about; when the user selects another work in the tree it becomes that one, and the latest turn of the conversation may still belong to the earlier work - selecting is the user's own act and more reliable than inferring from the latest turn; recent_conversation), which result or notice the user just saw (recent_displays), and how this message points to its object (pointing: answering what was just shown, a bare push, a near reference, a named object, a time, material...). When the user names no object and says continue, stop or what now, it is about the work the user is talking with, even if other works are running; when it answers a notice or result of another work that was just shown, it is about that work.
- Why this message comes now: what the user says in the middle of a work is often prompted by it - for it, because of its result, an idea it led to - even if what is asked is more general; or the user may simply have remembered something else. Seeing the cause shows its relation to each work.
- What it asks for: continuing, correcting, adding to or checking an existing work (the user will accept the result as part of what that work delivers), or a new output accepted on its own; changing something, or only understanding - contradicting or correcting the agent, or adding facts for the work to adjust to, moves that work forward; only wanting to understand, without having decided that something is wrong, is a side question.
- Its relation to the candidate works: each item in candidates comes with why it was found (sources: visited recently, running or with pending items, similar objects, close in time), its purpose, its state, what the user recently said to it (recent_notes), its results, and the works done after it under the same parent (later_siblings); object_groups lists the families of works that touched the same object - one file or service is often touched by several works. For the works that may be related, think whether this message continues it, is a part of it, is the next step after it, is another work done for it with a more general output, is another work under the same long-term objective, or only looks related because of the same object or topic or nearness in time; whether that work is already finished, and whether its scene has since been changed by later work.
- For a new work, which long-term objective (goals) it serves: a Goal is wider than this one request, and later requests with the same aim also go under it; it is not a project or a directory (candidates and Goals carry their working directories, for reference).
- The cost of a wrong judgment: delivered by mistake to an existing work, it absorbs content that is not its own, the executor works with an outdated or unrelated scene, and the tree no longer shows what the user is doing; a new work created by mistake loses the details of the original session, but the new executor still has the context of the path and the siblings.
When no candidate fits and it does not look like a new work, or a new work is to be created but you fear memory already holds the same work, write the reason in wider; you will see all works and judge once more.

Write titles, purposes, goals and why in the language the user writes in.

Output JSON only: {"deliveries":[{"analysis":"..","part":"all","to":"existing|new|side|research|control|ask|chat|memory","node":"N3","new":{"title":"..","purpose":"..","goal":null,"parent":null,"after":null,"uses":[],"same_work_as":[],"plan":false},"session":"continue|new|parent","control":null,"research":null,"answers_pending":null,"alternatives":[],"why":"one sentence"}],"wider":null}'''


WIDER = NL + NL + ('This is the second judgment: all_works lists every work (the most recently active first); candidates are the works whose '
                   "objects are close to this message's. This time you cannot ask to widen the scope again; wider is null.")


def local_outline(tree, cands, now):
    """The tree around the candidates: each one's ancestors, its siblings and its children."""
    keep = []
    for c in cands:
        if c not in tree.nodes: continue
        chain = [c] + tree.ancestors(c)
        keep += chain
        par = tree.nodes[c].parent
        keep += [n.id for n in tree.nodes.values() if n.parent == par]
        keep += [n.id for n in tree.nodes.values() if n.parent == c]
    keep = list(dict.fromkeys(keep))
    return [{'id': n, 'title': tree.nodes[n].title, 'parent': tree.nodes[n].parent, 'status': (tree.store.get(n) or {}).get('data', {}).get('status'),
             'hours_since_active': round((now - tree.nodes[n].last_time) / 3600, 1)} for n in keep]


def candidate_view(tree, cands, now):
    out = []
    for n, sources in cands:
        if n not in tree.nodes: continue
        d = tree.detail(n, now)
        d.pop('constraints', None)
        if isinstance(d.get('latest_results'), list): d['latest_results'] = d['latest_results'][-CAND_RESULTS:]
        g = n
        while tree.nodes[g].parent in tree.nodes: g = tree.nodes[g].parent
        if g != n and tree.nodes[g].kind == 'goal': d['goal'] = tree.nodes[g].title
        d['sources'] = sources
        d['children'] = [tree.nodes[c].title for c in d.get('children') or [] if c in tree.nodes][:8]
        out.append(d)
    return out


def payload(tree, *, message, pointing, recent, cands, now, current=None, ui_selection=None, displays=None,
            pending=None, research=None, user_understanding=None, wider=False, groups=None):
    """The delivery call's input (reads the store; build it in the thread that owns the store)."""
    msg = message if len(message) <= 6000 else message[:3000] + ' ... [middle omitted] ... ' + message[-2000:]
    p = {'message': msg, 'pointing': pointing, 'recent_conversation': recent, 'current': current, 'ui_selection': ui_selection,
         'candidates': candidate_view(tree, cands, now), 'open_pending': pending or [], 'recent_displays': displays or [],
         'research_items': research or [],
         'object_groups': [{'object': g['object'], 'matched': g['matched'], 'works': [{'id': n, 'title': tree.nodes[n].title}
                                                                                   for n in g['works'] if n in tree.nodes]}
                           for g in groups or []]}
    goals = sorted([x for x in tree.nodes.values() if x.kind == 'goal'], key=lambda x: -(x.last_time or 0))[:80]
    if goals:                                     # long-term objectives a new work can go under
        p['goals'] = [{'id': x.id, 'title': x.title, 'purpose': (x.purpose or '')[:80],
                       'recent_works': [c.title for c in sorted((c for c in tree.nodes.values() if c.parent == x.id), key=lambda c: -(c.last_time or 0))[:2]],
                       'working_dirs': sorted({c.working_dir for c in tree.nodes.values() if c.parent == x.id and c.working_dir})[:3]}
                      for x in goals]
    if wider:
        p['all_works'] = tree.outline(now)
    else:
        p['local_tree'] = local_outline(tree, [n for n, _ in cands], now)
    if user_understanding: p['understanding_of_user'] = user_understanding   # an inference: only for reading ambiguous messages
    return p


def call(p, *, model, effort='low', wider=False, prompt=None):
    return ask((prompt or PROMPT) + (WIDER if wider else ''), p, model=model, effort=effort, role='deliver-wide' if wider else 'deliver')


CAND_RESULTS = 1   # 2026-11-20: each candidate with its latest result (earlyg: routing and placement equal, uses within noise; input -6.5%)

def deliver(tree, *, message, pointing, recent, cands, now, model, effort='low', current=None, ui_selection=None, displays=None,
            pending=None, research=None, user_understanding=None, wider=False, groups=None, queries=None):
    """recent: [{'user','agent_end','went_to'}] oldest first; cands: [(node, sources)]; groups: object families
    [{'object','matched','works'}] from candidates.object_families."""
    p = payload(tree, message=message, pointing=pointing, recent=recent, cands=cands, now=now, current=current, ui_selection=ui_selection,
                displays=displays, pending=pending, research=research, user_understanding=user_understanding, wider=wider, groups=groups)
    if queries: p['recent_queries'] = queries          # V11: what the user asked recently, for a new work's uses (concept 5.3 item 5)
    return call(p, model=model, effort=effort, wider=wider)
