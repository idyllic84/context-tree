"""C tree_extractor — single LLM call per batch produces atomic units + tree mutations + segments.

Replaces V2-B v2's preprocessor_v2 + atomizer_v2 (two separate LLM calls).
Output is consumed by state_machine.apply_mutations + tier2_projection.

LLM sees current tree state (hot subtree + cold metadata) so its decisions
are tree-aware:
  - for_task_id resolves against visible tasks (no guessing)
  - affirm/reject targets cross-batch agent units (visible in recent activity)
  - skip detection sees session topology
  - mutations encode "this propose is REFINING task X" vs "REPLACING with new task"
"""
import json
import time
import context_tree.common.llm as copilot_api
from context_tree.common.models import DialogueTurn, AtomicUnit


# Batching budgets
BATCH_MAX_INPUT_CHARS = 25000
BATCH_MAX_TURNS = 50
HOT_TREE_BUDGET = 30000    # generous; tree is summary content, not raw text
RECENT_ACTIVITY_BUDGET = 2000  # chars for recent agent activity hint
RECENT_AGENT_KEEP = 30     # how many recent agent units to summarize


SYSTEM_PROMPT = """Tree-aware extraction for human↔AI-coding-agent dialogue.
CN/EN/mixed; output matches source language.

INPUT:
  [TREE] — current Goal/Task tree (hot subtree + cold metadata). {} on first batch.
  [RECENT] — last N agent unit summaries from prior batches (id+act+80c text).
  [TURNS] — current batch dialogue turns (raw agent_raw + human_raw per turn).

## Hierarchy model — CRITICAL

Top: USER GOAL (what user ultimately wants — usually 1, sometimes pivots)
  ├─ AGENT TASK or AGENT GOAL (decomposition by user/agent)
  │    ├─ AGENT TASK (concrete work)
  │    └─ AGENT TASK (concrete work)
  └─ AGENT GOAL ...

A "task with subtasks" in the tree = an agent goal layer (intermediate planning).
A "leaf task" = concrete agent action.

## Goal REUSE — strict rule

Before push_goal, scan [TREE]. If any existing goal's intent covers the new
work topic (auth/UI/build/migration/etc), DO NOT push_goal — use that
existing goal's id (g<N>) as parent for new push_task.

Examples of WRONG goal proliferation to AVOID:
- Existing g2 "Backend User System Planning" + new auth work → push_task under g2,
  NOT push_goal "Implement and verify Authentication System"
- Existing g1 "FRE redesign" + new FRE styling → push_task under g1,
  NOT push_goal "FRE styling improvements"

Only push_goal when the new work is a GENUINELY DIFFERENT user goal
(see "User goal pivot" rules below).

## When push_subtask vs push_task

- New work is a different USER GOAL → push_goal (rare!)
- New work is sibling-level under same USER GOAL → push_task
- New work CONCEPTUALLY belongs as a step of an existing task → push_subtask under that task

GOOD example: user goal = "implement auth system"
  - "Setup OAuth flow" → push_task (under user goal)
  - "Design JWT structure" → push_task (under user goal, sibling to OAuth)
  - "JWT key rotation" → push_subtask under "Design JWT structure" (it's a step of JWT)
  - "Implement KeyVault rotation" → push_subtask under "JWT key rotation"
  - "Document auth" → push_task (under user goal)

## User goal pivot detection

Watch for signals that USER changes the top-level goal:
  - explicit "let's do something else" / "回到上次那个问题" / "换个事情做"
  - long_gap meta_signal AND new topic
  - cwd/branch_changed meta_signal + unrelated content
On pivot → push_goal (new), set_active to its first task.
Without pivot → push_task / push_subtask under current goal.

## Reorganization

If you realize a recently-added top-level task is actually a subtask of an
earlier task (or of another task in the tree), use the reparent op to fix:
  reparent {task_id, new_parent_id}
This moves the task (and its subtree) to a new parent. Only use for genuine
hierarchy fixes; not for routine status changes.

## Per-turn output

For each turn produce:
  - skip (bool): true ONLY if BOTH human side and agent side have no decision content
  - human_normalized (str): resolve deictic refs from agent_raw, else echo human_raw
  - agent_segments (list): empty [] if agent has no decision content (pure progress
    / tool result / acknowledgment). Otherwise one entry per distinct agent activity:
      [{"activity": "propose|explain|clarify|report",
        "head": "≤200 chars from start (full text if <200)",
        "tail": "≤200 chars from end (empty if text <200)",
        "mid_summary": null OR "≤150 char summary if original > 600 chars"}]
  - units (list): atomic dialogue units

Unit fields:
  - id: "u<N>" — assign next monotonic N (continue from last batch's max)
  - speaker: "agent" | "human"
  - act: STRICTLY one of:
      Human: instruct, constrain, ask, affirm, reject, answer, report
      Agent: propose, explain, clarify, report
  - target: "u<M>" only on affirm/reject (points to prior agent unit, may be from prior batch)
  - correction: optional str on reject (corrective text from human)
  - scope: only on instruct, one of: new_goal, new_task, subtask, null
  - parent_id: only on subtask instruct (points to parent task's source unit)
  - for_task_id: REQUIRED on agent propose/explain — task id (t<N>) it serves
  - text: ≤30-char activity hint OR empty (downstream uses agent_segments)

CRITICAL act rules:
- "ok" / "好的" / "1" alone = affirm with target = most recent unclaimed propose
- Long human turn with multiple acts → split into multiple units (instruct + constrain + ...)
- Agent activity tag count = agent_segments count = agent units count

## Tree mutations

Atomic ops applied IN ORDER (later ops can reference ids from earlier ops in same batch):
  push_goal       {intent, source_unit_id} → assigns g<N>. ONLY for genuine USER goal pivots
  push_task       {parent_id (g/t), name, source_unit_id} → assigns t<N>
  push_subtask    {parent_id (must be t), name, source_unit_id}
  reparent        {task_id, new_parent_id} → fix hierarchy mistakes (sibling→subtask etc)
  merge_goals     {into: "g<N>", from: ["g<M>", ...]} → CONSOLIDATE duplicate goals
                  → use BEFORE adding new tasks if you notice [TREE] has duplicate goals
                    (e.g. English "Auth System" + 中文 "认证系统" = same topic).
                    All tasks/constraints from `from` move to `into`, `from` deleted.
  set_active      {task_id} → switch active task pointer
  affirm_propose  {task_id, unit_id, outcome_summary} → task complete
  reject_propose  {task_id, unit_id, correction_text?} → task abandoned alt
  affirm_explain  {task_id, unit_id} → add to lessons
  soft_complete   {task_id, propose_unit_id?, explain_unit_id?}
                  → ONLY when human pivots to different task without explicit affirm/reject
                    DO NOT call before user has actually pivoted away
  add_constraint  {container_id (g/t), text, source_unit_id}
  add_term        {task_id, text}
  mark_abandoned  {task_id, reason}
  touch           {branch_id} → bump access timestamp only

## Cross-batch consolidation — leverage your view of the FULL tree

You see the COMPLETE tree (all goals from prior batches). Use this to:
1. Before push_goal: check if ANY existing goal in [TREE] matches the new topic
   even with different language. If yes, push_task under it instead.
2. Before push_task: if there are multiple existing goals on the same theme
   (e.g. created in earlier batches under different names), emit merge_goals
   to consolidate them FIRST, then push_task under the surviving one.
3. emit merge_goals/reparent ops as needed to cleanup AS YOU EXTRACT (don't
   leave duplicates for a separate pass).

## Two-step thinking — DO THIS BEFORE OUTPUT

For every batch, mentally walk these two steps holistically:

STEP 1 — Build this batch's LOCAL TREE from [TURNS] alone (ignore [TREE]):
- Read all turns as a whole. What goals is user pursuing? (usually 1, sometimes 0-2)
- Decompose each goal into tasks/subtasks based on the WORK STRUCTURE you see.
- Set proper hierarchy: tasks that are sub-steps of bigger tasks should nest.
This produces a local mini-tree representing "this batch's contribution".

STEP 2 — Reconcile LOCAL TREE with EXISTING [TREE]:
- Compare your local tree's goals to [TREE]'s goals as WHOLES (not per-turn or
  per-task lookup): are any of your local goals the same theme as an existing one?
- If your local goal matches an existing goal → use existing goal id, attach
  your local goal's tasks under it.
- If [TREE] already has multiple goals that should consolidate (visible to you
  from [TREE]) → emit merge_goals first.
- Only push_goal for genuinely new themes.

Then emit mutations that encode the reconciled tree. Do not output the local
tree itself — just the mutations.

This two-step process avoids:
- Pushing duplicate goals (you reconcile whole goals against whole goals)
- Flat sibling explosion (you decide internal hierarchy LOCALLY before merging)
- Per-turn churn (you don't decide turn-by-turn how to slot into existing tree)

Optional top-level field:
  expand_branches: ["g<N>", "t<N>", ...]
                  → request full subtree of cold branches; on emit, your output
                    is discarded and call re-issued with expanded tree.

## Few-shot example

INPUT abbreviated:
  turn 5: agent="Suggest GRDB over SwiftData (macOS 15 NULL crash)"
          human="可以试试，但先看看 SwiftData 在 14 上稳不稳"
  turn 6: agent="SwiftData on macOS 14 looks stable per docs"
          human="ok 那就用 SwiftData"

OUTPUT mutations:
  [{op:push_goal, intent:"DB selection", source_unit_id:"u10"},
   {op:push_task, parent_id:"g1", name:"Pick DB lib", source_unit_id:"u10"},
   {op:reject_propose, task_id:"t1", unit_id:"u11",
                       correction_text:"先验证 SwiftData 在 macOS 14 稳定性"},
   {op:affirm_propose, task_id:"t1", unit_id:"u13",
                       outcome_summary:"Use SwiftData on macOS 14"}]

## OUTPUT (strict JSON, single object, no markdown)

{
  "turns": [
    {"turn_id": int, "skip": bool, "human_normalized": str,
     "agent_segments": [...], "units": [...]}
  ],
  "tree_mutations": [{"op": str, ...op-specific fields...}],
  "expand_branches": []
}

Violations of act vocabulary or id prefix convention will be discarded.
"""


