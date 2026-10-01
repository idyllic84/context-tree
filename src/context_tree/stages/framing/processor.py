"""V2-B Tier 3.5 — Purpose Framing Pass.

For each Task in the Session, gather its agent units (propose/explain/clarify/report),
batch them with goal/task context, and ask the LLM to produce per-unit:
  - purpose_title (≤80 chars, USER-purpose framing, not agent content roll-up)
  - purpose_body (150-300 chars, ground in head/tail without new facts)
  - subtype (decision_taken | decision_soft | decision_rejected |
             unclaimed_proposal | rationale_accepted | rationale_soft |
             clarify_open | report_observed)

Subtype is largely derivable from unit.acceptance + unit.act, but we let the
LLM confirm based on context (it sees adjacent user reactions).

Architecture: NEW module. Runs after state_machine builds the task tree.
Inputs: Session (turns + goals/tasks), uses unit_by_id lookup. Reads
adapter-supplied turn.agent_split (head/tail/truncated_chars) for agent text —
turn.agent_segments is deprecated and no longer populated.
Outputs: writes purpose_title / purpose_body / framing_failed onto AtomicUnit
in place. State machine has already set acceptance.

Batching: 5-8 tasks per LLM call (Batch Prompting paper, ~5x cost reduction).
Single batch ≤ 8K input chars. Single task > 4K chars → standalone batch.

Failure mode: per-task fallback writes
  purpose_title = head[:80]
  purpose_body = head + " ... " + tail
  framing_failed = True
"""
import json
import os
import sys

import context_tree.common.llm as copilot_api
from context_tree.common.models import Session, Goal, Task, AtomicUnit, DialogueTurn


BATCH_MAX_INPUT_CHARS = 45000
# Hard cap on agent units per LLM call. Output is the binding constraint:
# each framing entry ~250 chars; 60 × 250 = 15K (≈ 35% of 1/3 output cap 43K).
# Stage 17 observation: per-turn ac causes large tasks to accumulate many agent
# units (one per turn); without this cap, single-task batches exceeded LLM
# JSON-array output reliability and dropped 12% of unit_ids.
BATCH_MAX_AGENT_UNITS = 60
# A single task with > this many agent units is split into multiple blocks
# (each repeating the task header). Keeps any one LLM call's output bounded.
TASK_BLOCK_MAX_AGENT_UNITS = 30
PURPOSE_TITLE_MAX = 80
PURPOSE_BODY_MAX = 300


SYSTEM_PROMPT = """Re-frame agent dialogue units for a knowledge graph.
Conversation: human supervises an AI coding agent. Same language as source.

Title encodes the FACT / PROPOSAL / CONCEPT itself. The user's stance
(agreed / rejected / unclaimed / etc) is encoded in the `subtype` field —
do NOT prefix titles with "用户同意了 …" / "用户拒绝了 …". That info is
captured by subtype + the entity-resolver's Avoid: pairing.

For each agent unit input, produce:

1. purpose_title (≤80 chars) — the fact/proposal/concept, DOMAIN keywords first.
   Strong noun phrases. No verbs about what the user did.

   GOOD (fact-first, keyword-rich):
     "GRDB 替代 SwiftData 方案"
     "8px 内描边方案 (icon)"
     "checkForUpdateInformation 静默 Sparkle 更新"
     "SQL 从 DatabaseService 剥离到业务服务"
     "Ld linker 错误 (JSON 路径配置)"
     "Auth 模块迁移到 GRDB"
     "FRE 跳过按钮仅权限页显示"

   BAD (user-voice — redundant with subtype):
     "用户同意了 GRDB 方案"
     "用户拒绝了 SQL 留在 Database"
     "用户默认接受了 Sparkle 方案"

2. purpose_body (150-300 chars, plain text):
   Quote/paraphrase agent's HEAD/MID/TAIL. STRICT: no facts beyond input.
   Body MAY mention user's reaction in flowing prose (not as title prefix).

3. subtype — choose from acceptance × act + size:
     decision_taken / decision_soft / decision_rejected /
     unclaimed_proposal_large / unclaimed_proposal_small /
     rationale_accepted / rationale_soft /
     unclaimed_explain_large / unclaimed_explain_small /
     clarify_open / report_observed

   For act=clarify with no answer → clarify_open. For act=report only
   when user later affirmed (acceptance hard/soft) → report_observed.

OUTPUT (strict JSON):
{"framings": [{"unit_id": "u123", "purpose_title": "...", "purpose_body": "...", "subtype": "..."}]}
"""


