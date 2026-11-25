"""Step 1 of handling a user message (concept model 5.1): how the message points to the work it is about, and the
entities it names (including in pasted material). It decides nothing about placement; candidates.py turns it into
candidate works and the localization call decides among them."""
from .model import ask

NL = chr(10)

REF = '''You are CTM: the user talks only to you, in one continuous conversation, moving several works forward in turns. This step does not decide which work the message belongs to; it only prepares the search for candidates: judge how this message points to the work it is about, and extract the objects it mentions.

The ways of pointing (modes, several may apply) decide where CTM looks for candidates:
- display: answering a result, plan or pending item you just showed (approve, reject, correct, follow up, check, answer the executor's question). Candidates: the works of the latest displays and pending items.
- continue: a bare push or control pointing at nothing (go on, stop, leave it like this). Candidates: the current work and the running or waiting executors.
- nearby: a near reference to what was just said (this, it, the one just now). Candidates: the works in the latest conversation.
- named: names a work, an object (file, module, service, environment, data), a product (document, PR, report, plan, version) or an identifier (number, path, branch). Candidates: these objects searched in all of memory, however long ago.
- past: points to the past by time (yesterday, last time, the first version, before the fix). Candidates centre on that time.
- material: pastes logs, errors, code, documents or other material. Objects are extracted from the material to find candidates; the material itself goes to the executor as it is.
- reference: wants to use a plan, conclusion or document settled elsewhere. Candidates: the related decisions and documents.
- new: makes a new request that does not visibly point to an existing work. Related works are still searched by its objects (it may continue, be part of or be the next step of a work).
- external: research collecting information outside. Candidates: the research items in the query list and related works.
- chat: small talk; no candidates needed.
A missed way of pointing means the candidates of that way are never found; an extra one only adds a few candidates. When unsure, choose more.

Objects (entities): what in the message (including pasted material) tells one work from the others. For each write:
- said: the wording in the original;
- resolved: an explicit description with references resolved from the latest conversation ("it", "this file" written as which one exactly); copy the original when it cannot be resolved;
- type: object (file, module, service, environment, data), artifact (document, PR, report, plan, version), work (a work's name or description), identifier (numbers, paths, branch names and other identifiers that must match exactly: copy them as they are, without correcting the spelling);
- role: target (what is to be acted on or asked about) or context (only background).
Do not extract generic words (code, the problem, this feature).
Time references (time_refs): the words and roughly how many hours ago; empty when there are none.
Material (material): when the message has a long pasted text, what it is (log, error, code, document, ...) and its first few words; null when there is none.
Output JSON only: {"modes":["named"],"entities":[{"said":"..","resolved":"..","type":"object","role":"target"}],"time_refs":[{"phrase":"..","hours_ago":null}],"material":null}'''


def extract(message, recent, *, model, effort='low', displays=None, pending=None, prompt=None):
    """recent: [{'user','agent_end'}] of the last two or three turns, for resolving references like "it"."""
    msg = message if len(message) <= 8000 else message[:4000] + ' ... [middle omitted] ... ' + message[-3000:]
    payload = {'recent_conversation': recent, 'message': msg}
    if displays: payload['recent_displays'] = displays
    if pending: payload['open_pending'] = pending
    return ask(prompt or REF, payload, model=model, effort=effort, role='ref')
