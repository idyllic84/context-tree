"""CTM answering an executor's questions from memory (concept model v2, 5.2 item 5: questions about a decision, a constraint, a
file location, another task's result or an earlier approach are answered by CTM from memory - only what is in force; what it does
not have, it says it does not know).

This is the on-demand path that lets CTM keep only brief progress per reply: details stay in run evidence (raw replies),
documents and the user's messages, and are looked up when an executor asks. Candidates come from the asking task's work
line (its top-level work and everything under it) and the root, as known at the time of asking; retrieval is by embedding
similarity with a mild preference for recent items; the model answers only from what is shown, marks what is the
executor's own report rather than verified, and says when memory does not contain the answer.
"""
import math

from context_tree.common import llm as base
from .model import ask


# 2026-11-19: probes on the user's week (46, two judges): correct 26->28, wrong 4->3; more answered from memory
PROMPT = '''You are CTM. Below are the records found in memory for the question (with turn and source: the user's words, executor replies, documents left by executions, progress summaries written by CTM, constraints and decisions).
The one asking may be the user (wanting to know what was done, what was decided, how things stand) or an executor about to act; it will understand or act on your answer.
The records carry different weight: constraint and decision entries were settled by the user and are authoritative; newer entries replace older ones (those marked "replaced" are only history), rejected approaches must not be used again, and conclusions the user questioned must be verified before use;
the user's words outrank executors' reports, and what an executor reported without supporting traces is only what it said at the time; progress summaries are the state when they were written. When statements about the same thing differ over time, the latest current entry wins, and earlier words only explain how it came about.
Analyse first: which records concern the question, their sources and times, which are current and which were replaced or rejected, and whether they conflict; then answer.
- When you can answer, give the answer with the turns it rests on; when only replaced statements exist, say they were replaced and give the current one; for what comes from an executor reply without supporting traces, note "the executor's statement at the time, unverified";
- When the records do not have it, answer "not in memory" and do not guess - a wrong answer makes the user or the executor understand or act on something wrong.
Write the answers in the language the question is asked in.
Output JSON only: {"answers":[{"q":0,"analysis":"..","answer":"..","basis":["turn 12"],"found":true}]}'''


def _chunks(text, size=1500):
    text = text or ''
    return [text[i:i + size] for i in range(0, len(text), size)] or ['']


def line_of(store, node, at):
    root = ([node] + store.ancestors(node, at))[-1]
    out, todo = [], [root]
    while todo:
        x = todo.pop(); out.append(x); todo += store.children(x, at)
    return out


def candidates(store, node, at):
    """(key, label, text, time) for the work line's records known at `at`."""
    out = []
    for n in line_of(store, node, at) + ['ROOT']:
        for typ in ('segment', 'progress', 'constraint', 'decision', 'environment', 'identifier', 'state', 'procedure', 'document', 'result', 'query'):
            for r in store.items(typ, about=n, at=at):
                d = r['data']
                if typ == 'segment':
                    texts, label = [d.get('text', '')], "the user's words"
                elif typ == 'progress' and d.get('note'):
                    texts, label = [d['note']], "the user's note (the state then)"
                elif typ == 'progress':
                    texts, label = [f"{d.get('done', '')}; changed: {d.get('changed')}; verified: {d.get('verified')}; open: {d.get('open')}; failed: {d.get('failed')}"], 'progress summary written by CTM'
                elif typ == 'result':
                    texts, label = [d.get('statement', '')], 'result handed up by a subtask or predecessor'
                elif typ == 'query':
                    texts, label = [f"Q: {d.get('question', '')} A: {d.get('answer') or '(not answered)'}"], 'query record'
                elif typ == 'document':
                    from .documents import latest
                    v = latest(store, r['id'])
                    body = d.get('text') or ((v or {}).get('data', {}).get('text')) or '\n'.join(f'## {k}\n{t}' for k, t in ((v or {}).get('data', {}).get('sections') or {}).items())
                    texts, label = _chunks(body), f"document '{d.get('title', '')}'"
                else:
                    gone = r['replaced_at'] is not None and r['replaced_at'] <= at
                    by = store.get(r['replaced_by']) if gone and r['replaced_by'] else None
                    kind = {'rejected': 'rejected approach (do not use again)', 'questioned': 'conclusion the user questioned (verify before use)'}.get(d.get('type'), typ) if typ == 'decision' else typ
                    texts, label = [d.get('statement', '')], (f"{kind} (replaced by a newer entry in turn {by['turn']})" if by else f"{kind} (replaced)") if gone else f"{kind} (current)"
                for j, t in enumerate(texts):
                    out.append((f"{r['id']}#{j}", f"[turn {r['turn']}][{label}]", t, r['at']))
        for (rid,) in store.db.execute("select src from edges where rel='serves' and dst=? and at <= ?", (n, at)).fetchall():
            r = store.get(rid)
            if r and r['type'] == 'run':
                replies = [r] + [store.get(x) for (x,) in store.db.execute("select src from edges where rel='in_run' and dst=? and at <= ?", (rid, at)).fetchall()]
                for x in replies:
                    for j, t in enumerate(_chunks(x['data'].get('reply', '')) if x['data'].get('reply') else []):
                        out.append((f"{x['id']}#{j}", f"[turn {x['turn']}][executor reply]", t, x['at']))
    return out


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


