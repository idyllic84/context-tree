"""Tier 4 reflexion — smart-model self-audit over Goal/Task tree.

Inputs:
  - original session dialogue (compressed via Tier 1 outputs)
  - Goal/Task tree (post Tier 3)

Outputs (corrections to apply):
  - hallucinations: claims with no dialogue evidence → remove
  - missing: constraints/lessons explicit in dialogue but absent in tree → add
  - misassignments: items attached to wrong task → move

The Goal/Task tree is mutated in place. tree_to_entities should run after.

Cost: 1 smart-model call per session (full session in context).
"""

import json
import context_tree.common.llm as copilot_api
from context_tree.common.models import Session, Goal, Task


REFLEXION_PROMPT = """You are auditing an extracted Goal/Task tree against the original
dialogue between a human supervisor and an AI coding agent.

The tree contains, per task:
- constraints (rules / requirements)
- abandoned_alternatives (rejected approaches)
- lessons (learnings)
- outcome (final result if completed)
- terms (jargon)

Find three classes of issues, **each with a confidence score 0.0-1.0 and quoted evidence**:

1. **hallucinations** — items with NO clear evidence in the dialogue.
   Confidence = how certain you are the item is fabricated.
   Evidence = brief explanation of why it lacks support (or quote contradictory dialogue).

2. **missing** — explicit human constraints / lessons / abandoned alternatives in the
   dialogue absent from the tree.
   Confidence = how certain the dialogue truly establishes this fact.
   Evidence = direct quote from dialogue that supports it.

3. **misassignments** — items attached to the wrong task.
   Confidence = how certain about the relocation.
   Evidence = brief reason.

Be conservative: low confidence (<0.5) is fine — caller decides threshold.
The dialogue may be truncated. Missing evidence in a truncated excerpt is NOT
proof of hallucination; only remove claims contradicted by visible evidence.
Style differences are NOT issues.

Output strict JSON only:
{
  "hallucinations": [
    {"claim_id": "str", "confidence": 0.0-1.0, "evidence": "str"}
  ],
  "missing": [
    {"task_index": int, "type": "constraint|lesson|abandoned_alternative",
     "text": "str", "confidence": 0.0-1.0, "evidence": "str"}
  ],
  "misassignments": [
    {"claim_id": "str", "correct_task_index": int,
     "confidence": 0.0-1.0, "evidence": "str"}
  ]
}"""


# Thresholds for acting on reflexion suggestions
HALLUC_REMOVE_THRESHOLD = 0.7   # only remove if model is highly confident
MISSING_ADD_THRESHOLD = 0.5     # add as soft (lower bar; soft confidence anyway)
MISASSIGN_THRESHOLD = 0.7


def _serialize_dialogue(session: Session, max_chars: int = 8000) -> str:
    """Compact dialogue rendering for reflexion input."""
    lines = []
    char_count = 0
    for turn in session.turns:
        if turn.skip:
            continue
        lines.append(f"[Human T{turn.turn_id}] {(turn.human_normalized or turn.human_raw)[:500]}")
        split = turn.agent_split or {}
        agent = " | ".join(filter(None, [split.get("head"), split.get("tail")])) or turn.agent_raw[:500]
        if agent:
            lines.append(f"[Agent T{turn.turn_id}] {agent}")
        char_count = sum(len(l) for l in lines)
        if char_count > max_chars:
            lines.append("[... dialogue truncated ...]")
            break
    return "\n".join(lines)


def _flat_tasks(goal: Goal) -> list[Task]:
    out: list[Task] = []
    def walk(t: Task):
        out.append(t)
        for s in t.subtasks:
            walk(s)
    for t in goal.tasks:
        walk(t)
    return out


def _serialize_tree(session: Session) -> tuple[str, dict, list[Task]]:
    """Render task tree with claim_ids; return (text, claim_id → (task, field, index), all_tasks)."""
    lines = []
    claim_map: dict[str, tuple] = {}
    task_index = 0
    all_tasks: list[Task] = []
    for goal in session.goals:
        for t in _flat_tasks(goal):
            all_tasks.append(t)
    for ti, task in enumerate(all_tasks):
        lines.append(f"\n## Task {ti}: {task.name} [status={task.status}]")
        if task.outcome:
            cid = f"t{ti}.outcome"
            claim_map[cid] = (task, "outcome", None)
            lines.append(f"  [{cid}] outcome: {task.outcome}")
        for ci, c in enumerate(task.constraints):
            cid = f"t{ti}.c{ci}"
            claim_map[cid] = (task, "constraints", ci)
            lines.append(f"  [{cid}] constraint: {c}")
        for ai, alt in enumerate(task.abandoned_alternatives):
            cid = f"t{ti}.a{ai}"
            claim_map[cid] = (task, "abandoned_alternatives", ai)
            lines.append(f"  [{cid}] abandoned: {alt.get('approach')} (reason: {alt.get('reason')})")
        for li, l in enumerate(task.lessons):
            cid = f"t{ti}.l{li}"
            claim_map[cid] = (task, "lessons", li)
            lines.append(f"  [{cid}] lesson: {l}")
    return "\n".join(lines), claim_map, all_tasks


def _parse_json(text: str) -> dict | None:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
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


