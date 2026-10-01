"""Choose one retrieval action from a supplied evidence state without executing it."""
from ...common import llm
from ...common.context_view import BRANCH_RETRIEVE_PROMPT, AGENT_VOICE, USER_VOICE, _format_branched_state, _parse_iter_action


def select_action(query, branches, current_session_id=None, history=None, search_results=None,
                  model=None, mode="agent"):
    voice = AGENT_VOICE if mode == "agent" else USER_VOICE
    body = _format_branched_state(query, current_session_id, branches, history or [], search_results or [])
    content = llm.chat_content(BRANCH_RETRIEVE_PROMPT + voice, body, model=model, stage="retrieve")
    return _parse_iter_action(content)