def _format_recent_activity(recent_units: list[AtomicUnit], budget: int = RECENT_ACTIVITY_BUDGET) -> str:
    """Compact summary of recent agent units for cross-batch reference."""
    if not recent_units:
        return "(none)"
    lines = []
    used = 0
    for u in recent_units[-RECENT_AGENT_KEEP:]:
        text_preview = (u.text or "")[:80].replace("\n", " ")
        line = f"  {u.id} [{u.speaker}/{u.act}] {text_preview}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines) if lines else "(none)"


def _format_turns(batch: list[DialogueTurn]) -> str:
    """Format batch turns as input to LLM."""
    parts = []
    for t in batch:
        parts.append(f"## turn {t.turn_id}")
        if t.meta_signals:
            parts.append(f"meta_signals: {', '.join(t.meta_signals)}")
        if t.recent_paths_context:
            parts.append("recent_files:")
            for e in t.recent_paths_context[:5]:
                parts.append(f"  - {e['path']} ({e['action']}, {e['turns_ago']}t ago)")
        parts.append(f"agent_raw:\n{t.agent_raw}")
        parts.append(f"human_raw:\n{t.human_raw}")
        parts.append("")
    return "\n".join(parts)


def _compose_prompt_body(state_view: dict, recent_units: list[AtomicUnit],
                          batch: list[DialogueTurn]) -> str:
    """Compose full user-message body for the extraction LLM call."""
    parts = ["[TREE]", json.dumps(state_view, ensure_ascii=False, indent=2), ""]
    parts.append("[RECENT]")
    parts.append(_format_recent_activity(recent_units))
    parts.append("")
    parts.append("[TURNS]")
    parts.append(_format_turns(batch))
    return "\n".join(parts)


