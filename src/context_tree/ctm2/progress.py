"""Writing an executor's reply back into task progress (concept model v2, section 5.2 item 6).

CTM keeps a brief run summary per reply: what was done, which documents/files changed, verification, open issues,
decisions needed from the user, and failed attempts with their reasons. Statements are marked as reported by the
executor unless the trace (tool calls) supports them.
"""
from .model import ask


# 2026-11-19: analysis selects from the reply; downstream use ~40% -> ~65%, unsupported claims as V3 (V5/V7 invite gap-filling)
PROMPT = '''You are CTM. The executor finished a piece of work and replied. Write it up as one summary in this work's progress. The summary has three uses: a new executor who later takes over this work cannot see the original reply and continues from it alone,
treating it as fact; when the user asks about progress, CTM answers from it; the items in open become things waiting for the user.
So both kinds of error cost something. A wrong entry (a guessed cause, "maybe" written as "certainly", a number whose meaning is changed, an object the reply did not name) makes whoever takes over act on wrong facts. Missing a point needed to take over
(the conclusion reached with its grounds and key numbers, which files and documents were changed, what is left for the user to do and by when, a plan to be carried out once the user confirms, things waiting for a condition, approaches tried that failed)
makes whoever takes over redo work, reach contradicting conclusions, or have the user explain again. Long details (full tables, code, whole texts) need not be copied in; note where they are.
Analyse first: what in this reply someone taking over, or the user coming back, must know, and what is only process; what the reply states for certain and what is only a guess. Then write:
- done: what was done and what was obtained: conclusions with their grounds and key numbers, concretely;
- changed: which files and documents were changed or created (paths);
- verified: how the result was verified - "traced" when the tool call record has the matching command or test, "self-reported" when it is only the executor's own word - and what was checked;
- open: what is still unsettled or unfinished when this reply ends: what is left for the user to do or decide (with its deadline if it has one), a plan to be carried out once the user confirms, things waiting for a condition. CTM shows these to the user as numbered items, and whoever takes over starts from them: an unfinished point missing here looks finished. Where the executor already gave a recommendation or conclusion, write it as a conclusion, not as open;
- failed: approaches tried that failed, and why (empty if none).
Write in the language the user writes in.
Output JSON only: {"analysis":"..","done":"..","changed":[".."],"verified":"..","open":[".."],"failed":[".."]}'''


# Only when later work waits on a condition about this work's result (a conditional dependency, concept 3.4): the same
# summary call also judges each condition. Without conditions the prompt and the input are exactly the summary's.
CONDITIONS = '''In addition, conditions lists the later works waiting for this work's result, each with its condition (for example: start only when the tests pass). Judge from the reply and the tool record alone whether each condition is met now: true when met, false when clearly not met, null when you cannot tell - judged met by mistake, the later work starts while the condition does not hold; when you cannot tell, it waits for the user or the next result. Add "conditions_met":[{"successor":"N5","met":true,"why":".."}] to the output.'''


def summarize(user_message, reply, tools, *, model, effort='low', prompt=None, conditions=None):
    payload = {'user_request': (user_message or '')[:2000], 'executor_reply': (reply or '')[:8000],
               'tool_trace': [{k: v for k, v in t.items() if k in ('name', 'path', 'command', 'success')} for t in (tools or [])][:30]}
    if conditions:
        payload['conditions'] = conditions
        out, usage = ask((prompt or PROMPT) + chr(10) + CONDITIONS, payload, model=model, effort=effort, role='progress')
    else:
        out, usage = ask(prompt or PROMPT, payload, model=model, effort=effort, role='progress')
    if isinstance(out, dict): out.pop('analysis', None)         # V4 analyses first; the analysis is not part of the record
    return out, usage
