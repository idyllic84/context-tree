"""Executors and the execution-control layer (concept model v2, 5.2 items 1, 2, 4, 5, 6).

Lifecycle: a task gets a new executor (a run) with a contract and a small initial context the first time it is executed;
afterwards it keeps using that session, which normally never ends - however long the pause, even after a completion report
or after the task was abandoned (the executor is only stopped; reopening continues it). It ends only when its context is
near the limit and the user declines compaction; the next execution then gets a new executor with an initial context.
CTM forwards to the session the user's later messages about the task, constraints and decisions set elsewhere on its path,
and what changed while it was idle (files it involves changed elsewhere, query conclusions answered in forks).
Queries about a task with a session are answered in a read-only fork of that session, so the query does not enter the
session's execution context; without a session a new read-only executor answers.
Executor state: working (dispatched), waiting (for the user or CTM), idle (answered).
Control layer: classify executor stops (control.classify_stop) and handle them - continue within the contract,
escalate decisions, information, permissions and out-of-scope actions to CTM, check formal completion, enforce budgets,
and treat edits to constraint annotations as out of bounds. Only six kinds of things reach CTM: questions needing memory,
decisions for the user, actions beyond authorization, milestones, completion, failure. The control layer keeps no memory.
"""
from . import lifecycle as L

RECENT_HOURS = 3.0            # replay approximation of "working": sessions active this recently count as running executors
CONTEXT_LIMIT_TOKENS = 800_000


def active_run(store, task):
    """The task's session (not ended)."""
    for (rid,) in store.db.execute("select src from edges where rel='serves' and dst=? and valid_to is null order by at desc", (task,)).fetchall():
        r = store.get(rid)
        if r and r['type'] == 'run' and r['data'].get('mode') == 'session' and r['data'].get('status') == 'active':
            return r
    return None


def last_activity(store, run_id):
    """Latest exchange, produced file, or forwarded user message of the run (notices about outside changes do not count)."""
    r = store.db.execute("select max(e.at) from edges e left join items i on i.id=e.src where (e.src=? or e.dst=?) "
                         "and (i.type is null or i.type != 'notice')", (run_id, run_id)).fetchone()
    return max(r[0] or 0, store.get(run_id)['at'])


def end_reason(store, run, task, at, idle_hours=None):
    """A session ends only when its context is near the limit and the user declined compaction."""
    if run['data'].get('compact') == 'declined': return 'the context is full and the user does not compact it'
    return None


def context_check(store, run_id, *, at, turn=None):
    """When a session's context nears the limit, ask the user whether to compact it (runtime reports the token count)."""
    r = store.get(run_id)
    if (r['data'].get('tokens') or 0) <= CONTEXT_LIMIT_TOKENS or r['data'].get('compact'): return None
    store.patch(run_id, {'compact': 'asked'}, at=at, source='ctm')
    task = (store.db.execute("select dst from edges where src=? and rel='serves'", (run_id,)).fetchone() or ['ROOT'])[0]
    pid = store.add('pending', {'kind': 'ask_user', 'status': 'open', 'what': "This task's executor session is almost full. Compact it and go on? If not, a new executor takes over."},
                    at=at, source='ctm', turn=turn)
    store.link(pid, 'about', task, at=at, source='ctm'); store.link(pid, 'concerns', run_id, at=at, source='ctm')
    return pid


def set_state(store, run_id, state, *, at):
    if run_id and (store.get(run_id) or {}).get('data', {}).get('state') != state:
        store.patch(run_id, {'state': state}, at=at, source='ctm')