def _gather_task_agent_units(task: Task, all_units: dict[str, AtomicUnit],
                              all_turns: list[DialogueTurn],
                              unit_to_turn: dict | None = None) -> list[dict]:
    """For a task, collect its agent units with their head/tail/mid context."""
    # Build unit_id → turn map for accessing agent_split
    if unit_to_turn is None:
        unit_to_turn = {u.id: turn for turn in all_turns for u in turn.units}

    items = []
    for uid in task.linked_unit_ids:
        u = all_units.get(uid)
        if u is None or u.speaker != "agent":
            continue
        if u.act not in ("propose", "explain", "clarify", "report"):
            continue
        turn = unit_to_turn.get(uid)
        # Adapter-supplied per-turn split (replaces deprecated agent_segments)
        sp = (turn.agent_split if turn else None) or {}
        head = sp.get("head") or u.text or ""
        tail = sp.get("tail") or ""
        truncated = int(sp.get("truncated_chars") or 0)
        # "large" = original agent text > 400 chars (any truncation occurred).
        # Reading-without-objection over a substantial reply counts as soft acceptance.
        is_large = bool(turn and (truncated > 0 or len(turn.agent_raw) > 400))
        items.append({
            "unit_id": u.id,
            "act": u.act,
            "acceptance": u.acceptance or "unclaimed",
            "is_large": is_large,
            "head": head[:600],
            "tail": tail[:800],
            "truncated_chars": truncated,
        })
    return items


def _gather_user_context(task: Task, all_units: dict[str, AtomicUnit]) -> list[dict]:
    """Adjacent user units providing context (constrain/affirm/reject text)."""
    out = []
    for uid in task.linked_unit_ids:
        u = all_units.get(uid)
        if u is None or u.speaker != "human":
            continue
        if u.act in ("constrain", "affirm", "reject"):
            out.append({"act": u.act, "text": u.text[:80]})
    return out[:8]  # cap


def _format_task_block(task: Task, goal: Goal, agent_items: list[dict],
                       user_items: list[dict]) -> str:
    """Render one task's framing input as text block."""
    lines = [f"### task_id={task.id}"]
    lines.append(f"goal_intent: {goal.intent[:120]}")
    lines.append(f"task_name: {task.name[:120]}")
    if user_items:
        lines.append("user_reactions:")
        for ui in user_items:
            lines.append(f"  - [{ui['act']}] {ui['text']}")
    lines.append("agent_units:")
    for ai in agent_items:
        size_tag = "large" if ai.get("is_large") else "small"
        lines.append(f"  - unit_id={ai['unit_id']} act={ai['act']} acceptance={ai['acceptance']} size={size_tag}")
        lines.append(f"    HEAD: {ai['head']}")
        if ai.get("truncated_chars", 0) > 0:
            lines.append(f"    […{ai['truncated_chars']} chars omitted…]")
        if ai["tail"]:
            lines.append(f"    TAIL: {ai['tail']}")
    return "\n".join(lines)


def _block_size(block: str) -> int:
    return len(block)


