"""The pilot: the user talks only to CTM in one conversation (concept model 1, 5); CTM delivers each message and pi sessions
execute. Everything CTM does runs on one worker thread (the store is written single-threaded); pi sessions report on their
own threads and hand results to the worker.

Records (outside Git, under the pilot directory): ctm.sqlite (CTM memory), conversation.jsonl (what the page shows),
events.jsonl (every message, delivery, correction, executor turn, control decision, model usage and timing), sessions/
(pi session files), logs/ (pi stderr)."""
import json
import os
import queue
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout
from pathlib import Path

from context_tree.ctm2 import execution as X
from context_tree.ctm2 import lifecycle as L
from context_tree.ctm2 import maintain_store as MS
from context_tree.ctm2 import model as MD
from context_tree.ctm2 import ui as UI
from context_tree.ctm2.pipeline import CTM

from context_tree.ctm2.store import Store
from context_tree.ctm2.tree import StoreTree

from .pi_rpc import PiSession
from .vectors import VectorCache

TREE_WAIT = 1.5   # seconds the page waits for a fresh tree before it gets the last one with live executor state

RECENT_TURNS = 6
CONTINUE_TEXT = 'Continue.'
MILESTONE_S = 600                    # a round longer than this writes the executor's words so far into the progress


class Pilot:
    def __init__(self, root, *, pi_command=None, ctm_options=None, maintain_hours=12.0):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        for d in ('sessions', 'logs', 'work', 'records'): (self.root / d).mkdir(exist_ok=True)
        self.pi_command = pi_command
        self.ctm_options = dict(ctm_options or {})
        self.maintain_hours = maintain_hours
        self.runs = {}                       # CTM run id -> PiSession
        self.activity = {}                   # run id -> {'task', 'tool', 't'} while the executor works
        self.tidying = set()                 # tasks whose executor replied while CTM writes the relay (about 15 s; shown on the tree)
        self.queued = []                     # requests waiting for a working directory another executor is changing
        self.dir_activity = {}               # working directory -> (until when an executor worked there, its run)
        self.milestone_at = {}               # run id -> time of its last milestone (long rounds, concept 5.2 item 4)
        self.subs = []                       # SSE subscriber queues
        self.items = self._load_items()      # conversation items shown on the page
        self.selection = None                # node the user selected in the tree (UI selection for the next message)
        self.turn_text, self.turn_reply, self.turn_node = {}, {}, {}
        for it in self.items:
            if it['kind'] == 'user': self.turn_text[it['turn']] = it['text']
            if it['kind'] == 'reply' and it.get('text'): self.turn_reply[it['turn']] = it['text']
            if it['kind'] == 'relay' and it.get('node'): self.turn_node[it['turn']] = it['node']
        self.last_reply = next((it['text'] for it in reversed(self.items) if it['kind'] == 'reply' and it.get('text')), '')
        self._events = open(self.root / 'events.jsonl', 'a', encoding='utf-8')
        self._conv = open(self.root / 'conversation.jsonl', 'a', encoding='utf-8')
        self.jobs = queue.Queue()
        self._tree_lock = threading.Lock(); self._tree_pending = False; self._tree_fut = None; self._last_tree = None
        self._ready = threading.Event()
        threading.Thread(target=self._work, daemon=True).start()
        self._ready.wait(60)

    # ---- worker -------------------------------------------------------------------------------------------------------
    def _work(self):
        self.store = Store(str(self.root / 'ctm.sqlite'))
        self.vectors = VectorCache(self.root / 'vectors.sqlite')       # object names after an import: not recomputed per restart
        opts = dict(maintain_every=self.maintain_hours * 3600, answer_queries=True, use_planner=True, embed=self.vectors.embed)
        opts.update(self.ctm_options)
        self.ctm = CTM(self.store, **opts)
        self.ctm.write_object_files = True             # CTM keeps its ctm.md records itself (concept 3.5)
        st = self.root / 'ctm-state.json'
        if st.exists():
            s = json.loads(st.read_text(encoding='utf-8'))
            self.ctm.current = s.get('current'); self.ctm.assigned = {int(k): v for k, v in (s.get('assigned') or {}).items()}
            self.selection = s.get('selection')
        self._ready.set()
        while True:
            fn, fut = self.jobs.get()
            try:
                r = fn()
                self.store.commit()                  # every job is durable (a crash must not lose memory)
                if fut: fut.set_result(r)
            except Exception as e:
                try: self.store.commit()
                except Exception: pass
                self.record('error', where=getattr(fn, '__name__', ''), error=repr(e))
                self.publish({'type': 'error', 'text': f'internal error: {e}'})
                if fut: fut.set_exception(e)

    def call(self, fn, timeout=600):
        fut = Future(); self.jobs.put((fn, fut))
        return fut.result(timeout)

    def later(self, fn):
        self.jobs.put((fn, None))

    def _save_state(self):
        (self.root / 'ctm-state.json').write_text(json.dumps({'current': self.ctm.current, 'selection': self.selection,
                                                               'assigned': {str(k): v for k, v in self.ctm.assigned.items()}},
                                                              ensure_ascii=False), encoding='utf-8')

    # ---- records and the page -----------------------------------------------------------------------------------------
    def _load_items(self):
        f = self.root / 'conversation.jsonl'
        if not f.exists(): return []
        out = []
        for line in f.read_text(encoding='utf-8').splitlines():
            try: out.append(json.loads(line))
            except ValueError: pass
        return out

    def record(self, kind, **data):
        self._events.write(json.dumps({'t': time.time(), 'kind': kind, **data}, ensure_ascii=False) + '\n'); self._events.flush()

    def add_item(self, item):
        item = dict(item, t=time.time(), i=len(self.items))
        self.items.append(item)
        self._conv.write(json.dumps(item, ensure_ascii=False) + '\n'); self._conv.flush()
        self.publish({'type': 'item', 'item': item})
        return item

    def publish(self, ev):
        for q in list(self.subs):
            try: q.put_nowait(ev)
            except queue.Full: pass

    def subscribe(self):
        q = queue.Queue(maxsize=5000); self.subs.append(q); return q

    def unsubscribe(self, q):
        if q in self.subs: self.subs.remove(q)

    # ---- the user's message -------------------------------------------------------------------------------------------
    def message(self, text):
        return self.call(lambda: self._message(text))

    def _next_turn(self):
        r = self.store.db.execute("select max(turn) from items where type='turn'").fetchone()[0]
        return max(r or 0, max(self.turn_text or {0: 0})) + 1

    def _recent(self, turn):
        ks = sorted(k for k in self.turn_text if k < turn)[-RECENT_TURNS:]
        return [{'user': self.turn_text[k], 'agent': self.turn_reply.get(k, ''), 'node': self.ctm.assigned.get(k)} for k in ks]

    def _message(self, text):
        turn, at = self._next_turn(), time.time()
        self.turn_text[turn] = text
        self.add_item({'kind': 'user', 'turn': turn, 'text': text, 'selection': self.selection})
        self._observe_outside_changes(at)
        maint = self.ctm.maybe_maintain(at - 1e-3)
        if maint: self._after_maintenance(maint, at)
        u0, t0 = len(MD.USAGE), time.time()
        sel = self.selection if self.selection in self.ctm.tree.nodes else None
        self.selection = None
        info = {}

        def after_dispatch(d):                        # executors start before the memory call (concept 5.1: memory after dispatch)
            info['dispatch_s'] = round(time.time() - t0, 1)
            self._delivered(turn, text, at, d, info)

        res = self.ctm.on_message(turn, at, text, recent=self._recent(turn), previous_reply=self.last_reply, working_dir='',
                                   ui_selection=sel, after_dispatch=after_dispatch)
        if 'dispatch_s' not in info:
            self._delivered(turn, text, at, {k: res.get(k) for k in ('node', 'dispatches', 'queries', 'controls')}, info)
        for pl in res.get('planned') or []:            # the planner's subtasks: proposals the user approves (authorized ones already run)
            self.add_item({'kind': 'plan', 'turn': turn, 'task': pl['task'], 'title': self._title(pl['task']), 'subtasks': pl['subtasks']})
        self._object_files(res.get('object_files'), turn)
        usage = [{'role': x['role'], 'model': x.get('model'), 'in': (x['usage'] or {}).get('prompt_tokens'),
                  'out': (x['usage'] or {}).get('completion_tokens'), 's': x.get('seconds')} for x in MD.USAGE[u0:]]
        w = res.get('write') or {}
        note = self.ctm.memory_note(turn, w.get('replaced') or [])     # what CTM recorded (not the arrangement, which the route line shows)
        if note or info.get('to') == 'memory':
            self.add_item({'kind': 'ctmnote', 'turn': turn, 'text': note or 'This was said to CTM, but no new entry was recorded; if it should be remembered, please say it another way.',
                           'open': info.get('to') == 'memory'})
        self.record('message', turn=turn, text=text, selection=sel, node=info.get('node'), to=info.get('to'), alternatives=info.get('alts'),
                    dispatched=info.get('dispatched'), dispatch_seconds=info.get('dispatch_s'), seconds=round(time.time() - t0, 1),
                    queries=[{k: v for k, v in q.items() if k in ('query', 'node', 'from_memory', 'kind')} for q in res.get('queries') or []],
                    controls=[{k: v for k, v in c.items() if k in ('control', 'node', 'status')} for c in res.get('controls') or []],
                    memory=w.get('created'), replaced=w.get('replaced'), usage=usage, relay=res.get('relay'))
        self._save_state()
        self.publish({'type': 'tree'})
        return {'turn': turn, 'node': info.get('node')}

    def _delivered(self, turn, text, at, d, info):
        node = d.get('node')
        self.turn_node[turn] = node
        deliv = d.get('delivery') or {}
        d0 = ([x for x in deliv.get('deliveries') or [] if isinstance(x, dict)] or [{}])[0]
        alts = [a for a in (d0.get('alternatives') or []) if isinstance(a, str) and a in self.ctm.tree.nodes and a != node]
        dispatched = [{'task': x['task'], 'title': self._title(x['task']), 'run': x['run'], 'reused': x.get('reused'),
                       'readonly': x.get('readonly'), 'research': x.get('research')} for x in d.get('dispatches') or []]
        answers = [{'query': q['query'], 'answer': q.get('answer')} for q in d.get('queries') or [] if q.get('from_memory')]
        how = '; '.join(('read-only query' if x['readonly'] else 'continuing executor' if x['reused'] else 'new executor') + f" \"{x['title']}\"" for x in dispatched)
        if any(q.get('from_memory') for q in d.get('queries') or []): how = (how + '; ' if how else '') + 'answered from memory'
        if any(q.get('ask') for q in d.get('queries') or []): how = (how + '; ' if how else '') + 'answering needs a change of state, so I ask you first'
        if d0.get('to') == 'memory': how = (how + '; ' if how else '') + 'recorded by CTM itself, not sent to an executor'
        info.update(node=node, to=d0.get('to'), alts=alts, dispatched=dispatched)
        self.add_item({'kind': 'relay', 'turn': turn, 'text': how, 'node': node, 'title': self._title(node), 'to': d0.get('to'),
                       'alternatives': [{'id': a, 'title': self._title(a)} for a in alts[:2]], 'dispatched': dispatched,
                       'answers': answers, 'seconds': info.get('dispatch_s')})
        for c in d.get('controls') or []:
            if c.get('control') in ('pause', 'stop', 'abandon'):
                run = X.active_run(self.store, c.get('node'))
                if run and run['id'] in self.runs: self._abort(run['id'])
            if c.get('forward'):
                run = X.active_run(self.store, c.get('node'))
                if run: self._send(run['id'], c['forward'], turn, c.get('node'))
        for q in d.get('queries') or []:              # a query no work's session can answer: a fresh read-only executor
            if not q.get('from_memory') and not q.get('ask') and not q.get('node'):
                rid = self.store.add('run', {'mode': 'readonly', 'status': 'active', 'state': 'working', 'started_turn': turn,
                                             'contract': 'read only: do not change any file, configuration or external state'}, at=at, source='ctm', turn=turn)
                self.store.link(rid, 'serves', q['query'], at=at, source='ctm'); self.store.link(q['query'], 'answered_by', rid, at=at, source='ctm')
                ask_text = chr(10).join(['(Read-only query: only answer, change nothing.)', text, '', 'You could look at: ' + (q.get('readonly_plan') or '')])
                self._send(rid, ask_text, turn, q['query'], readonly=True)
        for x in d.get('dispatches') or []:
            self._send(x['run'], x.get('context') or x.get('forward') or text, turn, x['task'], readonly=bool(x.get('readonly')),
                       fork_of=x.get('fork_of'), research=bool(x.get('research')))
        self.store.commit()

    def _title(self, n):
        if not n: return None
        if n in self.ctm.tree.nodes: return self.ctm.tree.nodes[n].title
        r = self.store.get(n)
        return (r or {}).get('data', {}).get('title') or (r or {}).get('data', {}).get('question', '')[:40] or n

    # ---- executors ----------------------------------------------------------------------------------------------------
    def _session_file(self, run_id):
        return ((self.store.get(run_id) or {}).get('data') or {}).get('session_file')

    def _cwd(self, task):
        """The executor runs in the task's working directory (CTM decides it per work). A work that belongs to no project gets a
        scratch directory of its own under the pilot root, recorded as its working directory so its parts use it too."""
        r = self.store.get(task) or {}
        wd = (r.get('data') or {}).get('working_dir')
        if wd and Path(wd).exists(): return wd
        scratch = self.root / 'work' / (task or '_none'); scratch.mkdir(parents=True, exist_ok=True)
        scratch = str(scratch).replace(chr(92), '/')
        if r and r.get('type') in ('task', 'goal'):
            self.store.patch(task, {'working_dir': scratch}, at=time.time(), source='ctm')
            if task in self.ctm.tree.nodes: self.ctm.tree.nodes[task].working_dir = scratch
        return scratch

    def _observe_outside_changes(self, at, days=14):
        """Changes to known files that no executor made (concept S10): a version with the user as its source, and a notice to
        the executors whose work involves the file. A change while an executor was working in that directory is its own
        (executors also change files through commands, which leave no write record). Observation only, no judgment."""
        import os
        from context_tree.ctm2 import documents as D
        rows = [r for r in self.store.db.execute(
            "select f.id, f.data, (select max(v.at) from items v join edges e on e.src=v.id and e.rel='version_of' and e.dst=f.id) "
            "from items f where f.type='file'").fetchall() if r[2] and r[2] > at - days * 86400]   # files with a recent version
        for fid, data, last in rows[:400]:
            d = json.loads(data); path = d.get('path') or ''
            try: m = os.path.getmtime(path)
            except OSError: continue
            if last is None or m <= last + 2: continue
            key = MS.wd_key(d.get('working_dir') or os.path.dirname(path))
            act = self.dir_activity.get(key)
            if act and m <= act[0] + 2:                # an executor was working there then: its change
                D.observe_file_change(self.store, path=path, working_dir=d.get('working_dir') or '', at=at, source='executor', by_run=act[1])
            else:
                D.observe_file_change(self.store, path=path, working_dir=d.get('working_dir') or '', at=at, source='user')
                self.record('outside_change', path=path)

    def _busy_in(self, cwd, exclude=None):
        """A modifying executor working in this directory now (concept 3.6: one modifying executor per working directory)."""
        key = MS.wd_key(cwd)
        for rid, s in self.runs.items():
            if rid != exclude and s.alive and s.busy and getattr(s, 'modifies', False) and MS.wd_key(getattr(s, 'cwd', '')) == key:
                return s
        return None

    def _drain(self, cwd):
        """The directory is free again: send the next queued request for it."""
        for q in list(self.queued):
            if MS.wd_key(q['cwd']) == MS.wd_key(cwd) and not self._busy_in(q['cwd'], exclude=q['run_id']):
                self.queued.remove(q)
                self.record('dequeued', run=q['run_id'], task=q['task'], turn=q['turn'])
                self._send(q['run_id'], q['text'], q['turn'], q['task'], readonly=q['readonly'], fork_of=q['fork_of'], research=q['research'])
                return

    def _send(self, run_id, text, turn, task, readonly=False, fork_of=None, research=False):
        sess = self.runs.get(run_id)
        modifies = not (readonly or research)          # research executors only read the project
        cwd = self._cwd(task)
        other = self._busy_in(cwd, exclude=run_id) if modifies else None
        if other:                                      # another executor is changing the same directory: wait for its round
            self.queued.append({'run_id': run_id, 'text': text, 'turn': turn, 'task': task, 'readonly': readonly, 'fork_of': fork_of,
                                'research': research, 'cwd': cwd})
            self.record('queued', run=run_id, task=task, turn=turn, behind=other.run_id, cwd=cwd)
            self.add_item({'kind': 'notice', 'turn': turn, 'task': task,
                           'text': f"\"{self._title(task)}\" waits for \"{self._title(other.task)}\": both change files in the same directory ({cwd}), "
                                   f"and only one executor changes it at a time; it starts when that round ends."})
            X.set_state(self.store, run_id, 'waiting', at=time.time())
            return
        if not (sess and sess.alive):
            fork_file = self._session_file(fork_of) if fork_of else None
            sess = PiSession(cwd=self._cwd(task), session_dir=str(self.root / 'sessions'), name=self._title(task) or '',
                             session_file=self._session_file(run_id), fork_from=fork_file, readonly=readonly,
                             log_path=str(self.root / 'logs' / f'{run_id}.log'), command=self.pi_command,
                             on_event=self._on_event, on_settled=self._on_settled, on_dialog=self._on_dialog, on_exit=self._on_exit)
            sess.run_id, sess.task, sess.cwd, sess.modifies = run_id, task, cwd, modifies
            self.runs[run_id] = sess
        self.activity[run_id] = {'task': task, 'tool': None, 't': time.time()}
        if not sess.busy: sess.started_at = time.time(); self.milestone_at.pop(run_id, None)
        if modifies: self.dir_activity[MS.wd_key(cwd)] = (time.time() + 1e9, run_id)     # working now: until it settles
        self.record('send', turn=turn, run=run_id, task=task, readonly=readonly, fork_of=fork_of, chars=len(text), text=text[:20000], steer=sess.busy)
        try:
            r = sess.prompt(text, turn)
            if r and not r.get('success'):
                self.add_item({'kind': 'notice', 'turn': turn, 'run': run_id, 'text': f"The executor rejected this input: {r.get('error')}"})
            if not self._session_file(run_id):
                st = sess.state()
                if st.get('sessionFile'):
                    self.store.patch(run_id, {'session_file': st['sessionFile']}, at=time.time(), source='ctm')
        except Exception as e:
            self.add_item({'kind': 'notice', 'turn': turn, 'run': run_id, 'text': f'The executor did not respond: {e}'})
        X.set_state(self.store, run_id, 'working', at=time.time())
        self.publish({'type': 'tree'})

    def _abort(self, run_id):
        sess = self.runs.get(run_id)
        if sess and sess.alive and sess.busy:
            try: sess.abort()
            except Exception: pass

    def _on_event(self, sess, ev):                 # reader thread: executor activity is shown on the tree, not in the conversation
        if ev.get('type') == 'tool_execution_start':
            self.activity[sess.run_id] = {'task': sess.task, 'tool': ev.get('toolName'), 't': time.time()}
            self.publish({'type': 'activity', 'run': sess.run_id, 'task': sess.task, 'tool': ev.get('toolName')})
            now = time.time()
            if now - self.milestone_at.get(sess.run_id, getattr(sess, 'started_at', now)) >= MILESTONE_S and sess._last_text:
                self.milestone_at[sess.run_id] = now     # a long round: its own words so far become progress (no summary call)
                text, turn = sess._last_text[-600:], sess.turn
                self.later(lambda: self._milestone(sess, text, turn, now))

    def _milestone(self, sess, text, turn, at):
        X.milestone(self.store, run_id=sess.run_id, task=sess.task, summary={'done': "(mid-execution, the executor's words) " + text, 'open': []}, at=at, turn=turn)
        self.record('milestone', run=sess.run_id, task=sess.task, chars=len(text))
        self.publish({'type': 'tree'})

    def _on_dialog(self, sess, req):
        item = {'kind': 'dialog', 'run': sess.run_id, 'task': sess.task, 'title': self._title(sess.task), 'request': req, 'answered': False}
        self.later(lambda: self.add_item(item))

    def _on_exit(self, sess, code):
        def job():
            try: self._exited(sess, code)
            finally: self._drain(getattr(sess, 'cwd', ''))
        self.later(job)

    def _exited(self, sess, code):
        if self.runs.get(sess.run_id) is sess: self.runs.pop(sess.run_id, None)
        self.record('executor_exit', run=sess.run_id, code=code)
        if code: self.add_item({'kind': 'notice', 'run': sess.run_id, 'text': f'The executor process exited ({code}); see logs/{sess.run_id}.log'})

    def _on_settled(self, sess, result):
        if getattr(sess, 'modifies', False):           # the directory's executor stopped working now
            self.dir_activity[MS.wd_key(getattr(sess, 'cwd', ''))] = (time.time(), sess.run_id)
        def job():
            try: self._settled(sess, result)
            finally: self._drain(getattr(sess, 'cwd', ''))
        self.later(job)

    def _settled(self, sess, r):
        turn, run_id, task = r['turn'], sess.run_id, sess.task
        at = time.time()
        reply = r.get('reply') or ''
        tools = [{'name': x['name'], 'path': x['path'], 'success': x['success']} for x in r.get('tools') or [] if x.get('path')]
        for ex in self._keep_ctm_md_local([x for x in tools if x['name'] in ('edit', 'write', 'Edit', 'Write')]):
            self.record('ctm_md_excluded', run=run_id, exclude=ex)
        if reply: self.turn_reply[turn] = reply; self.last_reply = reply
        self.activity.pop(run_id, None)
        stats = {}
        try: stats = sess.stats()
        except Exception: pass
        if stats.get('tokens'):
            self.store.patch(run_id, {'tokens': (stats.get('contextUsage') or {}).get('tokens') or 0}, at=at, source='ctm')
        self.record('reply', turn=turn, run=run_id, task=task, chars=len(reply), reply=reply[:20000], tools=list(r.get('tools') or [])[:60],
                    aborted=r.get('aborted'), session_tokens=stats.get('tokens'), cost=stats.get('cost'))
        title = self._title(task)
        if r.get('aborted'):
            X.set_state(self.store, run_id, 'idle', at=at)
            self.add_item({'kind': 'notice', 'turn': turn, 'text': f'The execution of "{title}" stopped'})
            self.publish({'type': 'tree'}); return
        u0 = len(MD.USAGE)
        self.tidying.add(task); self.publish({'type': 'tree'})
        try:
            log = self.ctm.on_reply(turn, at, task, self.turn_text.get(turn, ''), reply, tools=tools, run=run_id,
                                    classify=not sess.readonly, working_dir=self._cwd(task), active=bool(r.get('tools')),
                                    diff=self._removed_lines(r.get('tools') or []))
        finally:
            self.tidying.discard(task)
        self._object_files(log.get('object_files'), turn)
        if log.get('tamper'):                          # the executor removed or changed a constraint annotation: the user decides
            what = (self.store.get(log['tamper']) or {}).get('data', {}).get('what') or ''
            self.add_item({'kind': 'pending', 'turn': turn, 'run': run_id, 'task': task, 'title': self._title(task), 'text': what, 'type': 'out_of_scope'})
        usage = [{'role': x['role'], 'in': (x['usage'] or {}).get('prompt_tokens'), 's': x.get('seconds')} for x in MD.USAGE[u0:]]
        stop, to, p = log.get('stop') or {}, log.get('to_ctm'), log.get('progress') or {}
        self.record('control', turn=turn, run=run_id, stop=stop, to_ctm=to, answer=log.get('answer'), progress=p, usage=usage)
        if sess.readonly:                             # a query: the answer is for the user (the query panel of concept 5.3)
            self.add_item({'kind': 'ctm', 'turn': turn, 'task': task, 'title': title, 'query': True,
                           'text': p.get('done') or reply[:600], 'detail': reply})
        elif stop.get('action') == 'auto_continue' and to is None:
            self._send(run_id, CONTINUE_TEXT, turn, task)           # within the contract: not the user's business
        elif to and to.get('kind') in ('question', 'decision', 'out_of_scope'):
            if p.get('done'): self.add_item({'kind': 'ctm', 'turn': turn, 'task': task, 'title': title, 'text': self._relay_text(p)})
            ans = log.get('answer') or {}
            if ans.get('by') == 'ctm' and ans.get('answer'):
                self.add_item({'kind': 'ctm', 'turn': turn, 'task': task, 'title': title, 'proxy': True,
                               'text': f"The executor of \"{title}\" asked something; I answered for you from what you said before: {ans['answer']}"})
                self._send(run_id, f"(CTM's answer from memory) {ans['answer']}", turn, task)
            else:
                what = (self.store.get(to.get('pending')) or {}).get('data', {}).get('what') or ''
                self.add_item({'kind': 'pending', 'turn': turn, 'run': run_id, 'task': task, 'title': title, 'text': what, 'type': to['kind']})
        elif to and to.get('kind') == 'failed':
            self.add_item({'kind': 'pending', 'turn': turn, 'run': run_id, 'task': task, 'title': title,
                           'text': f"The execution is blocked ({to.get('reason')}). {self._relay_text(p)} Please decide what to do.", 'type': 'failed'})
        else:
            done = bool(to and to.get('kind') == 'completed')
            self.add_item({'kind': 'ctm', 'turn': turn, 'task': task, 'title': title, 'done': done, 'text': self._relay_text(p) or reply[:600]})
        self._save_state()
        self.publish({'type': 'tree'})

    @staticmethod
    def _keep_ctm_md_local(tools):
        """Safety net: an executor wrote a ctm.md anyway (ctm.md is CTM's own, executors only read it): the repository's local
        exclude list gets it, so that no 'git add' takes it into a commit. Local only; nothing is committed."""
        from context_tree.ctm2.objectfiles import keep_local
        return [ex for ex in (keep_local(t.get('path')) for t in tools
                              if Path(str(t.get('path') or '')).name.lower() == 'ctm.md' and t.get('success') is not False
                              and Path(str(t.get('path'))).parent.is_dir()) if ex]

    @staticmethod
    def _removed_lines(tools):
        """Lines the executor's edits removed or changed (old text not kept in the new text), as '-' diff lines, for the check
        of constraint annotations and ctm.md entries (concept 3.5). Files rewritten whole or changed by commands are not seen."""
        out = []
        for t in tools:
            if t.get('name') != 'edit': continue
            a = t.get('args') or {}
            for e in (a.get('edits') if isinstance(a.get('edits'), list) else [a]):
                if not isinstance(e, dict): continue
                new = set((e.get('newText') or '').splitlines())
                out += ['-' + l for l in (e.get('oldText') or '').splitlines() if l not in new]
        return chr(10).join(out)

    @staticmethod
    def _relay_text(p):
        """CTM's relay of an executor turn (concept 5.4): what was done, changed, verified, failed, and what is open for the user."""
        if not p: return ''
        parts = [p.get('done') or '']
        ch = [c for c in p.get('changed') or [] if c]
        if ch: parts.append('Changed: ' + ', '.join(str(c) for c in ch[:8]) + (', ...' if len(ch) > 8 else ''))
        if p.get('verified'): parts.append('Verified: ' + str(p['verified']))
        fl = p.get('failed')
        if fl: parts.append('Did not work: ' + ('; '.join(str(x) for x in fl) if isinstance(fl, list) else str(fl)))
        op = [o for o in p.get('open') or [] if o]
        if op: parts.append('For you to decide, or not done yet: ' + ''.join(f'{chr(10)}{i}. {o}' for i, o in enumerate(op, 1)))   # numbered as the stored items
        return chr(10).join(x for x in parts if x)

    # ---- executor records (read-only, on request; each view is recorded: it measures whether the relay was enough) -----
    def export_record(self, run_id):
        return self.call(lambda: self._export_record(run_id), timeout=120)

    def _export_record(self, run_id):
        out = self.root / 'records' / f'{run_id}.html'; out.parent.mkdir(exist_ok=True)
        sess = self.runs.get(run_id)
        tmp = None
        if not (sess and sess.alive):
            sf = self._session_file(run_id)
            if not sf: return None
            tmp = sess = PiSession(cwd=str(self.root), session_dir=str(self.root / 'sessions'), session_file=sf,
                                   log_path=str(self.root / 'logs' / f'{run_id}-export.log'), command=self.pi_command)
        try:
            r = sess.send({'type': 'export_html', 'outputPath': str(out)}, timeout=60)
        finally:
            if tmp: tmp.close()
        self.record('view_record', run=run_id, ok=bool(r and r.get('success')))
        return str(out) if r and r.get('success') and out.exists() else None

    # ---- the user's edits (corrections are recorded: they measure the correction burden) ---------------------------
    def ui(self, op, **kw):
        return self.call(lambda: self._ui(op, **kw))

    def _object_files(self, out, turn):
        """What CTM did with its own ctm.md records; its proposals to annotate the code wait for the user's answer."""
        if not out: return
        for rule, f in out.get('written') or []: self.record('ctm_md', turn=turn, rule=rule, file=f, action='written')
        for rule, f in out.get('removed') or []: self.record('ctm_md', turn=turn, rule=rule, file=f, action='removed')
        for w in out.get('withdrawn') or []:          # its rule was replaced or withdrawn before the user answered
            for it in self.items:
                if it.get('kind') == 'pending' and it.get('pending') == w['pending']: it['withdrawn'] = True
            self.add_item({'kind': 'notice', 'turn': turn, 'text': f"CTM withdrew a proposal (the rule no longer holds; no answer needed): {w['text']}"})
        for p in out.get('proposals') or []:
            task = p['task'] if p['task'] in self.ctm.tree.nodes else None
            self.add_item({'kind': 'pending', 'turn': turn, 'task': task, 'title': self._title(task) if task else '',
                           'text': p['text'], 'type': 'proposal', 'pending': p['pending']})

    def _ui(self, op, **kw):
        at = time.time()
        node = kw.get('node')
        out = {'ok': True}
        if op == 'select':
            self.selection = node if node in self.ctm.tree.nodes else None
        elif op == 'rename':
            UI.rename(self.store, node, kw['title'], at=at)
        elif op == 'purpose':
            UI.set_purpose(self.store, node, kw['purpose'], at=at)
        elif op == 'move':
            UI.move(self.store, node, kw.get('parent') or None, at=at)
        elif op == 'status':
            UI.set_status(self.store, node, kw['status'], at=at)
            if kw['status'] in ('abandoned', 'paused'):
                run = X.active_run(self.store, node)
                if run: self._abort(run['id'])
        elif op == 'stop':
            self._abort(kw['run'])
        elif op == 'reattach':                       # this message belongs to another work (memory only)
            self._reattach(int(kw['turn']), node, at)
        elif op == 'redirect':                       # deliver this message to another work instead
            out = self._redirect(int(kw['turn']), node, at)
        elif op == 'maintain':
            ops = self.ctm.maybe_maintain(at, force=True) or []
            self._after_maintenance(ops, at)
            out['ops'] = len(ops)
        elif op == 'approve':                        # the user approves the planner's proposed subtasks; the executable ones start
            from context_tree.ctm2.planner import approve
            steps = self.ctm.planned_steps(node)
            approve(self.store, [n for n in [node] + steps if L.status(self.store, n) == 'proposed'], at=at)
            ev = [e for e in self.store.events_of(node) if e['kind'] == 'plan_requested']
            turn = (ev[-1]['data'] or {}).get('turn') if ev else max(self.turn_text or {0: ''})
            for c in steps:
                if L.status(self.store, c) == 'ready' and not X.active_run(self.store, c):
                    d = self.ctm.dispatch(c, turn=turn, at=at, message=self.turn_text.get(turn, ''))
                    self._send(d['run'], d.get('context') or d.get('forward') or '', turn, c)
            for it in self.items:
                if it['kind'] == 'plan' and it.get('task') == node: it['approved'] = True
        elif op == 'merge':                          # this work is the same as another one: merged into it
            UI.merge(self.store, kw['into'], node, at=at)
        elif op == 'create':                         # a node the user creates is authoritative, not a proposal
            out['node'] = UI.create_task(self.store, self.ctm.tree, kw['title'], kw.get('purpose') or '', kw.get('parent') or None, at=at,
                                         working_dir=kw.get('working_dir') or (self.ctm.tree.nodes[kw['parent']].working_dir if kw.get('parent') in self.ctm.tree.nodes else ''))
        elif op == 'split':                          # some of the work's messages are another work: a new sibling with them
            UI.split(self.store, node, [{'title': kw['title'], 'purpose': kw.get('purpose') or '', 'segments': kw.get('segments') or []}], at=at)
        elif op == 'move_constraint':
            UI.move_constraint(self.store, kw['constraint'], node, at=at)
        elif op == 'drop_inherited':
            UI.drop_inherited_constraint(self.store, node, kw['constraint'], at=at)
        elif op == 'constraint_kind':
            UI.change_constraint_kind(self.store, kw['constraint'], kw['kind'], at=at, obj=kw.get('object'),
                                      working_dir=kw.get('working_dir') or '')
        elif op == 'edit_root':
            out['item'] = UI.edit_root_item(self.store, kw['item'], kw['text'], at=at)
        elif op == 'add_preference':                 # the user states a preference or global rule on the root
            from context_tree.ctm2 import root as R
            out['item'] = R.add_preference(self.store, kw['text'], at=at, source='user')
        elif op == 'edit_doc':
            out['result'] = UI.edit_document(self.store, kw['doc'], kw.get('section'), kw['text'], at=at, model=self.ctm.model)
        elif op == 'dialog':
            sess = self.runs.get(kw['run'])
            ans = {k: kw[k] for k in ('value', 'confirmed', 'cancelled') if k in kw}
            if sess: sess.answer_dialog(kw['id'], **ans)
            for it in self.items:
                if it['kind'] == 'dialog' and it['request'].get('id') == kw['id']: it['answered'] = True
        else:
            return {'ok': False, 'error': f'unknown op {op}'}
        self.ctm.tree = StoreTree(self.store)
        self.record('ui', op=op, **{('new_kind' if k == 'kind' else k): v for k, v in kw.items() if k != 'title'}, title=kw.get('title'))
        self._save_state()
        self.publish({'type': 'tree'})
        if op not in ('select', 'stop'): self._object_files(self.ctm.sync_object_files(at), None)   # a UI edit may add or replace an object rule
        return out

    def _segments(self, turn):
        return [r['id'] for r in self.store.items('segment') if r['turn'] == turn]

    def _reattach(self, turn, node, at):
        for sg in self._segments(turn):
            UI.reattach_segment(self.store, sg, node, at=at)
        self.ctm.assigned[turn] = node; self.turn_node[turn] = node
        self.ctm.current = node                      # the user's correction makes it the work being talked about
        self.add_item({'kind': 'notice', 'turn': turn, 'text': f'Turn {turn} moved to "{self._title(node)}"'})

    def _redirect(self, turn, node, at):
        for rid, sess in list(self.runs.items()):    # stop the executor that got this message
            if sess.turn == turn and sess.busy and sess.task != node: self._abort(rid)
        self._reattach(turn, node, at)
        self.ctm.tree = StoreTree(self.store)
        d = self.ctm.dispatch(node, turn=turn, at=at, message=self.turn_text.get(turn, ''))
        self._send(d['run'], d.get('context') or d.get('forward') or self.turn_text.get(turn, ''), turn, node,
                   readonly=bool(d.get('readonly')), fork_of=d.get('fork_of'))
        return {'ok': True, 'run': d['run']}

    def _after_maintenance(self, ops, at):
        self.record('maintenance', ops=ops)
        if ops:
            self.add_item({'kind': 'notice', 'text': 'Maintenance tidied the tree: ' + ', '.join(sorted({o.get('op', '') for o in ops}))})
        self.ctm.tree = StoreTree(self.store)

    # ---- the tree for the page ----------------------------------------------------------------------------------------
    def tree(self):
        """The tree for the page. The worker thread (the only one using the store) can be busy for minutes with CTM's calls
        after a reply; then the last tree is returned with the executors' live state, and 'ctm_busy' tells the page."""
        fut = None
        with self._tree_lock:
            if not self._tree_pending:                # one tree job in the queue at a time
                self._tree_pending = True; fut = Future(); self.jobs.put((self._tree_job, fut))
            else:
                fut = self._tree_fut
            self._tree_fut = fut
        try:
            return dict(fut.result(TREE_WAIT), ctm_busy=False)
        except FutureTimeout:
            snap = self._last_tree or {'nodes': [], 'current': None, 'selection': self.selection, 'pending': []}
            return dict(snap, nodes=[self._live(n) for n in snap['nodes']], selection=self.selection, ctm_busy=True)

    def _tree_job(self):
        try:
            self._last_tree = self._tree(); return self._last_tree
        finally:
            with self._tree_lock: self._tree_pending = False

    def _live(self, n):
        """A node of the last tree with its executor's state now (kept in memory, not in the store)."""
        sess = self.runs.get(n.get('run')) if n.get('run') else None
        act = self.activity.get(n.get('run')) if n.get('run') else None
        return dict(n, busy=bool(sess and sess.busy), tool=(act or {}).get('tool'), tidying=n['id'] in self.tidying)

    def _tree(self):
        nodes = []
        for nid, n in self.ctm.tree.nodes.items():
            run = X.active_run(self.store, nid)
            sess = self.runs.get(run['id']) if run else None
            sf = (run['data'].get('session_file') if run else None) or ''
            act = self.activity.get(run['id']) if run else None
            nodes.append({'id': nid, 'title': n.title, 'purpose': n.purpose, 'parent': n.parent, 'status': L.status(self.store, nid),
                          'kind': n.kind, 'last': n.last_time, 'working_dir': n.working_dir,
                          'summarized': bool(n.kind == 'goal' and (self.store.get(nid) or {}).get('data', {}).get('summarized')),
                          'run': run['id'] if run else None, 'busy': bool(sess and sess.busy), 'tool': (act or {}).get('tool'), 'tidying': nid in self.tidying,
                          'session': Path(sf).stem.split('_')[-1][:8] if sf else None})
        pend = [{'id': p['id'], 'what': p['data'].get('what'), 'about': (self.store.about(p['id']) or [None])[0]}
                for p in self.store.items('pending', current_only=True) if p['data'].get('status', 'open') == 'open'][-20:]
        return {'nodes': nodes, 'current': self.ctm.current, 'selection': self.selection, 'pending': pend}

    # ---- views of memory for the page (concept 1.2, 3.7): node pages, root, documents, query panel, execution view -------
    def view(self, kind, ident=None):
        """A read-only view for the right panel; its errors are shown in the panel, not in the conversation."""
        def job():
            try: return self._view(kind, ident)
            except Exception as e:
                self.record('error', where=f'view:{kind}', error=repr(e))
                return {'error': f'this view failed: {e}'}
        return self.call(job, timeout=60)

    def _view(self, kind, ident):
        from context_tree.ctm2 import views as V, query as Q, root as R
        st = self.store
        if kind == 'page' and ident == 'ROOT':
            ents = []
            for typ, label in (('persona', 'Assistant settings'), ('user_understanding', "CTM's understanding of you (inferred)"), ('overall_goal', 'Overall goals'),
                               ('constraint', 'Preferences and global constraints'), ('environment', 'Common environments')):
                for r in st.items(typ, about='ROOT', current_only=True) if typ in ('constraint', 'environment') else st.items(typ, current_only=True):
                    d = r['data']
                    ents.append({'id': r['id'], 'type': typ, 'label': label, 'text': d.get('text') or d.get('statement') or '',
                                 'evidence': d.get('evidence'), 'confidence': d.get('confidence'), 'source': r['source']})
            return {'id': 'ROOT', 'kind': 'root', 'title': 'Root (global)', 'entries': ents, 'understanding': R.understanding_text(st)}
        if kind == 'page':
            if ident not in self.ctm.tree.nodes: return {'error': 'no such node'}
            p = V.node_page(st, ident)
            p['exchange'] = V.exchange_record(st, ident)[-80:]
            p['segments'] = [{'id': r['id'], 'turn': r['turn'], 'text': (r['data'].get('text') or '')[:300]} for r in st.items('segment', about=ident)][-60:]
            rel = p.get('relations') or {}
            ids = {x for v in rel.values() for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)}
            p['titles'] = {x: self._title(x) for x in ids}
            p['status_history'] = [{'at': e['at'], 'kind': e['kind'], 'data': e['data']} for e in p.get('status_history') or []][-20:]
            return p
        if kind == 'doc':
            return V.document_page(st, ident) if st.get(ident) else {'error': 'no such document'}
        if kind == 'queries':
            return {'items': [dict(q, about_titles=[self._title(a) for a in q.get('about') or []]) for q in Q.panel(st, limit=40)][::-1]}
        if kind == 'executions':
            rows = []
            for x in X.execution_view(st):
                sess = self.runs.get(x['run']); act = self.activity.get(x['run']) or {}
                rows.append(dict(x, title=self._title(x['task']), state=(st.get(x['run']) or {}).get('data', {}).get('state'),
                                 busy=bool(sess and sess.busy), tool=act.get('tool'), alive=bool(sess and sess.alive),
                                 queued=any(q['run_id'] == x['run'] for q in self.queued)))
            rows.sort(key=lambda r: (not r['busy'], not r['alive']))
            return {'items': rows}
        return {'error': 'unknown view'}

    def shutdown(self):
        for s in list(self.runs.values()):
            try: s.close()
            except Exception: pass
        try:
            self.call(lambda: self.store.commit(), timeout=30)
            self.store.db.close()
        except Exception:
            pass
