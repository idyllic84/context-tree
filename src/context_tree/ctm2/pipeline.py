"""CTM runtime pipeline over the store (concept model v2, section 5).

on_message (5.1, round 7): pointing and objects (ref) -> candidates per pointing mode
(recent works, live executors / pending items / displays, entity -> object -> works, time) -> delivery (one call; a second
over every work when none fits) -> records, mentions of the named objects, dispatch (reuse the session, new executor with an
initial context, the parent's session, read-only fork for a side question, research item, control, ask) -> memory (one call
after dispatch: constraints, guidance, decisions, facts, behavior, with placement and replacement) -> relay.
on_reply (5.2 items 4, 6): control-layer judgment of the stop, run evidence, file versions, brief progress, long reply as a
document, lifecycle events, escalations as pending items, relay of what needs the user.
on_executor_question (5.2 item 5): CTM answers from memory (only current items) or relays to the user.
maybe_maintain (5.6): periodic maintenance over what was stored since the last run.
UI edits go through ctm2.ui (5.5).
The current task (UI default) is the node of the user's last delivered message unless the user selects another node.
"""
import json

NL2 = chr(10) + chr(10)

from .writeback import write_reply
from .progress import summarize
from .tree import StoreTree
from .model import ask
from . import context as C
from . import control as K
from . import documents as D
from . import execution as X
from . import lifecycle as L
from . import query as Q
from . import relay
from . import root as R
from .maintain_store import maintain_store, last_maintenance, apply_ops
from . import maintain_store as MS
from .recall import answer as recall_answer

DECIDE = '''You are CTM. The executor stopped and asks the user to decide: whether to take an optional step the contract does not ask for, or which of several options to take.
Decide on the user's behalf only when what the user said for this work, the constraints and decisions in force, and your understanding of the user (an inference, which never overrides the user's words) already clearly settle the answer;
otherwise (it needs the user's preference, widens the scope, is irreversible or affects the outside) leave it to the user. Output JSON only: {"decide":false,"answer":"the reply to the executor when you decide","basis":"the grounds"}'''

CONTROL_STATUS = {'pause': 'paused', 'abandon': 'abandoned', 'accept': 'verified', 'reopen': 'reopened'}


WORKDIR = '''The user raised a new work that is not part of any existing work. Judge which directory it should be done in; the executor runs there.
You get the user's words, the new work's title and purpose, and the directories the user has worked in (each with the titles of a few works).
When the work means reading code, changing files or running things in a project, choose that project's directory; when it concerns no project (writing a document, looking things up, a general question, personal matters), choose null - CTM gives it a separate scratch directory.
The cost of a wrong choice: the executor reads and writes files in the wrong repository; choosing one when it should not, the executor works in an unrelated repository; not choosing one when it should, the executor first has to find the project or ask. When unsure, choose null.
Output JSON only: {"dir":"the directory exactly as given, or null","why":"one sentence"}'''


from concurrent.futures import ThreadPoolExecutor as _TPE
_POOL = _TPE(4)