def _parse_response(content: str) -> dict | None:
    """Parse LLM JSON output; tolerant to markdown fences and trailing junk."""
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


def _batch_turns(turns: list[DialogueTurn]) -> list[list[DialogueTurn]]:
    """Group turns by char + count cap."""
    out: list[list[DialogueTurn]] = []
    cur: list[DialogueTurn] = []
    cur_size = 0
    for t in turns:
        size = len(t.agent_raw) + len(t.human_raw) + 100
        if cur and (cur_size + size > BATCH_MAX_INPUT_CHARS or len(cur) >= BATCH_MAX_TURNS):
            out.append(cur); cur = []; cur_size = 0
        if not cur and size > BATCH_MAX_INPUT_CHARS:
            out.append([t]); continue
        cur.append(t); cur_size += size
    if cur: out.append(cur)
    return out


def extract_session(turns: list[DialogueTurn], state_machine,
                     model: str | None = None, verbose: int = 1) -> tuple[list[dict], list[AtomicUnit]]:
    """Run merged Tier 1+2 extraction over all batches of a session.

    Returns (all_mutations, all_units) — mutations applied to state_machine in place.
    Per-batch flow:
      1. compose prompt with current tree state + recent units + batch turns
      2. LLM call → parse {turns, tree_mutations, expand_branches?}
      3. If expand_branches: drop output, re-issue with expanded tree
      4. Else: build AtomicUnits from per-turn output, fill turn fields
      5. state_machine.apply_mutations(mutations, batch_units)
      6. Append batch units to recent_units registry for next batch
    """
    batches = _batch_turns(turns)
    if verbose >= 1:
        print(f"   {len(turns)} turns → {len(batches)} batches "
              f"(budget={BATCH_MAX_INPUT_CHARS}c / {BATCH_MAX_TURNS}turns)")

    all_mutations: list[dict] = []
    all_units: list[AtomicUnit] = []
    recent_units: list[AtomicUnit] = []
    next_unit_n = 0

    for bi, batch in enumerate(batches):
        if verbose >= 1:
            print(f"   batch {bi+1}/{len(batches)} ({len(batch)} turns)...", end=" ", flush=True)
        bt = time.time()

        state_view = state_machine.compose_view(char_budget=HOT_TREE_BUDGET)

        # Round 1
        body = _compose_prompt_body(state_view, recent_units, batch)
        data = _call_with_split_retry(body, batch, model, verbose)
        if data is None:
            if verbose >= 1: print(f"✗ batch failed entirely ({time.time()-bt:.1f}s)")
            continue

        # Optional round 2 if LLM requested expansion
        expand_ids = data.get("expand_branches", []) or []
        if expand_ids:
            if verbose >= 1: print(f"\n     expand_branches={expand_ids}", end=" ", flush=True)
            expanded = state_machine.expand(expand_ids)
            # Merge expanded subtree into hot view for round 2
            state_view2 = {"hot": expanded, "cold": state_view.get("cold", [])}
            body2 = _compose_prompt_body(state_view2, recent_units, batch)
            data2 = _call_with_split_retry(body2, batch, model, verbose)
            if data2 is not None:
                data = data2

        # Process turns + units
        batch_units = []
        by_tid = {t.turn_id: t for t in batch}
        for tobj in data.get("turns", []):
            tid = tobj.get("turn_id")
            t = by_tid.get(tid)
            if t is None: continue
            t.skip = bool(tobj.get("skip", False))
            t.human_normalized = str(tobj.get("human_normalized") or t.human_raw)
            t.agent_segments = list(tobj.get("agent_segments") or [])
            for u in tobj.get("units", []) or []:
                if not u.get("id"): continue
                au = _build_unit(u)
                if au is None: continue
                batch_units.append(au)
                t.units.append(au)
                # Track id counter for next batch reference
                try:
                    n = int(au.id.lstrip("u"))
                    next_unit_n = max(next_unit_n, n + 1)
                except ValueError: pass

        # Apply mutations
        muts = data.get("tree_mutations", []) or []
        warnings = state_machine.apply_mutations(muts, batch_units)
        all_mutations.extend(muts)
        all_units.extend(batch_units)

        # Update recent_units (cap to last 200 to bound memory)
        for u in batch_units:
            if u.speaker == "agent":
                recent_units.append(u)
        if len(recent_units) > 200:
            recent_units = recent_units[-200:]

        if verbose >= 1:
            print(f"✓ {len(batch_units)} units, {len(muts)} muts, "
                  f"{len(warnings)} warns ({time.time()-bt:.1f}s)")
        if warnings and verbose >= 1:
            for w in warnings[:10]:
                print(f"     ⚠ {w}")

    return all_mutations, all_units


