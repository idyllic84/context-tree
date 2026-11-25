"""What CTM says to the user (concept model v2, 5.1 step 4 and 5.4; implementation plan S6).

Every CTM message is a referable display: pending items and options are numbered and name their task; the user may say
"the second one" or "ok" and the reference resolves to a concrete item. Only what needs the user goes into the conversation -
decisions to make, blocked, completed, not as expected; other progress only updates the tree and the execution view.
Answers to queries go to the query panel with numbered items and sources; the conversation shows a one-line conclusion.
"""


def display(store, *, items, at, turn, kind):
    """items: [{'text', 'task', 'pending'?, 'decision'?}] -> numbered display records; returns their ids and text."""
    ids, lines = [], []
    for i, it in enumerate(items, 1):
        did = store.add('display', {'no': i, 'kind': kind, 'text': it['text'], 'task': it.get('task')}, at=at, source='ctm', turn=turn)
        if it.get('task'): store.link(did, 'about', it['task'], at=at, source='ctm')
        for rel in ('pending', 'decision', 'query'):
            if it.get(rel): store.link(did, 'shows', it[rel], at=at, source='ctm')
        ids.append(did)
        title = (store.get(it['task']) or {}).get('data', {}).get('title') if it.get('task') else None
        lines.append(f"{i}. {'[' + title + '] ' if title else ''}{it['text']}")
    return ids, chr(10).join(lines)


def recent_displays(store, at, limit=12):
    """The numbered items shown most recently (referents for short replies such as "the second one" or "ok, go ahead")."""
    rows = store.items('display', at=at)[-limit:]
    return [{'id': r['id'], 'no': r['data']['no'], 'kind': r['data']['kind'], 'text': r['data']['text'], 'task': r['data'].get('task'), 'turn': r['turn']} for r in rows]


def open_pending(store, at, task=None):
    rows = store.items('pending', about=task, at=at) if task else store.items('pending', at=at)
    return [r for r in rows if r['data'].get('status', 'open') == 'open']


