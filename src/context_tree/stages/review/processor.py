"""Iterative task-tree boundary refinement with validated mutations and stage-specific models."""
import json
import time
import context_tree.common.llm as copilot_api
REVIEW_SYSTEM_PROMPT = """Tree refinement for human↔AI-coding-agent dialogue.
CN/EN/mixed; output matches source language.

You see the COMPLETE Goal/Task tree extracted from a long session. Your job:
identify TREE QUALITY ISSUES and emit refinement mutations to fix them.

Common boundary issues:

1. SPLIT GOALS: Two goals on same theme that should consolidate into one.
   Look for goals with overlapping topics (auth/认证, UI/styling, db/数据库) —
   language differences (EN vs CN) often hide true sameness.
   FIX: merge_goals from→into.

2. UNDER-SEGMENTED: A SINGLE goal that actually contains multiple distinct
   themes that should be separate goals. Look for goals where sibling tasks
   span unrelated topics (e.g. one big "user system" goal containing both
   auth work AND macOS startup debugging — those are different themes).
   FIX: push_goal new + reparent some tasks under it.

3. FLAT WHERE IT SHOULD NEST: Sibling tasks at goal level that conceptually
   share a parent task (e.g. "Setup OAuth" + "Design JWT" + "Configure KeyVault"
   all belong under "Implement Auth" parent task instead of being siblings).
   FIX: reparent siblings under one chosen anchor task.

4. WRONG-GOAL TASKS: A task placed under one goal that actually belongs to
   another. E.g. macOS startup investigation under an auth goal.
   FIX: reparent task under correct goal.

5. NESTED-AS-GOAL: A small goal that's actually a subtask of another goal.
   E.g. "JWT key rotation" as separate goal but should be under "User auth".
   FIX: merge_goals (the small into the larger encompassing one).

6. NOISE: Tiny goals (1 task, vague intent) or tasks that aren't real work.
   FIX: mark_abandoned.

DO NOT:
- Split goals further if current grouping is reasonable
- Reparent tasks just for slight relevance
- Merge goals that are genuinely different topics
- Make changes for the sake of making changes

Available refinement mutations:

  merge_goals     {into: "g<N>", from: ["g<M>"], rationale: "..."}
                  → all tasks/constraints from `from` move to `into`,
                    `from` goals deleted.

  push_goal       {intent: "...", source_unit_id: "u<N>", rationale: "..."}
                  → create new goal (use to split an existing goal). New goal
                    gets next g<N>. Source_unit_id can be the linked_unit of
                    a task you'll reparent under it.

  push_task       {parent_id: "g<N>" or "t<N>", name: "...", source_unit_id: "u<N>", rationale: "..."}
                  → create new aggregating parent task to bundle siblings under.

  reparent        {task_id, new_parent_id, rationale: "..."}
                  → move task (and subtree) under different parent
                    (g<N> for goal-level, t<N> for subtask).

  mark_abandoned  {task_id, reason}
                  → mark a noise/irrelevant task as abandoned.

INPUT format:
  [TREE] full Goal/Task tree (id, name, status, subtasks)

OUTPUT (strict JSON):
{
  "refinement_mutations": [
    {"op": "push_goal", "intent": "macOS hang debug", "source_unit_id": "u31",
     "rationale": "g1 mixes auth work with macOS hang investigation; latter deserves own goal"},
    {"op": "reparent", "task_id": "t6", "new_parent_id": "g7", "rationale": "g7 is the concrete ID assigned by the preceding push_goal"},
    ...
  ]
}

If tree is well-organized → output {"refinement_mutations": []}.
"""


def _format_tree_for_review(state_machine) -> str:
    """Compact tree dump showing all goals + tasks (recursive)."""
    lines = []
    def walk_task(t, depth):
        indent = "  " * (depth + 1)
        lines.append(f'{indent}t={t.id} [{t.status}] "{t.name[:80]}"')
        for s in t.subtasks: walk_task(s, depth+1)
    for g in state_machine.goals:
        lines.append(f'g={g.id} [{g.status}] "{g.intent[:100]}" '
                     f'({sum(1 for _ in _flatten_tasks(g))} tasks)')
        for t in g.tasks: walk_task(t, 0)
    return "\n".join(lines)