class CTM:
    def __init__(self, store, *, model='gemini-4-argon', light_model='gemini-3.8-flash', memory_model='gemini-3.8-flash',
                 control_model='gemini-3.8-flash', recent_hours=X.RECENT_HOURS,
                 maintain_every=None, answer_queries=False,
                 user_understanding=None, use_planner=True, embed=None):
        self.store, self.model, self.recent_hours = store, model, recent_hours
        self.light_model = light_model                # light, high-volume calls (pointing and objects); the rest use model
        self.memory_model = memory_model              # memory call: flash had the fewest wrong items with comparable recall (round 7b)
        self.control_model = control_model            # control layer: flash let fewer substantive answers be skipped than argon (E7)
        self.scope_cache = {}                         # embedding vectors for finding the same requirement on other branches
        self.lift_same = False                        # concept 3.5: a new task constraint that is the same requirement as on other branches -> lift
                                                      # (scope.check; reconnected to this flow, not yet evaluated, so off)
        R.ensure_root(store)
        self.tree = StoreTree(store)
        self.current = None
        self.assigned = {}
        self.maintain_every = maintain_every          # seconds between maintenance runs (None: only when called)
        self.answer_queries = answer_queries
        self.use_planner = use_planner                # replay: the historical user never saw proposals, so only the request is recorded
        self.write_object_files = False               # the pilot: CTM writes its ctm.md records (objectfiles); off offline
        self._proposal_answers = {}                   # work -> CTM proposals the user just answered (go with its next dispatch)
        self._object_acc = {'written': [], 'removed': [], 'proposals': [], 'withdrawn': []}   # ctm.md work done at dispatches, reported with the message
        self.user_understanding = user_understanding  # initial content from the user-habit study (3.3)
        self._embed = embed                           # texts -> vectors; default: the project's embedding model
        self._vectors = {}

    # ---- signals for understanding and localization ------------------------------------------------------------------
    def running_nodes(self, limit=8, at=None):
        """Tasks whose executor is working or waiting, most recently active first (bounded). Replay cannot see real executor
        states between messages, so sessions active within recent_hours also count."""
        out = []
        for (rid, task) in self.store.db.execute("select e.src, e.dst from edges e join items i on i.id=e.src where e.rel='serves' and i.type='run' and e.valid_to is null").fetchall():
            r = self.store.get(rid)
            if r['data'].get('status') == 'active' and r['data'].get('mode') in ('session', 'readonly', 'fork') and task in self.tree.nodes:
                last = X.last_activity(self.store, rid)
                if r['data'].get('state') == 'waiting' or at is None or at - last <= self.recent_hours * 3600:
                    out.append((last, task))
        return list(dict.fromkeys(t for _, t in sorted(out, reverse=True)))[:limit]

    def _pending_view(self, at):
        return [{'id': p['id'], 'what': p['data'].get('what'), 'kind': p['data'].get('kind'), 'task': (self.store.about(p['id']) or [None])[0]}
                for p in relay.open_pending(self.store, at)][-10:]

    def _understanding_of_user(self, at):
        u = R.understanding_text(self.store, at)
        lines = u['understanding'] or ([self.user_understanding] if self.user_understanding else [])
        return '\n'.join(lines) if lines else None

    # ---- user message ---------------------------------------------------------------------------------------------------
    def _workdir_for_new(self, pointing, near, fallback, *, message='', new=None, at=None):
        """Where a new work runs (CTM decides per work): a directory the message names (one that exists), else the directory of
        the work it is part of or follows, else the caller's (replay: the session's), else the project the work belongs to as
        judged from the user's words; '' when it belongs to no project (the pilot gives it a scratch directory of its own)."""
        import os
        bs = chr(92)
        for e in (pointing or {}).get('entities') or []:
            for v in (e.get('resolved'), e.get('said')):
                v = (v or '').strip().strip('`"' + chr(39))
                if len(v) > 3 and (v[1:3] in (':/', ':' + bs) or v.startswith('/')):
                    if os.path.isdir(v): return v.replace(bs, '/')
                    if os.path.isfile(v): return os.path.dirname(v).replace(bs, '/')
        for n in [near] + (self.tree.ancestors(near) if near in self.tree.nodes else []):
            if n in self.tree.nodes and self.tree.nodes[n].working_dir: return self.tree.nodes[n].working_dir
        if fallback: return fallback
        return self._choose_workdir(message, new or {}, at)

    def _choose_workdir(self, message, new, at):
        """The project a new top-level work belongs to, among the directories the user has worked in (LLM judgment)."""
        dirs = {}
        for n in sorted(self.tree.nodes.values(), key=lambda x: -(x.last_time or 0)):
            wd = n.working_dir
            if not wd or '/work/' in wd.replace(chr(92), '/'): continue
            dirs.setdefault(wd, [])
            if len(dirs[wd]) < 4: dirs[wd].append(n.title)
        if not dirs: return ''
        out, _ = ask(WORKDIR, {'message': message[:3000], 'new_work': new, 'directories': [{'dir': d, 'works': t} for d, t in list(dirs.items())[:40]]},
                     model=self.light_model, effort='low', role='workdir')
        d = (out or {}).get('dir')
        return d if isinstance(d, str) and d in dirs else ''

    def embed(self, texts):
        need = [t for t in dict.fromkeys(texts) if t not in self._vectors]
        if need:
            if self._embed is None:
                from ..common import llm as base
                self._embed = base.embeddings
            for i in range(0, len(need), 96):
                for t, v in zip(need[i:i + 96], self._embed(need[i:i + 96])): self._vectors[t] = v
        return [self._vectors[t] for t in texts]

    def on_message(self, turn, at, message, *, recent, previous_reply, working_dir='', ui_selection=None, dispatch=True, thread_text=None,
                    after_dispatch=None):
        """Concept 5.1. CTM decides only where the user's words go and what to remember:
        pointing and objects (ref) -> candidates per pointing mode -> delivery (one call; a second over every work when none
        fits) -> records, mentions and dispatch -> memory (one call, after dispatch) -> reply."""
        from . import ref as REF, candidates as CA, deliver as DV, remember as RM
        X.sweep(self.store, at=at)
        displays = relay.recent_displays(self.store, at)
        pending = self._pending_view(at)
        ui_sel_raw = ui_selection
        ui_selection, pointed = self._selection(message, ui_selection)
        ui_selection = ui_selection if ui_selection in self.tree.nodes else None
        work = lambda n: self.tree.nodes[n].title if n in self.tree.nodes else None
        res_ = lambda n: self.tree.resolve(n) if n else None
        rc = [{'i': i, 'user': (t.get('user') or '')[:600], 'agent_end': (t.get('agent') or '')[-400:], 'went_to': work(res_(t.get('node')))}
              for i, t in enumerate(recent)]
        cur = res_(self.current)
        cur = cur if cur in self.tree.nodes else None
        # 1. how the message points to its work, the objects it names
        pointing, _ = REF.extract(message, [{'user': r['user'], 'agent_end': r['agent_end']} for r in rc[-2:]], model=self.light_model,
                                  displays=displays[-6:], pending=pending)
        pointing = pointing if isinstance(pointing, dict) else {}
        self._time_phrases = [t.get('phrase') for t in pointing.get('time_refs') or [] if isinstance(t, dict) and t.get('phrase')]
        # 2. candidates
        index = CA.object_index(self.store, at=at)
        groups = []
        if ui_selection:
            cands = [(ui_selection, ['ui_selection'])]
        else:
            recent_nodes = [n for n in (res_(a) for _, a in sorted(self.assigned.items())[-20:]) if n in self.tree.nodes]
            live = ([cur] if cur else []) + self.running_nodes(at=at) + [p['task'] for p in pending if p.get('task') in self.tree.nodes] \
                + [d['task'] for d in reversed(displays) if d.get('task') in self.tree.nodes]
            merged = {}                               # mentions on a node merged away by maintenance count for the node it went into
            for n, s in CA.candidates(self.store, at=at, ref=pointing, recent=recent_nodes, live=live, embed=self.embed, index=index, groups=groups):
                if res_(n) in self.tree.nodes: merged.setdefault(res_(n), []).extend(x for x in s if x not in merged.get(res_(n), []))
            cands = list(merged.items())
            for g in groups: g['works'] = list(dict.fromkeys(res_(n) for n in g['works'] if res_(n) in self.tree.nodes))
        # 3. delivery
        common = dict(message=message, pointing=pointing, recent=rc, now=at, model=self.model, current={'id': cur, 'title': work(cur)} if cur else None,
                      ui_selection={'id': ui_selection, 'title': work(ui_selection)} if ui_selection else None, displays=displays[-8:],
                      pending=pending, research=self._recent_research(at), user_understanding=self._understanding_of_user(at), groups=groups)
        out, _ = DV.deliver(self.tree, cands=cands, queries=self._recent_queries(at, turn), **common)
        out = out if isinstance(out, dict) else {}
        wider = None
        if out.get('wider') and not ui_selection:
            wide = list({res_(n): [f'objects ({w}, {sc:.2f})'] for n, sc, w in reversed(CA.object_matches(self.store, pointing, at=at, embed=self.embed, index=index, k=15)[:15])
                         if res_(n) in self.tree.nodes}.items())[::-1]
            seen = {n for n, _ in wide}
            out2, _ = DV.deliver(self.tree, cands=wide + [(n, s) for n, s in cands if n not in seen], wider=True, **common)
            if isinstance(out2, dict) and out2.get('deliveries'):
                wider = out.get('wider'); out = out2
        # 4. records, mentions and dispatch
        dl = [d for d in out.get('deliveries') or [] if isinstance(d, dict)] or [{'part': 'all', 'to': 'chat'}]
        tid = self.store.add('turn', {'role': 'user', 'text': message[:6000], 'points': [pointed] if pointed else []}, at=at, source='user', turn=turn)
        placed, segs, rows, alt_titles, planned = [], [], [], {}, []
        structure_signals = []                        # delivery's signals for the structure judgment (after memory)
        to_dispatch, queries, controls, asks, researched = [], [], [], [], []
        for j, d in enumerate(dl):
            to = d.get('to')
            part = message if d.get('part') in (None, '', 'all') or not isinstance(d.get('part'), str) else d['part']
            node = res_(d.get('node'))
            node = node if node in self.tree.nodes else None
            if ui_selection and to in ('existing', 'side', 'control', 'ask'):
                node = ui_selection                    # the user's selection fixes the work
            target = None
            if to == 'existing':
                target = node or cur
                if target:
                    self.tree.touch(target, turn, at, part[:150]); to_dispatch.append((target, None))
                    if d.get('answers_pending'):
                        for pid in d['answers_pending'] if isinstance(d['answers_pending'], list) else [d['answers_pending']]:
                            p = self.store.get(pid) if isinstance(pid, str) else None
                            if p and p['type'] == 'pending' and p['data'].get('status', 'open') == 'open':
                                self.store.patch(pid, {'status': 'answered'}, at=at, source='user')
                                self._answered_proposal(pid, target, at)
            elif to == 'new':
                nw = d.get('new') if isinstance(d.get('new'), dict) else {}
                parent, after = res_(nw.get('parent')), res_(nw.get('after'))
                parent = parent if parent in self.tree.nodes else (ui_selection or None)
                after = after if after in self.tree.nodes else None
                if after and parent is None: parent = self.tree.nodes[after].parent
                goal = nw.get('goal')                 # the long-term objective it serves: an existing goal's id, or a new one
                gid = res_(goal) if isinstance(goal, str) else None
                if parent is None and gid in self.tree.nodes and self.tree.nodes[gid].kind == 'goal': parent = gid
                wd = self._workdir_for_new(pointing, parent or after, working_dir, message=part,
                                           new={'title': nw.get('title'), 'purpose': nw.get('purpose')}, at=at)
                if parent is None and isinstance(goal, dict) and (goal.get('title') or '').strip():
                    parent = self.tree.add(goal['title'].strip()[:40], goal.get('purpose') or '', None, None, turn, at, kind='goal', working_dir='')
                    if not goal.get('stated'): self.store.patch(parent, {'summarized': True}, at=at, source='ctm')   # CTM's summary
                    L.set_status(self.store, parent, 'running', at=at, source='ctm', reason='goal')
                target = self.tree.add(nw.get('title') or part[:40], nw.get('purpose') or '', parent, after, turn, at, working_dir=wd)
                from . import scope as SC             # before dispatch: the new executor's context has its siblings' constraints that
                try: SC.inherit_for_new_work(self.store, target, at=at, model=self.model, message=part)   # apply (3.5; 28 right / 6 wrong)
                except Exception as e: self.store.event('ROOT', 'inherit_new_failed', at=at, source='ctm', data={'error': str(e)[:200]})
                for u in (nw.get('uses') if isinstance(nw.get('uses'), list) else []):   # cross-task references (concept 3.1; deliver V8)
                    u = res_(u) if isinstance(u, str) else None
                    ur = self.store.get(u) if u else None
                    if ur and u != target and u not in (parent, after) and ur['type'] in ('task', 'goal', 'research', 'decision', 'query'):
                        self.store.link(target, 'uses', u, at=at, source='ctm')
                if cur and cur != target and self.tree.nodes[cur].kind != 'goal':   # the work being done when this one was raised
                    self.store.patch(target, {'raised_during': cur}, at=at, source='ctm')
                self.tree.touch(target, turn, at, part[:150])
                sw = [res_(x) for x in (nw.get('same_work_as') if isinstance(nw.get('same_work_as'), list) else []) if isinstance(x, str)]
                sw = [x for x in sw if x in self.tree.nodes and x != target]
                if after and self.tree.nodes[after].parent not in self.tree.nodes and after not in sw:
                    sw.append(after)                  # a next step beside a root-level work: the larger work has no node
                if sw or parent is None:              # no goal given, or parts of a task that has no node yet: structure judgment
                    structure_signals.append({'node': target, 'with': sw, 'why': d.get('why') or ''})
                share = parent if d.get('session') == 'parent' and parent in self.tree.nodes and self.tree.nodes[parent].kind != 'goal' else None
                if nw.get('plan'):                      # a staged deliverable: the planner proposes subtasks (3.4); approved or authorized ones run
                    self.store.event(target, 'plan_requested', at=at, source='ctm', data={'turn': turn})
                    if self.use_planner:
                        from .planner import plan
                        plan(self.store, self.tree, target, request=part, at=at, turn=turn, model=self.model)
                        planned.append(target)
                to_dispatch.append((target, share))
            elif to == 'side':
                target = node
                queries.append(self._query(part, node, at, turn))
            elif to == 'research':
                rid = d.get('research')
                if not (isinstance(rid, str) and (self.store.get(rid) or {}).get('type') == 'research'):
                    nw = d.get('new') if isinstance(d.get('new'), dict) else {}
                    rid = self.store.add('research', {'title': nw.get('title') or part[:40], 'status': 'open', 'doc': None}, at=at, source='ctm', turn=turn)
                    self.store.link(rid, 'about', node or 'ROOT', at=at, source='ctm')
                target = rid; researched.append(rid)
            elif to == 'control':
                target = node or cur
                if target:
                    ap = d.get('answers_pending')
                    refers = next((str(x) for x in (ap if isinstance(ap, list) else [ap]) if isinstance(x, (int, str)) and str(x).isdigit()), None)
                    got = self._controls({'controls': [{'seg': 0, 'control': d.get('control'), 'refers': refers}]}, [{'text': part}], [target], displays, at, turn)
                    controls += got
                    for c in got:
                        if c['control'] in ('continue', 'resume') or (c['control'] == 'approve' and 'forward' not in c and 'ask' not in c):
                            to_dispatch.append((c['node'], None))
            elif to == 'memory':                    # said to CTM itself: recorded by the memory call below, sent to no executor
                target = node
            elif to == 'ask':
                asks.append(self._ask(f"It is unclear which work this request belongs to, and the action is irreversible: {part[:120]}", node, at, turn))
            valid = target in self.tree.nodes or (isinstance(target, str) and (self.store.get(target) or {}).get('type') == 'research')
            alts = [a for a in (res_(x) for x in (d.get('alternatives') or [] if isinstance(d.get('alternatives'), list) else []))
                    if a in self.tree.nodes and a != target][:3]
            if alts and target in self.tree.nodes: alt_titles[target] = [self.tree.nodes[a].title for a in alts]
            sid = self.store.add('segment', {'text': part[:6000], 'to': to, 'alternatives': alts}, at=at, source='user', turn=turn, id=f'SEG{turn}-{j}')
            self.store.link(sid, 'part_of', tid, at=at, source='ctm')
            self.store.link(sid, 'about', target if valid else 'ROOT', at=at, source='ctm')
            placed.append(target if valid else None); segs.append({'text': part, 'to': to})
            rows.append({'seg': j, 'to': to, 'relation': {'existing': 'same', 'new': 'child' if target in self.tree.nodes and self.tree.nodes[target].parent else 'new',
                                                          'side': 'query', 'research': 'research', 'control': 'same'}.get(to, to),
                         'target': target, 'why': d.get('why'), 'session': d.get('session'), 'alternatives': alts})
        primary = next((n for n in placed if n in self.tree.nodes), None)
        mention_nodes = list(dict.fromkeys(n for n in placed if n in self.tree.nodes))
        for n in mention_nodes:                       # the objects the user named stay findable through this work
            CA.record_mentions(self.store, n, pointing, turn=turn, at=at)
        if pointing.get('material') and len(message) > 1500 and primary:
            D.create_document(self.store, kind='material', title=f'Material pasted in turn {turn}', use_when="when the user's original material is needed",
                              text=message[:20000], task=primary, at=at, source='user')
        if primary: self.current = primary
        self.assigned[turn] = primary or (researched[0] if researched else 'none')
        dispatches = []
        asked = {a for p in asks for a in self.store.about(p)}
        stopped = {c['node'] for c in controls if c['control'] in ('pause', 'stop', 'abandon')}
        if dispatch:
            for rid in dict.fromkeys(researched):
                dispatches.append(self.dispatch_research(rid, turn=turn, at=at, message=message, thread_text=thread_text))
            task_nodes = {n for n, _ in to_dispatch}
            for q in queries:                         # a side question: a read-only fork of the work's session (5.3)
                n = q.get('node')
                if n and not q.get('from_memory') and not q.get('ask') and n not in task_nodes and n not in asked:
                    dd = self.dispatch(n, turn=turn, at=at, message=message, thread_text=thread_text, readonly=True)
                    dispatches.append(dd); self.store.link(q['query'], 'answered_by', dd['run'], at=at, source='ctm')
            for n, share in dict.fromkeys(to_dispatch):
                if n in asked or n in stopped: continue
                steps = self.planned_steps(n)
                open_steps = [c for c in steps if L.status(self.store, c) not in L.FINISHED]
                if n in planned or open_steps:        # a planned work: the message goes to its steps, not the whole
                    ready = [c for c in open_steps if L.status(self.store, c) == 'ready' and not X.active_run(self.store, c)]
                    running = [c for c in open_steps if L.status(self.store, c) == 'running' and X.active_run(self.store, c)]
                    for c in ready or ([] if n in planned else running):   # executable steps start; else the running ones hear it
                        dispatches.append(self.dispatch(c, turn=turn, at=at, message=message, thread_text=thread_text))
                    continue                          # proposals only: they wait for the user's approval
                dispatches.append(self.dispatch(n, turn=turn, at=at, message=message, thread_text=thread_text, share_from=share))
        if after_dispatch:                            # live use: executors start now; the memory call below does not delay them
            after_dispatch({'node': primary, 'delivery': out, 'dispatches': dispatches, 'queries': queries, 'controls': controls,
                            'alternatives': alt_titles})
        # 5. memory, after dispatch
        mem, mlog = None, {'replaced': []}
        if not working_dir and primary in self.tree.nodes:   # live use: CTM decides each work's directory; memory uses the delivered work's
            working_dir = self.tree.nodes[primary].working_dir or ''
        if True:                                      # every message: a gate in the delivery call missed user choices (held-out decisions 0.83 vs 0.93)
            targets = [{'part': s_['text'], 'node': n} for s_, n in zip(segs, placed)
                       if n in self.tree.nodes or (isinstance(n, str) and (self.store.get(n) or {}).get('type') == 'research')]
            prev = rc[-2:] + ([{'user': '', 'agent_end': (previous_reply or '')[-1500:]}] if previous_reply else [])
            (mem, _), cur_ids = RM.remember(self.store, self.tree, message=message, deliveries=targets, recent=prev, at=at,
                                            working_dir=working_dir, model=self.memory_model, pending=pending)
            current = RM.current_items(self.store, self.tree, [t_['node'] for t_ in targets], at, working_dir)
            mem, _ = RM.check_replacements(self.store, mem, current=current, embed=self.embed, model=self.memory_model)   # replacements:
            cur_ids = {r['id'] for r in current}      # each new item against its most similar current items
            mlog = RM.write(self.store, self.tree, mem, turn=turn, at=at, working_dir=working_dir, model=self.model,
                            current_ids=cur_ids, default_node=primary or (researched[0] if researched else None))
            if pointed and isinstance(mem, dict) and (mem.get('decisions') or mem.get('constraints')) and self.store.get((ui_sel_raw or '').partition('#')[0]):
                did, _, section = ui_sel_raw.partition('#')
                self.store.event(did, 'stale', at=at, source='user', data={'section': section, 'turn': turn})
        if self.lift_same:                            # where a requirement belongs (concept 3.5), after memory, before structure
            from . import scope as SC
            for i in mlog.get('ids') or []:
                r = self.store.get(i)
                if r and r['type'] == 'constraint' and r['data'].get('kind') == 'task' and r['replaced_at'] is None \
                        and self.store.about(i) and self.store.about(i)[0] in self.tree.nodes:
                    try: SC.check(self.store, self.tree, i, at=at, model=self.model, cache=self.scope_cache)
                    except Exception as e: self.store.event('ROOT', 'scope_failed', at=at, source='ctm', data={'error': str(e)[:200]})
        reply = self._relay(turn, at, placed, segs, dispatches, queries, asks, controls, replaced=mlog.get('replaced') or [], planned=planned,
                            alternatives=alt_titles)
        object_files = self.sync_object_files(at, turn)   # CTM's own ctm.md records and annotation proposals (not executors' work)
        structured = []                               # 6. structure, only when delivery left something to settle (executors already run)
        for sig in structure_signals:
            if sig['node'] not in self.tree.nodes: continue
            lvl = MS.level_of(self.tree, sig['node'])
            try:
                if lvl[0] is None:                    # no goal given: the goal it serves
                    structured += MS.assign_goals(self.store, self.tree, at, model=self.model,
                                                  works=[sig['node']] + [w for w in sig['with'] if MS.level_of(self.tree, w) == lvl] if sig['with'] else [sig['node']],
                                                  why=sig['why'])
                    continue
                focus = [sig['node']] + [w for w in sig['with'] if w in self.tree.nodes and MS.level_of(self.tree, w) == lvl]
                if len(focus) < 2: continue
                structured += MS.structure(self.store, self.tree, at, model=self.model, parent=lvl[0], trigger='new_work', focus=focus, why=sig['why'])
            except Exception as e:
                self.store.event('ROOT', 'structure_failed', at=at, source='ctm', data={'signal': sig, 'error': str(e)[:200]})
        return {'node': primary, 'placed': placed, 'understanding': {'pointing': pointing, 'delivery': out, 'wider': wider, 'memory': mem,
                                                                     'candidates': cands, 'groups': groups, 'structure': structured},
                'localization': {'segments': rows, 'constraints': []}, 'write': mlog, 'controls': controls, 'dispatches': dispatches,
                'queries': queries, 'asks': asks, 'relay': reply, 'object_files': object_files,
                'planned': [{'task': n, 'subtasks': [{'id': c, 'title': self.tree.nodes[c].title if c in self.tree.nodes else c,
                                                      'status': L.status(self.store, c)} for c in self.planned_steps(n)]} for n in planned]}

    def _recent_queries(self, at, turn, k=8, turns=12):
        """Answered queries of the last turns: a new work that builds on them names them in uses (deliver V11; concept 5.3 item 5)."""
        rows = [q for q in self.store.items('query', at=at) if q['turn'] is not None and turn - turns <= q['turn'] < turn and q['data'].get('answered')]
        return [{'id': q['id'], 'turn': q['turn'], 'question': (q['data'].get('question') or '')[:200], 'answer': (q['data'].get('answer') or '')[:300]}
                for q in rows[-k:]]

    def _recent_research(self, at, k=8):
        rows = [r for r in self.store.items('research', at=at) if r['data'].get('status') != 'attached']
        def last(r):
            x = self.store.db.execute("select max(i.at) from items i join edges e on e.src=i.id and e.rel='about' and e.dst=? where i.type='segment'",
                                      (r['id'],)).fetchone()[0]
            return x or r['at']
        rows = sorted(rows, key=last)[-k:]
        return [{'id': r['id'], 'title': r['data'].get('title'), 'hours_since_active': round((at - last(r)) / 3600, 1),
                 'related': [x for x in self.store.about(r['id'], at) if x != 'ROOT']} for r in rows]

    def dispatch_research(self, rid, *, turn, at, message, thread_text=None):
        """A research item keeps its own session across rounds (read-only on the project; the conclusion goes to its document)."""
        run, reused = X.research_executor(self.store, rid, at=at, turn=turn)
        if reused:
            text, items = C.forward_text(self.store, rid, run=run, turn=turn, at=at, thread_text=thread_text)
            tid = self.store.db.execute("select id from items where type='turn' and turn=? and source='user' limit 1", (turn,)).fetchone()
            if tid: X.forward(self.store, run_id=run, item_id=tid[0], at=at, why="the user's new message about this research")
            for i in items: X.forward(self.store, run_id=run, item_id=i, at=at, why='takes effect for this research')
            return {'task': rid, 'run': run, 'reused': True, 'research': True, 'why': "continuing this research's session", 'forward': text}
        text = C.research_context(self.store, rid, turn=turn, at=at, message=message, thread_text=thread_text)
        return {'task': rid, 'run': run, 'reused': False, 'research': True, 'why': 'a new research executor', 'context': text}

    def _selection(self, message, ui_selection):
        """UI selection or explicit @-reference (an exact id the user chose); a selected document or section localizes to the
        task it belongs to and is what the user points to."""
        import re
        if not ui_selection:
            m = re.search(r'@((?:N|DO)\d+)', message or '')
            if m: ui_selection = m.group(1)
        if not ui_selection: return None, None
        did, _, section = ui_selection.partition('#')
        item = self.store.get(did)
        if item and item['type'] == 'document':
            task = next((a for a in self.store.about(did) if a in self.tree.nodes), None)
            v = D.latest(self.store, did)
            body = (v or {}).get('data', {})
            text = (body.get('sections') or {}).get(section) if section else body.get('text')
            return task, f"the document '{item['data'].get('title', '')}'{(', section ' + chr(34) + section + chr(34)) if section else ''}: {(text or '')[:1500]}"
        return (ui_selection if ui_selection in self.tree.nodes else None), None

    def _ask(self, what, node, at, turn):
        pid = self.store.add('pending', {'kind': 'ask_user', 'what': what, 'status': 'open'}, at=at, source='ctm', turn=turn)
        self.store.link(pid, 'about', node or 'ROOT', at=at, source='ctm')
        return pid

    def _controls(self, u, segs, placed, displays, at, turn):
        """Control segments act on lifecycle and executors (S12: stop the deployment; S2: short approval)."""
        done = []
        for c in u.get('controls') or []:
            j = c.get('seg') if isinstance(c.get('seg'), int) and c.get('seg') < len(segs) else 0
            kind = c.get('control')
            target = None
            ref = c.get('refers')
            disp = next((d for d in reversed(displays) if str(d['no']) == str(ref)), None) if ref not in (None, 'previous_reply') else None
            if disp and disp.get('task') in self.tree.nodes: target = disp['task']
            if target is None: target = placed[j] if placed[j] in self.tree.nodes else (self.current if self.current in self.tree.nodes else None)
            if target is None: continue
            entry = {'node': target, 'control': kind}
            if kind == 'approve':
                shown = [r[0] for r in self.store.db.execute("select dst from edges where src=? and rel='shows'", (disp['id'],)).fetchall()] if disp else []
                opens = [p for p in relay.open_pending(self.store, at, target) if not shown or p['id'] in shown]
                if c.get('ambiguous') and any(p['data'].get('kind') == 'out_of_scope' for p in opens):
                    entry['ask'] = self._ask('There are several pending items, one with an irreversible action: please say which one you approve', target, at, turn)
                else:
                    for p in opens[-1:]:
                        self.store.patch(p['id'], {'status': 'answered'}, at=at, source='user')
                        self._answered_proposal(p['id'], target, at)
                    from .planner import approve
                    approve(self.store, [n for n in [target] + self.store.children(target) if L.status(self.store, n) == 'proposed'], at=at)
                    if L.status(self.store, target) == 'blocked': L.set_status(self.store, target, 'running', at=at, source='user', reason='approved by the user')
                    run = X.active_run(self.store, target)
                    if run:                                   # the answer goes back to the waiting executor (5.2 item 5)
                        text, items = C.forward_text(self.store, target, run=run['id'], turn=turn, at=at)
                        tid = self.store.db.execute("select id from items where type='turn' and turn=? and source='user' limit 1", (turn,)).fetchone()
                        if tid: X.forward(self.store, run_id=run['id'], item_id=tid[0], at=at, why="the user's answer to a pending item")
                        for i in items: X.forward(self.store, run_id=run['id'], item_id=i, at=at, why='takes effect for this task')
                        entry['forward'] = text + self._proposal_section(target)
            elif kind in ('pause', 'stop'):
                L.set_status(self.store, target, 'paused', at=at, source='user', reason=(segs[j].get('text') or '')[:80])
                run = X.active_run(self.store, target)
                if run: X.stop_run(self.store, run['id'], at=at, why=kind)
            elif kind == 'resume':
                run = X.active_run(self.store, target)
                if run: self.store.event(run['id'], 'control', at=at, source='user', data={'action': 'resume'})
                L.set_status(self.store, target, 'running' if X.active_run(self.store, target) else 'pending', at=at, source='user', reason='resumed by the user')
            elif kind in CONTROL_STATUS:
                st = L.status(self.store, target)
                if kind == 'accept' and st == 'running': L.set_status(self.store, target, 'reported_done', at=at, source='user', reason='the user confirmed it is done')
                L.set_status(self.store, target, CONTROL_STATUS[kind], at=at, source='user', reason=(segs[j].get('text') or '')[:80])
                if kind == 'abandon':
                    run = X.active_run(self.store, target)       # stop what it is doing; the session stays for a reopening
                    if run: X.stop_run(self.store, run['id'], at=at, why='the user abandoned this work')
                    for p in relay.open_pending(self.store, at, target): self.store.patch(p['id'], {'status': 'cancelled'}, at=at, source='user')
            entry['status'] = L.status(self.store, target)
            done.append(entry)
        return done

    def dispatch(self, task, *, turn, at, message, thread_text=None, mode='session', readonly=False, share_from=None):
        """Reuse the task's active session (forward the new part) or start a new executor with an initial context."""
        run, reused, why = X.executor_for(self.store, task, at=at, turn=turn, mode=mode, readonly=readonly, share_from=share_from)
        wd = (self.store.get(task) or {}).get('data', {}).get('working_dir', '')
        busy = [r for r in self.running_nodes() if r != task and (self.store.get(r) or {}).get('data', {}).get('working_dir') == wd and wd]
        if busy: self.store.event(task, 'workdir_shared', at=at, source='ctm', data={'with': busy})   # one modifier per working dir (3.6)
        fork_of = (self.store.db.execute("select dst from edges where src=? and rel='forked_from'", (run,)).fetchone() or [None])[0]
        phrases = getattr(self, '_time_phrases', None)   # the message names a time ("last time", "the first version"): its attempts, for the executor to resolve
        attempts = C.attempts_text(self.store, task, at=at, phrases=phrases) if phrases else ''
        if fork_of:                                   # a query answered in a read-only fork of the task's session
            text, _ = C.forward_text(self.store, task, run=fork_of, turn=turn, at=at, readonly=True)
            return {'task': task, 'run': run, 'reused': False, 'fork_of': fork_of, 'why': why, 'forward': text + attempts, 'readonly': True}
        if not readonly and wd:                       # ctm.md entries this executor has not heard in the conversation (concept 3.5)
            self.sync_object_files(at, turn, need={'working_dir': wd, 'task': task, 'reused': bool(reused)})
        if reused:
            text, items = C.forward_text(self.store, task, run=run, turn=turn, at=at, readonly=readonly, thread_text=thread_text)
            text += attempts + ('' if readonly else self._proposal_section(task))
            tid = self.store.db.execute("select id from items where type='turn' and turn=? limit 1", (turn,)).fetchone()
            if tid: X.forward(self.store, run_id=run, item_id=tid[0], at=at, why="the user's new message about this task")
            for i in items: X.forward(self.store, run_id=run, item_id=i, at=at, why='set elsewhere, takes effect for this task')
            return {'task': task, 'run': run, 'reused': True, 'why': why, 'forward': text, 'readonly': readonly}
        text = C.initial_context(self.store, task, turn=turn, at=at, message=message, thread_text=thread_text, readonly=readonly) + attempts
        if not readonly: text += self._proposal_section(task)
        self.store.patch(run, {'contract_turn': turn, 'initial_context_chars': len(text)}, at=at, source='ctm')
        return {'task': task, 'run': run, 'reused': False, 'why': why, 'context': text, 'readonly': readonly}

    def _query(self, text, node, at, turn):
        if self.answer_queries:
            qid, res = Q.handle(self.store, question=text, node=node, at=at, turn=turn, model=self.light_model, route_model=self.light_model, embed=self.embed)
            return {'query': qid, 'node': node, **res}
        qid = self.store.add('query', {'question': text, 'answered': False}, at=at, source='ctm', turn=turn)
        self.store.link(qid, 'about', node or 'ROOT', at=at, source='ctm')
        return {'query': qid, 'node': node}

    def _relay(self, turn, at, placed, segs, dispatches, queries, asks, controls, replaced=(), planned=(), alternatives=None):
        """The conversation reply: how each segment was understood and arranged, with numbered items (5.1 step 4, 5.4)."""
        items = []
        for n in planned:                             # proposed subtasks wait for approval (S5)
            for c in self.store.children(n):
                if L.status(self.store, c) == 'proposed':
                    items.append({'text': 'Proposed subtask, waiting for approval: ' + (self.store.get(c)['data'].get('title') or ''), 'task': c})
        for old, new in replaced:                     # S8: the user sees which current item was replaced (e.g. back to an old plan)
            o, n = self.store.get(old), self.store.get(new)
            if o['type'] == 'decision':
                items.append({'text': f"Decision updated: \"{o['data'].get('statement', '')}\" -> \"{n['data'].get('statement', '')}\"",
                              'task': (self.store.about(new) or [None])[0], 'decision': new})
        for d in dispatches:
            if d.get('readonly'): continue                # shown with the query below
            alt = (alternatives or {}).get(d['task'])
            items.append({'text': ('Passed to the running executor' if d['reused'] else 'Dispatched a new executor') + f" ({d['why']})"
                          + (f"; it may also be: {', '.join(alt)}" if alt else ''), 'task': d['task']})
        for q in queries:
            items.append({'text': 'Answered as a query' + (': ' + (q.get('answer') or 'needs a read-only check')[:120] if self.answer_queries else ''), 'task': q.get('node'), 'query': q['query']})
        for c in controls:
            items.append({'text': f"{c['control']} -> status {c.get('status')}", 'task': c['node']})
        for a in asks:
            p = self.store.get(a)
            items.append({'text': 'Needs your decision: ' + (p['data'].get('what') or ''), 'task': (self.store.about(a) or [None])[0], 'pending': a})
        items = [dict(i, task=i['task'] if i.get('task') in self.tree.nodes else None) for i in items]
        _, text = relay.display(self.store, items=items, at=at, turn=turn, kind='reply') if items else ([], '')
        self.store.add('turn', {'role': 'ctm', 'text': text}, at=at, source='ctm', turn=turn)
        return text

    def planned_steps(self, node):
        """Subtasks the planner made for this work (proposals until approved or authorized)."""
        return [c for c in self.store.children(node) if (self.store.get(c) or {}).get('source') == 'planner']

    def sync_object_files(self, at, turn=None, need=None):
        """CTM's own record of object rules (concept 3.5): it writes, rewrites and removes ctm.md entries itself and proposes
        source annotations to the user; nothing of this goes into an executor's input. Entries become due when an executor that
        did not hear the rule is about to start (`need`), or when the work it was said in is finished. What was done since the
        last call that returned it is returned (dispatches inside a message accumulate)."""
        from . import objectfiles as OF
        out = OF.sync(self.store, at=at, turn=turn, write=self.write_object_files, need=need)
        for p in out['proposals']:
            relay.display(self.store, items=[{'text': p['text'], 'task': p['task'] if p['task'] in self.tree.nodes else None, 'pending': p['pending']}],
                          at=at, turn=turn, kind='pending')
        acc = self._object_acc
        for k in acc: acc[k] += out[k]
        if need is not None: return out
        self._object_acc = {'written': [], 'removed': [], 'proposals': [], 'withdrawn': []}
        return acc

    def memory_note(self, turn, replaced=()):
        """What CTM recorded from this message, for the conversation: the user sees it and can correct it."""
        label = {'constraint': 'constraint', 'guidance': 'guidance', 'environment': 'fact', 'decision': 'decision', 'overall_goal': 'overall goal'}
        lines = []
        for iid, typ, data in self.store.db.execute("select id, type, data from items where turn=? and source='user' and type in "
                                                    "('constraint','guidance','environment','decision','overall_goal') order by at", (turn,)).fetchall():
            d = json.loads(data); st = d.get('statement') or ''
            if not st: continue
            about = self.store.about(iid)
            obj = next((self.store.get(a) for a in about if a.startswith('OBJ:')), None)
            where = (f"object <{obj['data'].get('name')}>" if obj else 'global' if 'ROOT' in about or not about
                     else ', '.join(f'"{self.tree.nodes[a].title}"' for a in about if a in self.tree.nodes) or 'global')
            kind = {'rejected': 'rejected approach', 'questioned': 'questioned'}.get(d.get('type'), label[typ])
            lines.append(f"- {kind} ({where}): {st}")
        for old, new in replaced:
            o, n = self.store.get(old), self.store.get(new)
            if o and n: lines.append(f"- replaces: \"{o['data'].get('statement', '')}\" -> \"{n['data'].get('statement', '')}\"")
        return chr(10).join(lines)

    def _answered_proposal(self, pid, target, at):
        """The user answered CTM's proposal to annotate an object: the executor of `target` gets the proposal with the user's
        words, and does it if the user agreed (the answer is read by the executor, not by code)."""
        p = self.store.get(pid) or {}
        if p.get('data', {}).get('kind') != 'propose_annotation': return
        self.store.event(p['data'].get('constraint') or pid, 'annotation_answered', at=at, source='user', data={'pending': pid})
        self._proposal_answers.setdefault(target, []).append(p['data'].get('what', ''))

    def _proposal_section(self, task):
        got = self._proposal_answers.pop(task, [])
        if not got: return ''
        return NL2 + "## The user is answering CTM's proposals" + chr(10) + chr(10).join(f"- CTM's proposal: {t}" for t in got) + chr(10) + (
            "The user's answer is in the words above: if the user agrees, do it - write it as a constraint comment in this object's file "
            "(marked as a constraint, citing the user's decision and the date), and commit or not as the user says; if not, do not do it.")

    def _conditions_waiting(self, node):
        out = []
        for (dst, data) in self.store.db.execute("select dst, data from edges where src=? and rel='dep' and valid_to is null", (node,)):
            d = json.loads(data) if isinstance(data, str) else (data or {})
            if d.get('type') == 'conditional' and d.get('condition'):
                out.append({'successor': dst, 'title': (self.store.get(dst) or {}).get('data', {}).get('title'), 'condition': d['condition']})
        return out

    # ---- executor side ---------------------------------------------------------------------------------------------------
    def on_reply(self, turn, at, node, user_message, reply, *, tools=None, progress=None, run=None, contract=None, classify=False,
                 working_dir='', diff=None, check_completion=False, stop=None, active=None):
        """An executor answered (via the control layer). classify: run the control layer's stop judgment; diff: the run's file
        diff for the constraint-annotation check; check_completion: formal completion check when it reports completion."""
        if (self.store.get(node) or {}).get('type') == 'research':
            return self._research_reply(turn, at, node, reply, progress=progress, run=run, tools=tools, working_dir=working_dir)
        conds = self._conditions_waiting(node)          # later work waiting on a condition about this result (planner's steps)
        early_stop = None                               # the stop classification needs only the contract and the reply's end: run it alongside the summary
        if classify and stop is None and reply and node in self.tree.nodes:
            early_stop = _POOL.submit(K.classify_stop, contract or user_message, reply[-1500:], model=self.control_model)
        p = progress if progress is not None else (summarize(user_message, reply, tools, model=self.model,
                                                             conditions=conds)[0] if reply else None)
        for c in ((p or {}).get('conditions_met') or []) if conds else []:
            if isinstance(c, dict) and c.get('met') is True and c.get('successor') in {x['successor'] for x in conds}:
                L.condition_met(self.store, node, c['successor'], at=at, note=(c.get('why') or '')[:200])
        ro = (self.store.get(run) or {}).get('data', {}).get('mode') in ('readonly', 'fork') if run else False
        asked = (self.store.db.execute("select src from edges where rel='answered_by' and dst=? order by at desc limit 1", (run,)).fetchone() or [None])[0] if ro else None
        if node in self.tree.nodes and reply and not ro:  # a query's answer is the query's result, not progress of the work it asked about
            self.tree.touch(node, turn, at, 'agent: ' + reply[-200:])
        log = write_reply(self.store, self.tree, turn=turn, at=at, node=node, reply=reply, progress=p, model=self.model,
                          run_id=run, tools=tools, working_dir=working_dir, progress_about=asked)
        log['to_ctm'] = None
        log['progress'] = p                           # what CTM relays to the user (5.4)
        if node in self.tree.nodes and reply:         # the user's follow-up questions went to the executor with the message; its reply answers them
            for q in self.store.items('pending', about=node, at=at):
                if q['data'].get('kind') == 'question_to_reply' and q['data'].get('status', 'open') == 'open':
                    self.store.patch(q['id'], {'status': 'answered', 'by': 'executor_reply', 'run': log['run']}, at=at, source='executor')
        run_item = self.store.get(log['run'])
        if run_item and run_item['data'].get('mode') == 'single' and run_item['data'].get('status') == 'active':
            X.end_run(self.store, log['run'], 'the single call has answered', at=at)
        if run_item and run_item['data'].get('mode') in ('readonly', 'fork'):   # a read-only execution or fork answers and ends
            X.end_run(self.store, log['run'], 'the read-only query has been answered', at=at)
            q = self.store.db.execute("select src from edges where rel='answered_by' and dst=? order by at desc limit 1", (log['run'],)).fetchone()
            if q: self.store.patch(q[0], {'answer': ((p or {}).get('done') or reply or '')[:2000], 'answered': True}, at=at, source='executor')
            return log
        if p and p.get('done'): self.store.event(log['run'], 'progress_seen', at=at, source='ctm')
        if (tools if active is None else active) and log.get('run'):   # the executor used a tool this round (observed, for the budget)
            self.store.event(log['run'], 'activity', at=at, source='executor')
        tamper = X.constraint_tamper(diff) if diff else []
        if tamper and node in self.tree.nodes:        # edits to constraint annotations are out of bounds: escalate
            pid = self.store.add('pending', {'kind': 'out_of_scope', 'status': 'open', 'what': 'The executor deleted or edited constraint comments or ctm.md: ' + tamper[0][:200]},
                                 at=at, source='ctm', turn=turn)
            self.store.link(pid, 'about', node, at=at, source='ctm')
            relay.display(self.store, items=[{'text': self.store.get(pid)['data']['what'], 'task': node, 'pending': pid}], at=at, turn=turn, kind='pending')
            log['tamper'] = pid
        if (classify or stop) and node in self.tree.nodes and reply:
            if stop is None:
                stop, usage = early_stop.result() if early_stop is not None else                     K.classify_stop(contract or user_message, reply[-1500:], model=self.control_model)   # V3 (analysis-style) was worse on E7, kept V2 (11-18)
                log['calls'] += 1
            log['stop'] = stop
            to_ctm = X.handle_stop(self.store, run_id=log['run'], task=node, stop=stop, at=at, turn=turn)
            log['to_ctm'] = to_ctm
            if to_ctm is None:
                to_ctm = X.budget_check(self.store, log['run'], at=at)
                log['to_ctm'] = to_ctm
            if to_ctm and to_ctm['kind'] == 'completed':
                if check_completion:
                    comp, _ = K.check_completion(contract or user_message, reply, model=self.control_model); log['completion'] = comp; log['calls'] += 1
                    if not comp.get('complete', True):
                        self.store.event(log['run'], 'ask_complete', at=at, source='ctm', data=comp)
                        return log
                self.store.event(log['run'], 'request_done', at=at, source='executor', data={'turn': turn})
                relay.display(self.store, items=[{'text': 'Done: ' + ((p or {}).get('done') or '')[:200], 'task': node}], at=at, turn=turn, kind='result')
            if to_ctm and to_ctm['kind'] == 'failed':
                L.set_status(self.store, node, 'blocked', at=at, source='ctm', reason=to_ctm.get('reason', ''))
                relay.display(self.store, items=[{'text': 'Blocked: ' + to_ctm.get('reason', ''), 'task': node}], at=at, turn=turn, kind='result')
            if to_ctm and to_ctm['kind'] in ('question', 'decision', 'out_of_scope'):
                log['answer'] = self.on_executor_question(node, to_ctm, at=at, turn=turn)
        if node in self.tree.nodes and reply and not ro and not (log.get('to_ctm') or {}).get('kind') in ('question', 'decision', 'out_of_scope', 'failed'):
            self._open_items(node, p, log['run'], at=at, turn=turn)   # an escalated stop already put its question to the user
        if run_item and run_item['data'].get('mode') == 'session':
            waiting = bool(log.get('to_ctm') and log['to_ctm']['kind'] in ('question', 'decision', 'out_of_scope')
                           and (log.get('answer') or {}).get('by') == 'user')
            X.set_state(self.store, log['run'], 'waiting' if waiting else 'idle', at=at)
            X.context_check(self.store, log['run'], at=at, turn=turn)
        log['object_files'] = self.sync_object_files(at, turn)   # rules the reply's write-back recorded or replaced
        return log

    def _research_reply(self, turn, at, rid, reply, *, progress, run, tools, working_dir):
        """A research round's answer: run evidence, a brief progress entry, the conclusion appended to the research document."""
        ex = self.store.add('exchange', {'reply': reply or ''}, at=at, source='executor', turn=turn)
        if run: self.store.link(ex, 'in_run', run, at=at, source='ctm')
        if tools and run: D.record_file_versions(self.store, run=run, task=None, tools=tools, at=at, working_dir=working_dir)
        if progress:
            pid = self.store.add('progress', {k: progress.get(k) for k in ('done', 'changed', 'verified', 'open', 'failed')}, at=at, source='ctm', turn=turn, observed_at=at)
            self.store.link(pid, 'about', rid, at=at, source='ctm'); self.store.link(pid, 'summarizes', ex, at=at, source='ctm')
        r = self.store.get(rid)
        did = r['data'].get('doc')
        if not did:
            did = D.create_document(self.store, kind='research', title=r['data'].get('title') or rid, use_when="when this research's conclusions are needed", text='',
                                    task=None, run=run, at=at, source='executor')
            self.store.unlink(did, 'about', 'ROOT', at=at); self.store.link(did, 'about', rid, at=at, source='ctm')
            self.store.patch(rid, {'doc': did}, at=at, source='ctm')
        D.update_section(self.store, did, f'turn {turn}', (reply or '')[:20000], run=run, task=None, at=at, source='executor')
        if run: X.set_state(self.store, run, 'idle', at=at)
        return {'run': run, 'exchange': ex, 'research': rid, 'document': did, 'to_ctm': None, 'calls': 0, 'replaced': [], 'created': []}

    def _open_items(self, node, p, run, *, at, turn):
        """Concept 1.2 / 5.2 item 6: what a reply leaves for the user becomes numbered, referable pending items of this work; the
        user's reaction decides what they become. A new reply supersedes the work's earlier open items."""
        for q in self.store.items('pending', about=node, at=at):
            if q['data'].get('kind') == 'open_item' and q['data'].get('status', 'open') == 'open':
                self.store.patch(q['id'], {'status': 'superseded', 'by_run': run}, at=at, source='ctm')
        items = []
        for o in [str(x) for x in ((p or {}).get('open') or []) if str(x).strip()][:8]:
            pid = self.store.add('pending', {'kind': 'open_item', 'what': o[:400], 'status': 'open'}, at=at, source='ctm', turn=turn)
            self.store.link(pid, 'about', node, at=at, source='ctm'); items.append({'text': o[:400], 'task': node, 'pending': pid})
        if items:
            relay.display(self.store, items=items, at=at, turn=turn, kind='pending')

    def on_executor_question(self, task, to_ctm, *, at, turn):
        """Executor -> CTM (5.2 items 4, 5): a question is answered from memory (current items only); an optional step or a
        choice is decided by CTM only when the user's words, the decisions in force and CTM's understanding of the user settle
        it; otherwise, and for actions beyond the authorization, it becomes a pending item relayed to the user."""
        pend = self.store.get(to_ctm['pending'])
        what = pend['data'].get('what') or ''
        answer = self.ctm_answer(task, to_ctm['kind'], what, at)
        if answer:
            self.store.patch(pend['id'], {'status': 'answered', 'answer': answer['answer'], 'by': 'ctm'}, at=at, source='ctm')
            if L.status(self.store, task) == 'blocked': L.set_status(self.store, task, 'running', at=at, source='ctm', reason='CTM answered from memory')
            nid = self.store.add('notice', {'text': answer['answer']}, at=at, source='ctm', turn=turn)
            run = to_ctm.get('run')
            if run: X.forward(self.store, run_id=run, item_id=nid, at=at, why="CTM's answer to the executor's question")
            return answer
        relay.display(self.store, items=[{'text': what, 'task': task, 'pending': pend['id']}], at=at, turn=turn, kind='pending')
        return {'by': 'user'}

    def ctm_answer(self, task, kind, what, at):
        """What CTM can answer for an escalation without the user (read-only): information found in memory for a question; a
        decision only when the user's words, the decisions in force and the understanding of the user settle it."""
        if kind == 'question':
            ans, _ = recall_answer(self.store, task, at, [what], model=self.model, need=True, embed=self.embed)
            if ans and ans[0].get('found'): return {'by': 'ctm', 'answer': ans[0].get('answer'), 'basis': ans[0].get('basis')}
        elif kind == 'decision':
            words = [x['data'].get('text') for x in self.store.items('segment', about=task, at=at)][-6:]
            rules = [r['data'].get('statement') for n in [task] + self.store.ancestors(task, at) + ['ROOT']
                     for typ in ('constraint', 'decision') for r in self.store.items(typ, about=n, at=at, current_only=True)][-30:]
            out, _ = ask(DECIDE, {'executor_asks': what, 'user_words_for_this_work': words, 'constraints_and_decisions_in_force': rules,
                                  'understanding_of_user': self._understanding_of_user(at)}, model=self.model, effort='low', role='ctm-decide')
            if out.get('decide') and out.get('answer'): return {'by': 'ctm', 'answer': out['answer'], 'basis': out.get('basis')}
        return None

    # ---- maintenance ------------------------------------------------------------------------------------------------------
    def maybe_maintain(self, at, force=False):
        if last_maintenance(self.store) < 0 and not force:   # the first message sets the baseline of the first window
            self.store.event('ROOT', 'maintenance', at=at, source='maintenance', data={'baseline': True})
            return None
        if not force and (self.maintain_every is None or at - max(last_maintenance(self.store), 0) < self.maintain_every):
            return None
        ops, usage = maintain_store(self.store, self.tree, at, model=self.model)
        for op in ops or []:                              # messages maintenance moved now belong to their new work
            for t in op.get('moved') or []:
                self.assigned[t] = op['to']
        return ops