def _batch_blocks(blocks: list[tuple[str, dict]]) -> list[list[tuple[str, dict]]]:
    """Group (text_block, metadata) tuples into batches respecting agent_unit count
    + char budget. Stage 17: agent_unit count is the primary cap (output-bound),
    char budget is secondary (input-bound, almost never binds first)."""
    out: list[list[tuple[str, dict]]] = []
    current: list[tuple[str, dict]] = []
    current_size = 0
    current_units = 0
    for block, meta in blocks:
        size = _block_size(block)
        items = len(meta["agent_items_by_uid"])
        if current and (current_units + items > BATCH_MAX_AGENT_UNITS
                        or current_size + size > BATCH_MAX_INPUT_CHARS):
            out.append(current)
            current = []; current_size = 0; current_units = 0
        current.append((block, meta))
        current_size += size
        current_units += items
    if current:
        out.append(current)
    return out


def _parse_response(content: str) -> list[dict]:
    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
        return list(data.get("framings", []))
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            return []
        depth = 0
        for i, c in enumerate(text[start:], start):
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return list(json.loads(text[start:i+1]).get("framings", []))
                    except json.JSONDecodeError:
                        return []
        return []


def _fallback_framing(unit: AtomicUnit, agent_items_by_uid: dict[str, dict]) -> tuple[str, str]:
    item = agent_items_by_uid.get(unit.id)
    if item is None:
        return (unit.text[:PURPOSE_TITLE_MAX], unit.text[:PURPOSE_BODY_MAX])
    title = item["head"][:PURPOSE_TITLE_MAX].strip()
    body_parts = [item["head"][:200]]
    if item.get("truncated_chars", 0) > 0:
        body_parts.append(f"[…{item['truncated_chars']} chars omitted…]")
    if item["tail"]:
        body_parts.append(item["tail"][:100])
    body = " ".join(body_parts)[:PURPOSE_BODY_MAX]
    return title, body


def _frame_batch_with_split(batch: list[tuple[str, dict]], verbose: int = 1,
                              _depth: int = 0) -> list[dict]:
    """Run framing on a batch with split-on-missing recovery (mirrors L1's
    _call_with_split). If the LLM omits some unit_ids in its framings array
    (common with large batches), recursively retry just the affected tasks at
    half-batch size until each missing item gets a dedicated retry.

    Returns merged framings list (may include duplicates by unit_id — caller
    dedupes by keeping first).
    """
    if not batch:
        return []
    user_msg = "\n\n".join(b[0] for b in batch)
    expected_uids: set[str] = set()
    for _, meta in batch:
        expected_uids.update(meta["agent_items_by_uid"].keys())

    try:
        content = copilot_api.chat_cheap(SYSTEM_PROMPT, user_msg, stage="framing")
        framings = _parse_response(content)
    except copilot_api.RequestBudgetExceeded:
        raise
    except Exception as e:
        if verbose >= 1:
            print(f"\n     {'  '*_depth}err({len(batch)}t):{str(e)[:50]}",
                  end=" ", flush=True)
        framings = []

    returned_uids = {f.get("unit_id") for f in framings if isinstance(f, dict)}
    missing_uids = expected_uids - returned_uids
    if not missing_uids:
        return framings

    missing_tasks = [(blk, meta) for blk, meta in batch
                       if any(uid in missing_uids for uid in meta["agent_items_by_uid"])]
    if not missing_tasks:
        return framings

    if len(missing_tasks) == 1:
        # Final retry — single task; if LLM still omits, accept fallback
        if verbose >= 1:
            print(f"\n     {'  '*_depth}1-task retry ({len(missing_uids)} missing)",
                  end=" ", flush=True)
        try:
            content2 = copilot_api.chat_cheap(SYSTEM_PROMPT, missing_tasks[0][0], stage="framing")
            framings.extend(_parse_response(content2))
        except copilot_api.RequestBudgetExceeded:
            raise
        except Exception:
            pass
        return framings

    mid = len(missing_tasks) // 2
    if verbose >= 1:
        print(f"\n     {'  '*_depth}split {len(missing_tasks)}→{mid}+{len(missing_tasks)-mid} "
              f"({len(missing_uids)} missing)",
              end=" ", flush=True)
    framings.extend(_frame_batch_with_split(missing_tasks[:mid], verbose, _depth + 1))
    framings.extend(_frame_batch_with_split(missing_tasks[mid:], verbose, _depth + 1))
    return framings