def executor_for(store, task, *, at, turn, mode='session', idle_hours=None, readonly=False, share_from=None):
    """The task's session (reused, however long ago) or a new executor. Returns (run_id, reused, reason).
    readonly: a query about the task - a read-only fork of its session if it has one, otherwise a new read-only executor;
    the task's status is not changed."""
    run = active_run(store, task)
    if run and end_reason(store, run, task, at):
        end_run(store, run['id'], end_reason(store, run, task, at), at=at); run = None
    if readonly:
        rid = store.add('run', {'mode': 'fork' if run else 'readonly', 'status': 'active', 'state': 'working', 'tokens': 0, 'started_turn': turn,
                                'contract': 'read only: do not change any file, configuration or external state'}, at=at, source='ctm', turn=turn)
        store.link(rid, 'serves', task, at=at, source='ctm')
        if run:
            store.link(rid, 'forked_from', run['id'], at=at, source='ctm')
            return rid, False, "read-only query: a fork of this task's session answers"
        return rid, False, 'read-only query: a new read-only executor'
    st = L.status(store, task)
    if st in ('reported_done', 'verified', 'abandoned', 'replaced'):
        L.set_status(store, task, 'reopened', at=at, source='ctm', reason='the user continues this work')
    if L.status(store, task) in ('pending', 'ready', 'reopened', 'blocked', 'paused'):
        L.set_status(store, task, 'running', at=at, source='ctm', reason='dispatched')
    if run:
        set_state(store, run['id'], 'working', at=at)
        return run['id'], True, "continuing this task's session"
    shared = active_run(store, share_from) if share_from else None
    if shared:                                        # a subtask directly continuing its parent's execution works in the parent's session
        store.link(shared['id'], 'serves', task, at=at, source='ctm')
        set_state(store, shared['id'], 'working', at=at)
        return shared['id'], True, "continuing this subtask in the parent task's session"
    had = store.db.execute("select 1 from edges e join items i on i.id=e.src where e.rel='serves' and e.dst=? and i.type='run' "
                           "and i.data like '%\"mode\": \"session\"%'", (task,)).fetchone()
    rid = store.add('run', {'mode': mode, 'status': 'active', 'state': 'working', 'tokens': 0, 'started_turn': turn}, at=at, source='ctm', turn=turn)
    store.link(rid, 'serves', task, at=at, source='ctm')
    return rid, False, ('the earlier session ended, a new executor' if had else 'a new task, a new executor')


def research_executor(store, rid, *, at, turn):
    """A research item keeps its own session across rounds; returns (run_id, reused)."""
    for (x,) in store.db.execute("select src from edges where rel='serves' and dst=? and valid_to is null order by at desc", (rid,)).fetchall():
        r = store.get(x)
        if r and r['type'] == 'run' and r['data'].get('mode') == 'research' and r['data'].get('status') == 'active':
            set_state(store, x, 'working', at=at)
            return x, True
    x = store.add('run', {'mode': 'research', 'status': 'active', 'state': 'working', 'tokens': 0, 'started_turn': turn,
                          'contract': "research: read the project's files only, write the conclusions into the research document"}, at=at, source='ctm', turn=turn)
    store.link(x, 'serves', rid, at=at, source='ctm')
    return x, False


def sweep(store, *, at, idle_hours=1.0):
    """Close read-only executors and forks that never answered (sessions are not ended by time)."""
    ended = []
    for (rid,) in store.db.execute("select id from items where type='run' and data like '%\"status\": \"active\"%'").fetchall():
        r = store.get(rid)
        if r['data'].get('status') != 'active' or r['data'].get('mode') not in ('readonly', 'fork', 'single'): continue
        if at - last_activity(store, rid) > idle_hours * 3600:
            end_run(store, rid, 'no reply', at=at); ended.append(rid)
    return ended


def stop_run(store, run_id, *, at, why):
    """Stop what the executor is doing; the session stays and continues when the task is resumed or reopened."""
    store.event(run_id, 'control', at=at, source='user', data={'action': 'stop', 'why': why})
    set_state(store, run_id, 'idle', at=at)


def end_run(store, run_id, reason, *, at):
    store.patch(run_id, {'status': 'ended', 'end_reason': reason}, at=at, source='ctm', reason=reason)


def forward(store, *, run_id, item_id, at, why):
    """Something the active session must receive: the user's new message about its task, or a constraint/decision set
    elsewhere that applies on its task path."""
    store.link(item_id, 'forwarded_to', run_id, at=at, source='ctm', data={'why': why})


def runs_affected_by(store, node, at):
    """Active sessions whose task is `node` or below it (a constraint on `node` applies to them)."""
    out = []
    for (rid, task) in store.db.execute("select e.src, e.dst from edges e join items i on i.id=e.src where e.rel='serves' and i.type='run'").fetchall():
        r = store.get(rid)
        if r['data'].get('mode') == 'session' and r['data'].get('status') == 'active' and (task == node or node in store.ancestors(task)):
            out.append(rid)
    return out


