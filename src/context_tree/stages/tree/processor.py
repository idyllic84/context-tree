"""C Layer 2 — tree mutations from atomic units + current tree.

LLM ONLY decides tree structure. Cannot invent ids.
- Available unit_ids: explicitly listed in [UNITS]
- Available tree ids: explicitly listed in [TREE]
- Mutations referencing other ids → state_machine rejects them

Per batch flow:
  L1 produces units → L2 takes units batch + tree state → mutations → state_machine.apply

L2 batches are sized INDEPENDENTLY of L1 batches (`batch_units_for_l2`):
L2 input is a compact unit list (~80-150 chars/unit) — much smaller per item
than L1's raw dialogue, so L2 can fit ~2x more items per batch without LLM
output budget concern. Conservative defaults: 200 units / 20K chars per batch.
"""
import json
import time
import context_tree.common.llm as copilot_api
from context_tree.common.models import DialogueTurn, AtomicUnit


# L2 batch sizing — independent of L1's BATCH_MAX_TURNS / BATCH_MAX_INPUT_CHARS.
# Conservative bump: roughly 2× the units per batch L1 would have produced
# (50 turn × ~2 unit/turn ≈ 100 units → 200 units). Keep input chars modest
# because tree_view already consumes ~30K of prompt.
L2_BATCH_MAX_UNITS = 150
L2_BATCH_MAX_INPUT_CHARS = 15000


def batch_units_for_l2(turns: list[DialogueTurn],
                         max_units: int = L2_BATCH_MAX_UNITS,
                         max_chars: int = L2_BATCH_MAX_INPUT_CHARS,
                         ) -> list[tuple[list[AtomicUnit], list[DialogueTurn]]]:
    """Group turns into L2 batches by unit count + estimated char budget.

    Returns list of (units, source_turns) tuples — units in dialogue order;
    source_turns is the subset of `turns` whose units fall in this batch
    (used to construct the [TIMELINE] block).

    Turns with no units are skipped. A turn's units always stay in one batch
    (we don't split a turn's units across L2 batches).
    """
    out: list[tuple[list[AtomicUnit], list[DialogueTurn]]] = []
    cur_units: list[AtomicUnit] = []
    cur_turns: list[DialogueTurn] = []
    cur_chars = 0
    for t in turns:
        if not t.units: continue
        t_chars = sum(80 + len(u.text or "") for u in t.units)
        if cur_units and (len(cur_units) + len(t.units) > max_units
                          or cur_chars + t_chars > max_chars):
            out.append((cur_units, cur_turns))
            cur_units, cur_turns, cur_chars = [], [], 0
        cur_units.extend(t.units)
        cur_turns.append(t)
        cur_chars += t_chars
    if cur_units:
        out.append((cur_units, cur_turns))
    return out