def review_session(session: Session, verbose: int = 1) -> dict:
    """Run reflexion. Returns the LLM correction dict (also applies to session)."""
    if not any(g.tasks for g in session.goals):
        if verbose: print("   reflexion: no tasks to audit")
        return {"hallucinations": [], "missing": [], "misassignments": []}

    dialogue_text = _serialize_dialogue(session)
    tree_text, claim_map, all_tasks = _serialize_tree(session)

    body = (f"## Dialogue (compressed)\n{dialogue_text}\n\n"
            f"## Extracted Task tree (with claim_ids)\n{tree_text}")

    if verbose:
        print(f"   reflexion: {len(claim_map)} claims, {len(all_tasks)} tasks, "
              f"{len(dialogue_text)} dialogue chars")

    content = copilot_api.chat_content(REFLEXION_PROMPT, body, stage="reflexion")

    corrections = _parse_json(content)
    if not isinstance(corrections, dict) or any(
            not isinstance(corrections.get(key), list)
            for key in ("hallucinations", "missing", "misassignments")):
        raise ValueError("Reflexion returned invalid correction arrays")
    apply_corrections(session, corrections, claim_map, all_tasks, verbose=verbose)
    return corrections


def apply_corrections(session: Session, corrections: dict,
                      claim_map: dict, all_tasks: list[Task], verbose: int = 1) -> None:
    """Apply reflexion corrections with per-item confidence thresholds.

    - hallucinations: remove only if confidence >= HALLUC_REMOVE_THRESHOLD
    - missing: add to soft_lessons / soft_constraints if confidence >= MISSING_ADD_THRESHOLD
              (soft buckets get lower confidence in tree_to_entities)
    - misassignments: move only if confidence >= MISASSIGN_THRESHOLD
    """
    halluc_items = corrections.get("hallucinations", [])
    missing = corrections.get("missing", [])
    misassign = corrections.get("misassignments", [])

    # Normalize: handle both old (str) and new (dict) shapes for backward compat
    def _norm_halluc(x):
        if isinstance(x, dict):
            return x.get("claim_id"), float(x.get("confidence", 0.5))
        return x, 0.5  # legacy: assume mid confidence

    # 1. Remove hallucinations (above threshold)
    halluc_grouped: dict[int, list[tuple[str, int | None]]] = {}
    halluc_skipped = 0
    for item in halluc_items:
        cid, conf = _norm_halluc(item)
        if cid not in claim_map:
            continue
        if conf < HALLUC_REMOVE_THRESHOLD:
            halluc_skipped += 1
            continue
        task, field, idx = claim_map[cid]
        halluc_grouped.setdefault(id(task), []).append((field, idx))

    task_by_id = {id(t): t for t in all_tasks}
    removed = 0
    for tid, items in halluc_grouped.items():
        task = task_by_id[tid]
        items.sort(key=lambda x: (0 if x[1] is None else 1, -(x[1] or 0)))
        for field, idx in items:
            try:
                if field == "outcome":
                    task.outcome = None
                    task.status = "in_progress"
                    removed += 1
                elif field in ("constraints", "lessons"):
                    getattr(task, field).pop(idx)
                    removed += 1
                elif field == "abandoned_alternatives":
                    task.abandoned_alternatives.pop(idx)
                    removed += 1
            except (IndexError, AttributeError):
                pass

    # 2. Add missing (above threshold, into soft_* buckets)
    added = 0
    skipped_missing = 0
    for m in missing:
        if not isinstance(m, dict):
            continue
        conf = float(m.get("confidence", 0.5))
        if conf < MISSING_ADD_THRESHOLD:
            skipped_missing += 1
            continue
        ti = m.get("task_index")
        if ti is None or ti < 0 or ti >= len(all_tasks):
            continue
        task = all_tasks[ti]
        kind = m.get("type")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if kind == "constraint" and text not in task.constraints \
           and text not in task.soft_constraints:
            task.soft_constraints.append(text)
            added += 1
        elif kind == "lesson" and text not in task.lessons \
             and text not in task.soft_lessons:
            task.soft_lessons.append(text)
            added += 1
        elif kind == "abandoned_alternative":
            task.abandoned_alternatives.append({
                "approach": text, "reason": "added by reflexion (low confidence)",
            })
            added += 1

    # 3. Move misassignments (above threshold)
    moved = 0
    for ma in misassign:
        if not isinstance(ma, dict):
            continue
        conf = float(ma.get("confidence", 0.5))
        if conf < MISASSIGN_THRESHOLD:
            continue
        cid = ma.get("claim_id")
        target_idx = ma.get("correct_task_index")
        if cid not in claim_map or target_idx is None or target_idx < 0 or target_idx >= len(all_tasks):
            continue
        src_task, field, idx = claim_map[cid]
        dst_task = all_tasks[target_idx]
        if id(src_task) == id(dst_task):
            continue
        try:
            if field == "outcome":
                dst_task.outcome = src_task.outcome
                src_task.outcome = None
                src_task.status = "in_progress"
            elif field in ("constraints", "lessons"):
                value = getattr(src_task, field)[idx]
                getattr(dst_task, field).append(value)
                getattr(src_task, field).pop(idx)
            elif field == "abandoned_alternatives":
                value = src_task.abandoned_alternatives[idx]
                dst_task.abandoned_alternatives.append(value)
                src_task.abandoned_alternatives.pop(idx)
            moved += 1
        except (IndexError, AttributeError):
            pass

    if verbose:
        print(f"   reflexion applied: removed {removed} (skipped {halluc_skipped} low-conf), "
              f"added {added} soft (skipped {skipped_missing} low-conf), moved {moved}")