# For an executor that stopped because it needs information (concept 5.2 item 4: an executor that needs information turns to CTM): only the information itself
# counts. A record that the information was requested, or the executor's own question, is not an answer (first full replay:
# CTM "answered" requests for the user's App ID or a browser check by restating the request).
NEED = PROMPT + '''
The executor needs the information itself (or the result of an action only the user can take). Records that only say "this information was requested", or the executor's own questions or plans, do not count as found;
for what the user has to do now (authorize in a browser, listen to an audio clip, provide an account or a log) memory has no answer: answer "not in memory".'''


_VECTORS = {}   # chunk key (record id#part) -> vector; records do not change once written (a change is a new record), so this is safe


RECALL_K = 20             # 2026-11-19 (was 8): with replaced records shown with their replacements, probes correct 28 -> 33 of 46


def answer(store, node, at, questions, *, model, k=8, cache=None, need=False, prompt=None, embed=None):
    """Answer the executor's questions from the work line's memory as known at `at`. cache: dict for chunk vectors.
    need: the questions are information an executor stopped for (stricter: the information itself must be in memory)."""
    if not questions: return [], {}
    cands = [c for c in candidates(store, node, at) if c[2].strip()]
    if not cands: return [{'q': i, 'answer': 'not in memory', 'found': False} for i in range(len(questions))], {}
    cache = cache if cache is not None else _VECTORS   # without it every question re-embedded the whole work line (2026-11-19)
    emb = embed or base.embeddings                # embed: the pilot's vectors kept on disk (else the first query after a restart
    todo = [c for c in cands if c[0] not in cache]  # re-embedded the whole Goal subtree: ~100 s live, 2026-11-23)
    for i in range(0, len(todo), 64):
        for c, v in zip(todo[i:i + 64], emb([c[2][:2000] for c in todo[i:i + 64]])): cache[c[0]] = v
    qv = emb([q[:1000] for q in questions])
    newest = max(c[3] for c in cands); oldest = min(c[3] for c in cands)
    k = RECALL_K or k
    pick = []
    for v in qv:
        scored = sorted(cands, key=lambda c: -(_cos(v, cache[c[0]]) + 0.05 * ((c[3] - oldest) / ((newest - oldest) or 1))))
        for c in scored[:k]:
            if c not in pick: pick.append(c)
    by_id = {c[0].split('#')[0]: c for c in cands}   # a replaced record comes with the record that replaced it, up to the current one
    for c in list(pick):
        r = store.get(c[0].split('#')[0]) or {}
        seen = set()
        while r.get('replaced_by') and r['replaced_by'] not in seen and (r.get('replaced_at') or 0) <= at:
            seen.add(r['replaced_by']); nxt = by_id.get(r['replaced_by'])
            if nxt and nxt not in pick: pick.append(nxt)
            r = store.get(r['replaced_by']) or {}
    shown = [{'id': i, 'label': c[1], 'text': c[2]} for i, c in enumerate(pick)]
    out, usage = ask(NEED if need else (prompt or PROMPT), {'questions': [{'q': i, 'question': q} for i, q in enumerate(questions)], 'records': shown},
                     model=model, effort='low', max_out=6000, role='recall')
    answers = out.get('answers') or []
    return answers, usage
