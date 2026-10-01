"""Assemble final context from fixed selected evidence."""
from ...common import llm as copilot_api
from ...common.context_view import AGENT_VOICE, USER_VOICE, BRANCH_RETRIEVE_PROMPT, _parse_iter_action, _format_branched_state

def assemble_context(utterance: str, current_session_id: str | None,
                     branches: list[dict], model: str | None = None,
                     mode: str = "agent", search_results: list[dict] | None = None) -> list[dict]:
    if not branches:
        return []
    selected_tasks = {(b["session_id"], nid) for b in branches
                      for nid in {n["id"] for n in b["nodes"]} | set(b.get("_expanded_data", {}))}
    evidence_results = []
    for search in search_results or []:
        matches = []
        for hit in search["matches"]:
            if "identifier" in hit:
                if (hit["session"], hit["task_id"]) in selected_tasks:
                    matches.append(hit)
            else:
                tasks = [t for t in hit["related_tasks"] if (t["session"], t["task_id"]) in selected_tasks]
                if tasks:
                    matches.append({**hit, "related_tasks": tasks})
        if matches:
            evidence_results.append({**search, "matches": matches})
    voice = AGENT_VOICE if mode == "agent" else USER_VOICE
    body = (_format_branched_state(utterance, current_session_id, branches, [], evidence_results)
            + "\nAll available evidence is supplied. Assemble final context candidates only. "
            "Do not search, expand, invent missing facts, or use another candidate's summary as evidence.")
    content = copilot_api.chat_content(BRANCH_RETRIEVE_PROMPT + voice, body,
                                       model=model, stage="context")
    action = _parse_iter_action(content)
    if (not isinstance(action, dict)
            or not (action.get("done") or action.get("action") == "done")
            or not isinstance(action.get("candidates"), list)
            or any(action.get(key) for key in ("expand", "search_file", "search_identifier"))):
        raise ValueError("Context stage must finish using supplied evidence only")
    return action["candidates"]


def _finalize_branched(llm_cands: list[dict], branches: list[dict],
                        dropped: set[str], actions_log: list[str],
                        timing: dict, iters: int, mode: str = "user") -> dict:
    """Validate LLM's candidates against actual branches; build output structure."""
    branch_by_id = {b["branch_id"]: b for b in branches if b["branch_id"] not in dropped}
    out_cands = []
    for c in llm_cands if isinstance(llm_cands, list) else []:
        if not isinstance(c, dict): continue
        bids = c.get("branch_ids") or []
        if not isinstance(bids, list): continue
        valid_bids = list(dict.fromkeys(bid for bid in bids
                                      if isinstance(bid, str) and bid in branch_by_id))
        if not valid_bids or not isinstance(c.get("summary", ""), str): continue
        valid_refs = set()
        for bid in valid_bids:
            branch = branch_by_id[bid]
            visible = {n["id"] for n in branch["nodes"]}
            visible.update(branch.get("_expanded_data", {}))
            for fields in branch.get("_expanded_data", {}).values():
                visible.update(n["id"] for n in fields.get("subtree", []))
            valid_refs.update(f"{branch['session_id']}/{nid}" for nid in visible)
        cited = c.get("cited") or []
        cited = [ref for ref in cited if isinstance(ref, str) and ref in valid_refs] if isinstance(cited, list) else []
        primary = branch_by_id[valid_bids[0]]
        merged_from = valid_bids if len(valid_bids) > 1 else None
        out_cands.append({
            "branch_ids": valid_bids,
            "primary_session": primary["session_id"],
            "anchor": {
                "id": primary["anchor_id"],
                "kind": primary["anchor_kind"],
                "name": primary["anchor_name"],
                "breadcrumb": primary["breadcrumb"],
                "status": primary["status"],
            },
            "lit_members_total": sum(branch_by_id[b]["lit_count"] for b in valid_bids),
            "summary": c.get("summary", ""),
            "cited": list(dict.fromkeys(cited)),
            "merged": merged_from is not None,
        })
    return {
        "mode": mode,
        "candidates": out_cands,
        "branches": branches,
        "dropped": list(dropped),
        "iterations": iters,
        "actions": actions_log,
        "elapsed": timing,
    }