def _all_tasks(goal: Goal) -> list[Task]:
    out: list[Task] = []
    def walk(t: Task):
        out.append(t)
        for s in t.subtasks: walk(s)
    for t in goal.tasks: walk(t)
    return out


def frame_session(session: Session, verbose: int = 1) -> Session:
    """Run framing pass over all tasks in the session. Mutates units in place."""
    all_units = {u.id: u for turn in session.turns for u in turn.units}
    unit_to_turn = {u.id: turn for turn in session.turns for u in turn.units}

    # Build (block, metadata) pairs per task. metadata holds agent_items_by_uid for fallback.
    # Per-turn agent_content (Stage 17) means a long task can accumulate many agent units.
    # Tasks with > TASK_BLOCK_MAX_AGENT_UNITS are split into multiple chunks; each chunk
    # gets its own block carrying the full task header so the LLM has context for each call.
    blocks: list[tuple[str, dict]] = []
    skipped_no_agent = 0
    split_tasks = 0
    for goal in session.goals:
        for task in _all_tasks(goal):
            agent_items = _gather_task_agent_units(task, all_units, session.turns, unit_to_turn)
            if not agent_items:
                skipped_no_agent += 1
                continue
            user_items = _gather_user_context(task, all_units)
            if len(agent_items) > TASK_BLOCK_MAX_AGENT_UNITS:
                split_tasks += 1
            for chunk_start in range(0, len(agent_items), TASK_BLOCK_MAX_AGENT_UNITS):
                chunk = agent_items[chunk_start:chunk_start + TASK_BLOCK_MAX_AGENT_UNITS]
                block = _format_task_block(task, goal, chunk, user_items)
                meta = {
                    "task_id": task.id,
                    "agent_items_by_uid": {ai["unit_id"]: ai for ai in chunk},
                }
                blocks.append((block, meta))

    if not blocks:
        if verbose >= 1: print("   no agent units to frame")
        return session

    batches = _batch_blocks(blocks)
    if verbose >= 1:
        print(f"   {len(blocks)} blocks ({split_tasks} large tasks split) → {len(batches)} batches "
              f"(skipped {skipped_no_agent} agent-less tasks)")

    success = failed = 0
    for bi, batch in enumerate(batches):
        if verbose >= 1:
            n_units = sum(len(m["agent_items_by_uid"]) for _, m in batch)
            print(f"   batch {bi+1}/{len(batches)} ({len(batch)} blocks / {n_units} units, "
                  f"{sum(len(b[0]) for b in batch)} chars)...", end=" ", flush=True)

        framings = _frame_batch_with_split(batch, verbose=verbose)

        # Dedupe by unit_id (split-recovery may re-return same uid in retries)
        framings_by_uid: dict[str, dict] = {}
        for f in framings:
            if not isinstance(f, dict): continue
            uid = f.get("unit_id")
            if uid and uid not in framings_by_uid:
                framings_by_uid[uid] = f

        # Combined fallback metadata for this batch
        combined_meta = {}
        for _, meta in batch:
            combined_meta.update(meta["agent_items_by_uid"])

        # Walk all units mentioned in this batch and apply framing or fallback
        for _, meta in batch:
            for uid in meta["agent_items_by_uid"].keys():
                u = all_units.get(uid)
                if u is None: continue
                f = framings_by_uid.get(uid)
                if f and f.get("purpose_title") and f.get("purpose_body"):
                    u.framing_failed = False
                    u.purpose_title = str(f["purpose_title"])[:PURPOSE_TITLE_MAX]
                    u.purpose_body = str(f["purpose_body"])[:PURPOSE_BODY_MAX]
                    success += 1
                else:
                    title, body = _fallback_framing(u, combined_meta)
                    u.purpose_title = title
                    u.purpose_body = body
                    u.framing_failed = True
                    failed += 1
        if verbose >= 1: print("✓")

    if verbose >= 1:
        print(f"   framing: {success} ok / {failed} fallback")
    return session
