"""Execution-control layer: judging an executor's stop (concept model v2, section 5.2).

The control layer sees the execution contract (approximated in evaluation by the user's requests for the
current work) and the end of the executor's reply. It decides whether to let the executor continue or to
escalate to CTM, without seeing the user's later answer.
"""
from .model import ask


# flash with V2 let fewer substantive answers be skipped (E7)
PROMPT = '''You are the execution control layer: you drive an executor agent to complete the work its contract requires. The agent has stopped. From the execution contract (what the user asked of this work) and the end of the agent's reply, judge the kind of stop and how to handle it.
Kinds:
- none: the agent asks the user for nothing (it reports completion or a conclusion);
- continue: the next step is clearly within what the contract asks; the agent only asks whether to go on;
- permission: before acting, the agent asks the user to approve a direction or plan, or asks for an action with side effects or beyond the contract (commit, push, delete, deploy, change files outside the scope, publish externally, ...);
- decision: the agent offers an optional step the contract does not ask for, or several options, and asks the user whether to do it or which to take;
- info: the agent needs information or material only the user has.
When the contract (the user's own words) already explicitly asks for or authorizes an action and the agent asks again whether to do it, let it go on as the contract says: auto_continue (asking the user again would only interrupt them).
Handling: continue -> auto_continue (let the agent go on); none -> report (report the result to CTM); permission, decision, info -> escalate (to CTM, which answers from memory or asks the user).
Write why in the language the user writes in.
Output JSON only: {"type":"..","action":"auto_continue|report|escalate","why":"one sentence"}'''


def classify_stop(contract, reply_tail, *, model, effort='low', prompt=None):
    return ask(prompt or PROMPT, {'contract_user_requests': contract, 'agent_reply_end': reply_tail}, model=model, effort=effort, role='control')


COMPLETION = '''You are the execution control layer. The executor says it has finished. Check only formal completion, not whether it was done well: whether every output the contract asks for was given (files, documents, conclusions);
whether the reply follows the agreement (briefly what was done, which files and documents were changed, how it was verified, open questions, what the user needs to decide); whether long content went into documents instead of piling up in the reply.
Output JSON only: {"complete":true,"missing":[".."],"ask_executor":"one sentence asking it to supply what is missing"}'''


def check_completion(contract, reply, *, model, effort='low'):
    """Formal completion check (concept 5.2 item 4); correctness is judged by CTM and the user, not here."""
    return ask(COMPLETION, {'contract': contract, 'executor_reply': (reply or '')[-6000:]}, model=model, effort=effort, role='completion')
