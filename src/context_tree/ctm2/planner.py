"""Planner (concept model v2, 3.4 task sources and proposals, S5 scenario; implementation plan: planning is part of the
design; real use is evaluated in runtime integration).

CTM calls the planner for larger work ("design first, then implement, open a PR once the tests pass"). Planned subtasks and their dependencies appear
as proposals; they become pending when the user approves or when they lie within what the user already authorized.
Gates such as "open a PR after the tests pass" are recorded as conditional dependencies on the subtask, and the authorization the
user gave in the original words is kept on that subtask.
"""
from .model import ask
from . import lifecycle as L

PROMPT = '''You are the planner. Split the work the user wants into subtasks that can be executed and accepted separately (in the order "requirements -> design -> implementation" when it helps, but not necessarily).
For each subtask give a title, its output, the completion criteria (done_criteria: the control layer judges formal completion by them), the effort budget (budget: about how many rounds of execution), which earlier subtasks it depends on (serial / join / conditional (state the condition) / alternative), and whether the user's words already authorize it (authorized_by_user).
Do not add subtasks the user did not ask for. Write titles and outputs in the language the user writes in. Output JSON only: {"subtasks":[{"key":"s1","title":"..","output":"..","done_criteria":"..","budget":3,"depends":[{"on":"s0","type":"serial","condition":null}],"authorized_by_user":false}]}'''


def plan(store, tree, task, *, request, at, turn, model):
    out, usage = ask(PROMPT, {'task': (store.get(task) or {}).get('data', {}), 'user_request': request}, model=model, effort='medium', role='planner')
    keymap = {}
    for st in out.get('subtasks') or []:
        nid = tree.add(st.get('title') or '', st.get('output') or '', task, None, turn, at, source='planner', proposed=True)
        keymap[st.get('key')] = nid
        store.patch(nid, {'done_criteria': st.get('done_criteria'), 'budget': st.get('budget')}, at=at, source='planner')
        if st.get('authorized_by_user'):
            L.set_status(store, nid, 'pending', at=at, source='ctm', reason='within what the user authorized')
    for st in out.get('subtasks') or []:
        for dep in st.get('depends') or []:
            if dep.get('on') in keymap and st.get('key') in keymap:
                L.add_dep(store, keymap[dep['on']], keymap[st['key']], at=at, source='planner', kind=dep.get('type') or 'serial', condition=dep.get('condition'))
    for nid in keymap.values():
        L.refresh_ready(store, nid, at=at, source='ctm')
    return keymap, usage


def approve(store, nodes, *, at):
    """The user approved proposed subtasks: they become pending (and ready if their dependencies allow)."""
    for n in nodes:
        if L.status(store, n) == 'proposed':
            L.set_status(store, n, 'pending', at=at, source='user', reason='approved by the user')
            L.refresh_ready(store, n, at=at, source='ctm')
