"""The root (global layer) of the tree (concept model v2, 3.3; implementation plan S9).

Holds what belongs to no Goal and stays valid long term: the persona and CTM's understanding of the user (CTM-only,
always present, bounded), overall goals and priorities (interpretation only, never authority to act), explicit
preferences and global constraints (root task constraints, inherited by everything), common environments (volatile ones
with observation time), and the root conversation record (segments about ROOT). User-set and CTM-inferred items are kept
apart; inferred preferences and goal changes are proposals until the user accepts them.
"""
ROOT = 'ROOT'
UNDERSTANDING_CHAR_LIMIT = 2500


def ensure_root(store, at=0):
    if not store.get(ROOT):
        store.add('root', {'title': 'root'}, at=at, source='ctm', id=ROOT)
    if not store.items('persona'):
        pid = store.add('persona', {'text': PERSONA}, at=at, source='user')
        store.link(pid, 'about', ROOT, at=at, source='ctm')


PERSONA = '''Role: the assistant between the user and the executor agents: understanding, memory, routing, answering queries, relaying and dispatching. Principles: say plainly what is uncertain; do not overstep - a proposal is not an authorization; admit mistakes first; do not rewrite the user's words or add requirements for the user. Communication: conclusion first, brief; number pending items and say which task each belongs to. Initiative: for reversible actions, act on the most likely understanding and state it; for irreversible actions or ones affecting the outside, ask first when unsure.'''


def add_understanding(store, text, *, evidence, confidence, at, source='ctm'):
    """An entry of CTM's understanding of the user: an inference with evidence, confidence and time; editable by the user."""
    uid = store.add('user_understanding', {'text': text, 'evidence': evidence, 'confidence': confidence}, at=at, source=source)
    store.link(uid, 'about', ROOT, at=at, source='ctm')
    return uid


def understanding_text(store, at=None):
    """Persona and understanding of the user for CTM's own understanding context (never for executors)."""
    persona = store.items('persona', at=at, current_only=True)
    entries = store.items('user_understanding', at=at, current_only=True)
    lines = [f"- {e['data']['text']} (grounds: {e['data'].get('evidence', '')}; confidence: {e['data'].get('confidence', '')})" for e in entries]
    text = chr(10).join(lines)
    over = len(text) > UNDERSTANDING_CHAR_LIMIT
    return {'persona': persona[-1]['data']['text'] if persona else '', 'understanding': lines, 'over_limit': over,
            'overall_goals': [g['data'] for g in store.items('overall_goal', at=at, current_only=True)]}


def add_overall_goal(store, text, *, priority=None, at, source='user'):
    gid = store.add('overall_goal', {'text': text, 'priority': priority, 'authority': False}, at=at, source=source)
    store.link(gid, 'about', ROOT, at=at, source='ctm')
    return gid


def add_preference(store, statement, *, at, source='user'):
    """A user preference or global constraint is a task constraint on the root; inferred ones are proposals."""
    if source == 'user':
        cid = store.add('constraint', {'statement': statement, 'kind': 'global', 'validity': 'long_term'}, at=at, source='user')
        store.link(cid, 'about', ROOT, at=at, source='ctm')
        return cid
    pid = store.add('pending', {'kind': 'proposed_preference', 'statement': statement}, at=at, source='ctm')
    store.link(pid, 'about', ROOT, at=at, source='ctm')
    return pid


def add_environment(store, statement, *, volatile=False, at, source='user'):
    eid = store.add('environment', {'statement': statement, 'volatile': volatile, 'scope': 'common'}, at=at, source=source,
                    observed_at=at if volatile else None)
    store.link(eid, 'about', ROOT, at=at, source='ctm')
    return eid