SYSTEM_PROMPT = """Tree structure decision for human↔AI-coding-agent dialogue.
CN/EN/mixed; output matches source language.

You decide ONLY the tree structure (goals, tasks, subtasks, mutations).
Atomic units are ALREADY EXTRACTED — you reference them by id.

INPUT:
  [TREE]     — current Goal/Task tree state. {} on first batch.
  [TIMELINE] — per-turn date + boundary markers (long_gap / cwd_changed /
               branch_changed). Use as STRONG hint for topic shifts: a long_gap
               or branch_changed between turns often marks a new goal/task
               boundary. cwd_changed often signals different work area.
  [UNITS]    — units extracted from this batch (id, speaker, act, target, text).
  [REFERENCED_PRIOR_UNITS] — existing feedback targets from earlier batches.
               Reference only IDs in these two blocks; never invent unit IDs.

## Hierarchy model

USER GOAL  (Goal class — usually 1 per session, sometimes pivots)
  ├─ Task   (functions as agent_goal when has subtasks)
  │   ├─ Task (leaf = agent_task — concrete work)
  │   └─ Task (leaf)
  └─ Task (leaf)

A task with subtasks IS the agent_goal layer. Leaf tasks are concrete actions.

## Two-step thinking BEFORE output

STEP 1 — Build LOCAL tree from this batch's units (ignore [TREE]):
  - What goals is user pursuing in this batch? (usually 1)
  - Decompose into tasks/subtasks based on the WORK STRUCTURE
  - Set proper hierarchy: sub-steps NEST under their parent task

STEP 2 — Reconcile LOCAL tree with EXISTING [TREE]:
  - Compare local goals to [TREE] goals as WHOLES, not per-task lookup
  - If local goal matches existing goal in theme → reuse existing goal id,
    attach local tasks under it (don't push_goal duplicate)
  - If [TREE] has multiple goals on same theme → emit merge_goals first
  - Only push_goal for genuinely new themes

Then emit mutations encoding the reconciled tree.

## Tree mutations (applied IN ORDER)

  push_goal       {intent, source_unit_id} → assigns g<N>
  push_task       {parent_id (g/t), name, source_unit_id} → assigns t<N>
  push_subtask    {parent_id (must be t), name, source_unit_id}
  reparent        {task_id, new_parent_id} → fix hierarchy mistakes
  merge_goals     {into: "g<N>", from: ["g<M>"]} → consolidate duplicate goals
  set_active      {task_id} → switch active task pointer
  affirm_propose  {task_id, unit_id, outcome_summary} → task complete
  reject_propose  {task_id, unit_id, correction_text?} → task abandoned alt
  affirm_explain  {task_id, unit_id} → add to lessons
                  These three ops use the AGENT unit being affirmed/rejected,
                  never the human feedback unit. Example: u4 [human/affirm]
                  target=u3 means affirm_propose(..., unit_id="u3"), not "u4".
                  Link u4 separately with link_unit.
  soft_complete   {task_id, propose_unit_id?, explain_unit_id?}
                  → ONLY when human pivots without explicit affirm/reject
  add_constraint  {container_id (g/t), text, source_unit_id}
                  Pick container_id by SCOPE inference (descendants of container
                  inherit this constraint; siblings outside don't):
                    • User says "use TS" at session start (broad, no specific task) →
                      container_id = ROOT goal of the session
                    • User says "用 X 替代 Y" mid-task on a domain-general principle →
                      container_id = current task's parent goal
                    • User says "for THIS task: use X" →
                      container_id = current active task (default narrowest)
                    • User CONTRADICTS an earlier constraint ("X 不行,改 Z") →
                      add NEW constraint at SAME node where the original was, with
                      text describing the new state ("不要 X, 改用 Z"). Both coexist.
                      Retrieval LLM will read both and pick narrower-scope as override.
                  When unsure, prefer narrower (current task) — broader constraints
                  affect more siblings and cost more to retract later.
  add_term        {task_id, text}
  mark_abandoned  {task_id, reason}
  link_unit       {task_id, unit_id} → attach a human/agent unit to the task it serves
                  Link every task-relevant unit, including reports and explanations.
                  Units within a turn are ordered human then following agent response.
                  A feedback target belongs to its earlier task, even if a later unit
                  in the same human message starts another task.
  touch           {branch_id} → bump access timestamp only

## CRITICAL id rules

- Mutation `task_id` / `goal_id` / `container_id` / `parent_id`:
  must be EXISTING tree id from [TREE], OR a new id assigned by an EARLIER
  mutation in your output. Never invent.
- Mutation `unit_id` / `source_unit_id`: must be in [UNITS]. Never invent.
- New goal/task ids: state machine assigns next sequential g<N>/t<N> when you
  emit push_goal / push_task / push_subtask. To reference a task you JUST pushed
  in this same output, predict its id based on existing [TREE]: if [TREE] has
  max t_id = t29, your first push_task gets t30, second gets t31, etc.
- NEVER emit literal "t<next>" or "g<next>" — those are placeholders, not ids.
  Always use concrete numbers based on counting from [TREE]'s max id.

## OUTPUT (strict JSON)

{"tree_mutations": [{"op": str, ...op-specific fields...}]}

If tree is correctly reflected by current state + your few additions, output
{"tree_mutations": []}.
"""


def _format_tree(state_view: dict) -> str:
    return json.dumps(state_view, ensure_ascii=False, indent=2)