def _flatten_tasks(g) -> list:
    out = []
    def walk(t):
        out.append(t)
        for s in t.subtasks: walk(s)
    for t in g.tasks: walk(t)
    return out


def review_and_refine(state_machine, model: str | None = None,
                      verbose: int = 1, max_iterations: int = 4) -> int:
    """Run review passes over full tree until convergence (0 mutations) or
    max_iterations reached. Returns total mutations applied across all passes.
    Iterative passes catch wide goals where each pass peels off one strong theme."""
    total = 0
    for it in range(max_iterations):
        n = _review_once(state_machine, model=model, verbose=verbose, iteration=it+1)
        total += n
        if n == 0:
            break
    return total


def _review_once(state_machine, model: str | None = None,
                 verbose: int = 1, iteration: int = 1) -> int:
    """Single review pass. Returns mutations applied this pass."""
    if not state_machine.goals:
        if verbose >= 1: print("   [REVIEW] empty tree, skip")
        return 0

    tree_str = _format_tree_for_review(state_machine)
    next_g = state_machine._goal_counter + 1
    next_t = state_machine._task_counter + 1
    if verbose >= 1:
        n_tasks = sum(1 for g in state_machine.goals for _ in _flatten_tasks(g))
        print(f"   [REVIEW#{iteration}] {len(state_machine.goals)} goals / {n_tasks} tasks "
              f"({len(tree_str)} chars)...", end=" ", flush=True)
    bt = time.time()

    body = (
        f"## Next IDs\n\n"
        f"Next push_goal will assign g{next_g}. Next push_task will assign t{next_t}. "
        f"Increment by 1 for each push in your output. NEVER use placeholders like "
        f"'g_new' or 't_new' — always emit concrete numbered ids.\n\n"
        f"## Current Tree\n\n{tree_str}\n\n"
        f"## Task\n\n"
        f"Review the tree above. Identify boundary issues and emit refinement mutations.\n"
        f"Be conservative — only fix clear issues, leave reasonable groupings alone.\n"
    )

    content = copilot_api.chat_content(REVIEW_SYSTEM_PROMPT, body, model=model, stage="review")

    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise ValueError("Tree review returned invalid JSON")
        depth = 0
        data = None
        for i, c in enumerate(text[start:], start):
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start:i+1]); break
                    except json.JSONDecodeError as exc:
                        raise ValueError("Tree review returned invalid JSON") from exc
        if data is None:
            raise ValueError("Tree review returned incomplete JSON")

    if not isinstance(data, dict) or not isinstance(data.get("refinement_mutations"), list):
        raise ValueError("Tree review missing refinement_mutations")
    refinement = data["refinement_mutations"]
    if not refinement:
        if verbose >= 1: print(f"clean ({time.time()-bt:.1f}s)")
        return 0

    # Apply via state_machine (no new units)
    warnings = state_machine.apply_mutations(refinement, [])
    if warnings:
        raise ValueError("Invalid review mutations: " + "; ".join(warnings[:3]))
    if verbose >= 1:
        n_merge = sum(1 for m in refinement if m.get("op") == "merge_goals")
        n_reparent = sum(1 for m in refinement if m.get("op") == "reparent")
        n_abandon = sum(1 for m in refinement if m.get("op") == "mark_abandoned")
        print(f"applied {len(refinement)} ({n_merge}m/{n_reparent}r/{n_abandon}a), "
              f"{len(warnings)}w ({time.time()-bt:.1f}s)")
        if verbose >= 2:
            for m in refinement:
                rat = m.get("rationale", "")[:80]
                print(f"     {m.get('op'):<15} {rat}")
    return len(refinement)
