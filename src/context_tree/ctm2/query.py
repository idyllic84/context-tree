"""Queries (concept model v2, 5.3; implementation plan S8).

A segment CTM judged to be a query (unclear cases are treated as queries and said so) creates no node. CTM answers from
memory when memory holds the answer (decisions, progress, documents, run evidence of the related work line, the root);
otherwise it dispatches a read-only execution whose contract forbids any change. Volatile states observed are kept with
their observation time. The full answer goes to the query panel with numbered items and sources; the conversation gets a
one-line conclusion and a link. The query and answer are kept as a searchable record linked to the related work (or the
root) and are carried into the initial context if the user later turns it into a task.
"""
from .model import ask
from .recall import answer
from . import relay



# 2026-11-19: on the 40 agreed probes routed well 35 vs 36 (within noise); analysis-first is the project rule
ROUTE = '''You are CTM. The user asked a question (only wanting to know something). Below is the answer found in memory (possibly empty or incomplete). First analyse: whether it asks about something recorded, about the current state, or for an explanation or analysis; whether the memory answer is complete, and whether it rests on current records or on ones that may be out of date; then decide how to answer:
- It asks about something recorded - what was done, decided or said, progress and results - and the memory answer is complete: answer from memory (from_memory=true).
- It asks about the current state of files, logs, running services or external data: the records in memory may be out of date (things may have changed since, and a record may only be an executor's unverified claim) -> dispatch a read-only execution to look (from_memory=false); the memory answer is only a lead.
- It asks for an explanation, analysis, comparison or technical reasoning (why, what to do, what is the difference, would it work): the executor of the related work answers read-only (from_memory=false), as it can look into the code and material and reason; the memory answer is only a lead.
A wrong answer from memory (taking old records for the present, only stitching together earlier statements) misleads the user; an unnecessary read-only execution is only slower. When unsure, dispatch a read-only execution.
When the answer can only be obtained by changing some state (running commands with side effects, changing configuration, deploying), needs_change is true, and CTM asks the user first.
Output JSON only: {"analysis":"..","kind":"record|current_state|explain","from_memory":true,"readonly_plan":"when not from memory: which files to read, which read-only commands to run, what to answer","needs_change":false}'''


def handle(store, *, question, node, at, turn, model, route_model=None, embed=None):
    """Returns (query_id, result) where result has 'answers' from memory or a 'readonly' execution request."""
    ans, usage = answer(store, node, at, [question], model=model, embed=embed) if node else ([], {})
    found = bool(ans and ans[0].get('found'))
    d, _ = ask(ROUTE, {'question': question, 'memory_answer': ans[0] if ans else None}, model=route_model or model, effort='low', role='query-route')   # a two-way choice: flash (2026-11-20: 37 vs 36 of 42 routed well, half the time)
    use_memory = found and bool(d.get('from_memory'))
    if use_memory:
        result = {'from_memory': True, 'answer': ans[0].get('answer'), 'basis': ans[0].get('basis'), 'kind': d.get('kind')}
    else:
        result = {'from_memory': False, 'readonly_plan': d.get('readonly_plan'), 'partial': ans[0].get('answer') if ans else None,
                  'needs_change': bool(d.get('needs_change')), 'kind': d.get('kind')}
    found = use_memory
    qid = store.add('query', {'question': question, **result}, at=at, source='ctm', turn=turn)
    store.link(qid, 'about', node or 'ROOT', at=at, source='ctm')
    if not found and result.get('needs_change'):
        pid = store.add('pending', {'kind': 'ask_user', 'status': 'open', 'what': f'Answering "{question[:80]}" needs a change of state: {result.get("readonly_plan") or ""}. Go ahead?'},
                        at=at, source='ctm', turn=turn)
        store.link(pid, 'about', node or 'ROOT', at=at, source='ctm'); result['ask'] = pid
    elif not found:
        rid = store.add('run', {'mode': 'readonly', 'status': 'requested', 'contract': 'read only: do not change any file, configuration or external state', 'plan': result['readonly_plan']},
                        at=at, source='ctm', turn=turn)
        store.link(rid, 'serves', qid, at=at, source='ctm')
    relay.display(store, items=[{'text': (result.get('answer') or 'needs a read-only check: ' + (result.get('readonly_plan') or ''))[:300], 'task': node, 'query': qid}],
                  at=at, turn=turn, kind='query_answer')
    return qid, result


def panel(store, at=None, limit=20):
    """Query panel (1.2): past answers with numbered items, sources and time (replaced statements are marked as history by the
    recall prompt), and the research items with their conclusion documents."""
    research = [{'id': r['id'], 'turn': r['turn'], 'research': r['data'].get('title'), 'document': r['data'].get('doc'),
                 'status': r['data'].get('status'), 'about': store.about(r['id'])} for r in store.items('research', at=at)[-limit:]]
    return research + [{'id': q['id'], 'turn': q['turn'], 'question': q['data'].get('question'), 'answer': q['data'].get('answer'),
             'basis': q['data'].get('basis'), 'from_memory': q['data'].get('from_memory'), 'about': store.about(q['id'])}
            for q in store.items('query', at=at)[-limit:]]