def _format_units(units: list[AtomicUnit]) -> str:
    """Compact unit list for L2 — id + speaker + act + target + scope + text hint."""
    lines = []
    for u in units:
        parts = [f"{u.id} [{u.speaker}/{u.act}]"]
        if u.target: parts.append(f"target={u.target}")
        if u.scope: parts.append(f"scope={u.scope}")
        if u.parent_id: parts.append(f"parent_id={u.parent_id}")
        if u.for_task_id: parts.append(f"existing_task={u.for_task_id}")
        if u.correction: parts.append(f"correction={u.correction[:40]!r}")
        if u.text: parts.append(f"text={u.text[:200]!r}")
        lines.append("  " + " ".join(parts))
    return "\n".join(lines)


def _parse(content: str) -> dict | None:
    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0: return None
        depth = 0
        for i, c in enumerate(text[start:], start):
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try: return json.loads(text[start:i+1])
                    except json.JSONDecodeError: return None
        return None


def _format_timeline(turns: list) -> str:
    """Render per-turn temporal markers (date, meta_signals) — used by L2 to
    detect topic boundaries (long_gap, cwd_changed, branch_changed often
    correlate with new goal/task)."""
    if not turns: return "(none)"
    lines = []
    for t in turns:
        date = (t.timestamp or "")[:10]
        unit_ids = ",".join(u.id for u in t.units) or "—"
        sigs = ", ".join(t.meta_signals) if getattr(t, "meta_signals", None) else ""
        line = f"  turn{t.turn_id} [{date}] units={unit_ids}"
        if sigs: line += f"  ⚑{sigs}"
        lines.append(line)
    return "\n".join(lines)


def build_tree_for_batch(state_machine, batch_units: list[AtomicUnit],
                          model: str | None = None, verbose: int = 1,
                          batch_turns: list = None) -> list[dict]:
    """L2: take batch units + current tree state → emit tree mutations and apply.
    `batch_turns` (optional, recommended): the DialogueTurn list this batch came from,
    used to surface temporal boundary signals (long_gap, cwd_changed, branch_changed)
    to the LLM so it can detect topic shifts.
    Returns list of mutations applied."""
    if not batch_units:
        return []

    state_view = state_machine.compose_view(char_budget=30000)
    next_g = state_machine._goal_counter + 1
    next_t = state_machine._task_counter + 1

    body = (
        f"[NEXT_IDS]\nNext push_goal will assign g{next_g}. "
        f"Next push_task/push_subtask will assign t{next_t}. "
        f"Increment by 1 for each push in your output.\n\n"
        "[TREE]\n" + _format_tree(state_view) + "\n\n"
        + "[TIMELINE] (turn dates + boundary markers ⚑; long_gap/cwd/branch shifts often signal topic change)\n"
        + _format_timeline(batch_turns or []) + "\n\n"
        + "[UNITS] (new units in chronological human/response order)\n"
        + _format_units(batch_units) + "\n\n"
        + "[REFERENCED_PRIOR_UNITS] (valid earlier feedback targets, retain their task ownership)\n"
        + _format_units([state_machine._unit_by_id[uid] for uid in
                         dict.fromkeys(u.target for u in batch_units if u.target)
                         if uid in state_machine._unit_by_id]) + "\n\n"
        + "Decide tree mutations.\n"
    )

    if verbose >= 1:
        print(f"   [L2] {len(batch_units)} units...", end=" ", flush=True)
    bt = time.time()

    content = copilot_api.chat_content(SYSTEM_PROMPT, body, model=model, stage="tree")
    data = _parse(content)

    if not isinstance(data, dict) or not isinstance(data.get("tree_mutations"), list):
        raise ValueError("L2 returned invalid tree_mutations")

    muts = data.get("tree_mutations", []) or []
    warnings = state_machine.apply_mutations(muts, batch_units)
    if warnings:
        raise ValueError("L2 invalid mutations: " + "; ".join(warnings[:3]))

    if verbose >= 1:
        print(f"✓ {len(muts)} muts, {len(warnings)} warns ({time.time()-bt:.1f}s)")
        if warnings:
            for w in warnings[:5]:
                print(f"     ⚠ {w}")
    return muts