def _build_unit(u: dict) -> AtomicUnit | None:
    """Validate and construct AtomicUnit from LLM dict. Returns None if invalid."""
    try:
        return AtomicUnit(
            id=str(u["id"]),
            speaker=u.get("speaker", "human"),
            act=u.get("act", "instruct"),
            text=str(u.get("text") or "")[:200],
            target=u.get("target"),
            correction=u.get("correction"),
            scope=u.get("scope"),
            parent_id=u.get("parent_id"),
            for_task_id=u.get("for_task_id"),
        )
    except Exception:
        return None


def _call_with_split_retry(body: str, batch: list[DialogueTurn], model: str | None,
                            verbose: int = 1, _depth: int = 0) -> dict | None:
    """LLM call. On hard failure (no parse / 0 turns), split batch in half and recurse.
    Returns merged {turns, tree_mutations, expand_branches} or None if all fail."""
    expected_ids = {t.turn_id for t in batch}

    try:
        content = (copilot_api.chat_content(SYSTEM_PROMPT, body, model=model)
                   if model else copilot_api.chat_cheap(SYSTEM_PROMPT, body))
        data = _parse_response(content)
    except Exception as e:
        if verbose >= 1: print(f"\n     {'  '*_depth}err({len(batch)}t):{str(e)[:50]}", end=" ", flush=True)
        data = None

    returned_ids = {t.get("turn_id") for t in (data or {}).get("turns", []) if isinstance(t, dict)}
    missing = expected_ids - returned_ids

    if data and not missing:
        return data

    # Split missing turns in half and recurse
    missing_batch = [t for t in batch if t.turn_id in missing]
    if len(missing_batch) <= 1:
        if verbose >= 1: print(f"\n     {'  '*_depth}1 turn final retry", end=" ", flush=True)
        try:
            content = (copilot_api.chat_content(SYSTEM_PROMPT, body, model=model)
                       if model else copilot_api.chat_cheap(SYSTEM_PROMPT, body))
            return _parse_response(content) or data
        except Exception:
            return data

    mid = len(missing_batch) // 2
    if verbose >= 1: print(f"\n     {'  '*_depth}split {len(missing_batch)} → {mid} + {len(missing_batch)-mid}",
                            end=" ", flush=True)
    left = missing_batch[:mid]; right = missing_batch[mid:]
    # Re-compose body for each half (without tree state — we keep current view)
    # Caller's body already has [TREE] section; for split we just substitute [TURNS]
    head, _, _ = body.rpartition("[TURNS]")
    left_body = head + "[TURNS]\n" + _format_turns(left)
    right_body = head + "[TURNS]\n" + _format_turns(right)

    merged_turns: list[dict] = list((data or {}).get("turns", []))
    merged_muts: list[dict] = list((data or {}).get("tree_mutations", []))

    for sub_body, sub_batch in [(left_body, left), (right_body, right)]:
        sub = _call_with_split_retry(sub_body, sub_batch, model, verbose, _depth + 1)
        if sub:
            for t in sub.get("turns", []):
                if t.get("turn_id") in {x.turn_id for x in sub_batch}:
                    merged_turns.append(t)
            merged_muts.extend(sub.get("tree_mutations", []) or [])

    return {"turns": merged_turns, "tree_mutations": merged_muts, "expand_branches": []}