def handle_stop(store, *, run_id, task, stop, at, turn):
    """Apply the control layer's decision on an executor stop (stop = control.classify_stop output). Returns what goes
    to CTM (None when the executor simply continues)."""
    action = stop.get('action')
    if action == 'auto_continue':
        store.event(run_id, 'auto_continue', at=at, source='ctm', data=stop)
        return None
    if action == 'report':
        return {'kind': 'completed', 'run': run_id, 'task': task}
    kind = {'permission': 'out_of_scope', 'decision': 'decision', 'info': 'question'}.get(stop.get('type'), 'decision')
    pid = store.add('pending', {'kind': kind, 'what': stop.get('why'), 'from_run': run_id, 'status': 'open'}, at=at, source='executor', turn=turn)
    store.link(pid, 'about', task, at=at, source='ctm')
    set_state(store, run_id, 'waiting', at=at)
    if kind in ('decision', 'out_of_scope'):
        L.set_status(store, task, 'blocked', at=at, source='ctm', reason="waiting for the user's decision")
    return {'kind': kind, 'pending': pid, 'run': run_id, 'task': task}


TAMPER_MARKERS = ('ctm:',)   # the mark of CTM's ctm.md entries ('- [ctm:ID]') and of constraint annotations; a line that only
                             # mentions ctm.md is not one (2026-11-24: a sentence in an executor's report raised a false alarm)


def constraint_tamper(diff_text):
    """An executor edit that removes or changes constraint annotations or ctm.md entries is out of bounds (escalate)."""
    hits = []
    for line in (diff_text or '').splitlines():
        if line.startswith('-') and not line.startswith('---') and any(m in line.lower() for m in TAMPER_MARKERS):
            hits.append(line)
    return hits


NO_PROGRESS_LIMIT = 3          # consecutive auto-continues with no tool use in between -> stop and escalate
MAX_AUTO_CONTINUE = 10         # auto-continues since the user's last message to this executor (cost and safety limit)


def budget_check(store, run_id, *, at, error=None):
    """Errors, retries and budget (5.2 item 4): continuing without new progress, too many continues, or the same error twice
    stops the run and escalates to CTM, which re-plans, narrows the scope or asks the user. Progress here is an observation,
    not a judgment: the executor used a tool (edited, ran, read) since the last continue. Every reply has a summary, so the
    summary cannot tell a stalled executor from a working one (the earlier check reset on it and never fired)."""
    run = store.get(run_id) or {}
    last_user = max([run.get('at') or -1.0] + [r[0] for r in store.db.execute(
        "select at from edges where rel='forwarded_to' and dst=?", (run_id,)).fetchall()])
    evs = [e for e in store.events_of(run_id) if e['kind'] in ('auto_continue', 'activity', 'error')]
    last_act = max([last_user] + [e['at'] for e in evs if e['kind'] == 'activity'])
    streak = sum(1 for e in evs if e['kind'] == 'auto_continue' and e['at'] > last_act)
    total = sum(1 for e in evs if e['kind'] == 'auto_continue' and e['at'] > last_user)
    errors = [e['data'].get('error') for e in evs if e['kind'] == 'error']
    if error: store.event(run_id, 'error', at=at, source='executor', data={'error': error}); errors.append(error)
    reason = ('no_progress' if streak >= NO_PROGRESS_LIMIT else 'too_many_continues' if total >= MAX_AUTO_CONTINUE
              else 'repeated_error' if len(errors) >= 2 and errors[-1] == errors[-2] else None)
    if reason:
        store.event(run_id, 'escalate', at=at, source='ctm', data={'reason': reason, 'streak': streak, 'total': total})
        return {'kind': 'failed', 'run': run_id, 'reason': reason}
    return None


def milestone(store, *, run_id, task, summary, at, turn=None):
    """A long-running executor reports a milestone: CTM writes it into the task's progress right away."""
    pid = store.add('progress', dict(summary, milestone=True), at=at, source='ctm', turn=turn, observed_at=at)
    store.link(pid, 'about', task, at=at, source='ctm'); store.link(pid, 'summarizes', run_id, at=at, source='ctm')
    store.event(run_id, 'progress_seen', at=at, source='ctm')
    return pid


def execution_view(store, at=None):
    """Execution view (1.2): running or waiting executors with node, form, status and latest output."""
    out = []
    for r in store.items('run', at=at):
        d = r['data']
        if d.get('status') not in ('active', 'requested'): continue
        task = [x for (x,) in store.db.execute("select dst from edges where src=? and rel='serves' and valid_to is null", (r['id'],)).fetchall()]
        last = store.db.execute("select i.data from items i join edges e on e.src=i.id and e.rel='in_run' and e.dst=? order by i.at desc limit 1", (r['id'],)).fetchone()
        import json
        out.append({'run': r['id'], 'task': task[0] if task else None, 'form': d.get('mode'), 'status': d.get('status'),
                    'latest_output': (json.loads(last[0]).get('reply', '')[-300:] if last else '')})
    return out
