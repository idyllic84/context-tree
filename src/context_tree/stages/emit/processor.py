"""V2-B Layer 2 → Layer 3 — emit purpose-framed agent_content + user-derived entities.

Differs from V2-A in three ways:
  1. Each agent unit linked to a Task → an `agent_content` entity with title/content
     from purpose_title / purpose_body (set by framing_pass). subtype encodes
     acceptance × act (decision_taken / rationale_accepted / unclaimed_proposal / ...)
  2. Task.lessons (V2-A's separate lesson entity) is no longer emitted as type=lesson
     — affirmed explains become agent_content/rationale_accepted instead
  3. Task.outcome is no longer a string-based context entity. Replaced by the
     agent_content/decision_taken entity for the corresponding propose unit.

Per-turn file/directory edges (replaces V2-A's per-task path aggregation):
  - Each turn (= one agent_content) emits its own file edges anchored on the
    agent_content title (falls back to task name if no agent_content emitted).
  - Same-directory files folded into one `directory` entity edge when the count
    reaches DIR_FOLD_THRESHOLD. Edge cap (PER_TURN_EDGE_CAP) prevents explore
    turns from flooding the graph; overflow noted in the last edge's explanation.
  - File operation aggregation: modifies > creates > references (strongest wins
    per file within the turn). mentioned_in is separate, deduped against touched.

Retained from V2-A:
  - Goal.intent → context entity
  - Goal/Task constraints → constraint entities
  - Task.terms → term entities
  - File entities (now also directory entities)
  - corrected_to edges (re-anchored to agent_content unit_ids when both ends present)
  - junk-title filter (file + directory bypass)

Subtype confidence map (per spec §6.3):
  decision_taken      0.95
  decision_soft       0.65
  decision_rejected   0.85
  unclaimed_proposal  0.40
  rationale_accepted  0.85
  rationale_soft      0.55
  clarify_open        0.40
  report_observed     0.70
"""
import os
import re
from context_tree.common.models import Session, Goal, Task, AtomicUnit, DialogueTurn
from context_tree.stages.ingest.processor import get_device_id


# ─── Confidence per subtype (B-revised, size-aware unclaimed) ───
SUBTYPE_CONFIDENCE = {
    "decision_taken": 0.95,
    "decision_soft": 0.65,
    "decision_rejected": 0.85,
    "unclaimed_proposal_large": 0.55,   # large-ish agent text user didn't object to
    "unclaimed_proposal_small": 0.40,   # small unclaimed — kept for completeness
    "rationale_accepted": 0.85,
    "rationale_soft": 0.55,
    "unclaimed_explain_large": 0.50,
    "unclaimed_explain_small": 0.35,
    "clarify_open": 0.30,                # agent asked, user never answered — weakest
    "report_observed": 0.70,
}

# Threshold for "large" agent text — user reading-without-objection counts as soft accept.
LARGE_AGENT_CHARS = 400

# Per-turn file edge aggregation (replaces per-task aggregation):
#   - Each turn (= one agent_content) emits its own file/dir edges.
#   - ≥ DIR_FOLD_THRESHOLD files in same directory → fold into one directory
#     entity edge per relation (with file list in explanation).
#   - Cap PER_TURN_EDGE_CAP edges per turn (prevents explore-heavy turns from
#     flooding the graph). Excess truncated; count noted on last edge's explanation.
#   - Touched relations priority (strongest wins per file): modifies > creates > references.
#   - mentioned_in is separate; deduped against touched paths.
DIR_FOLD_THRESHOLD = 3
PER_TURN_EDGE_CAP = 15
_REL_PRIORITY = {"references": 0, "creates": 1, "modifies": 2}

# Other entity confidences (carried over from V2-A)
CONF_GOAL_INTENT = 0.80
CONF_GOAL_CONSTRAINT = 0.90
CONF_TASK_CONSTRAINT = 0.90
CONF_SOFT_CONSTRAINT = 0.55
CONF_TERM = 0.85
CONF_FILE = 0.95


# ─── Junk-title filter (carried over from V2-A bug fix) ───
_JUNK_TITLE_RE = re.compile(r'^[\W\d_]*$')

def _is_junk_title(title: str) -> bool:
    if not title: return True
    s = title.strip()
    if len(s) < 4: return True
    if _JUNK_TITLE_RE.match(s): return True
    return False


# ─── File entity helpers (same as V2-A) ───

def _file_id(path: str) -> str:
    return f"{get_device_id()[:8]}:{path}"


def _dir_id(path: str) -> str:
    return f"{get_device_id()[:8]}:dir:{path}"


def _file_entity(path: str, project: str | None, session_id: str, date: str,
                 source_unit_id: str | None) -> dict:
    in_project_path = project if project and (path == project or path.startswith(project + os.sep)) else None
    return {
        "id": _file_id(path),
        "type": "file",
        "title": path,
        "content": None,
        "project": project or "",
        "session": session_id,
        "date": date,
        "source_unit_id": source_unit_id,
        "confidence": CONF_FILE,
        "metadata_extra": {
            "device_id": get_device_id(),
            "extension": os.path.splitext(path)[1],
            "in_project": in_project_path,
        },
    }


def _dir_entity(path: str, project: str | None, session_id: str, date: str,
                 source_unit_id: str | None) -> dict:
    in_project_path = project if project and (path == project or path.startswith(project + os.sep)) else None
    return {
        "id": _dir_id(path),
        "type": "directory",
        "title": path,
        "content": None,
        "project": project or "",
        "session": session_id,
        "date": date,
        "source_unit_id": source_unit_id,
        "confidence": CONF_FILE,
        "metadata_extra": {
            "device_id": get_device_id(),
            "in_project": in_project_path,
        },
    }


def _turn_touched_paths(turn: DialogueTurn) -> dict[str, str]:
    """Per turn, return {path: strongest relation} from tool_use signals.
    Priority: modifies > creates > references."""
    out: dict[str, str] = {}
    def upd(p: str, r: str):
        cur = out.get(p)
        if cur is None or _REL_PRIORITY[r] > _REL_PRIORITY[cur]:
            out[p] = r
    for p in turn.tool_inputs: upd(p, "references")
    for p in turn.tool_outputs: upd(p, "creates")
    for p in turn.tool_modifies: upd(p, "modifies")
    return out


def _fold_paths_by_dir(paths: dict[str, str]) -> list[dict]:
    """Group paths by dirname. ≥ DIR_FOLD_THRESHOLD in one dir → fold into
    per-relation directory entries. Else per-file entries.

    Returns list of {kind: file|directory, path: str, relation: str, files?: list[str]}.
    """
    by_dir: dict[str, list[tuple[str, str]]] = {}
    for p, r in paths.items():
        d = os.path.dirname(p) or "/"
        by_dir.setdefault(d, []).append((p, r))
    out: list[dict] = []
    for d, items in by_dir.items():
        if len(items) >= DIR_FOLD_THRESHOLD:
            by_rel: dict[str, list[str]] = {}
            for p, r in items:
                by_rel.setdefault(r, []).append(p)
            for r, fs in by_rel.items():
                out.append({"kind": "directory", "path": d, "relation": r, "files": fs})
        else:
            for p, r in items:
                out.append({"kind": "file", "path": p, "relation": r})
    return out


def _flat_tasks(goal: Goal) -> list[Task]:
    out: list[Task] = []
    def walk(t: Task):
        out.append(t)
        for s in t.subtasks: walk(s)
    for t in goal.tasks: walk(t)
    return out


def _derive_subtype(unit: AtomicUnit, is_large: bool) -> str | None:
    """Derive subtype from (act, acceptance, size). Returns None only for clarify
    that was answered (covered by the user answer→constraint path)."""
    a = (unit.acceptance or "unclaimed").lower()
    if unit.act == "propose":
        if a == "hard":     return "decision_taken"
        if a == "soft":     return "decision_soft"
        if a == "rejected": return "decision_rejected"
        return "unclaimed_proposal_large" if is_large else "unclaimed_proposal_small"
    if unit.act == "explain":
        if a == "hard":     return "rationale_accepted"
        if a == "soft":     return "rationale_soft"
        return "unclaimed_explain_large" if is_large else "unclaimed_explain_small"
    if unit.act == "clarify":
        # answered clarify → user side already produced answer→constraint, skip
        return "clarify_open" if a == "unclaimed" else None
    if unit.act == "report":
        # Only emit report when user explicitly engaged with it (affirm/soft).
        # Unclaimed reports are typically tool-call results ("已 commit" / "tests pass")
        # — high volume, low signal. Drop.
        if a in ("hard", "soft"):
            return "report_observed"
        return None
    return None


def _agent_content_entity(unit: AtomicUnit, subtype: str, project: str,
                           session_id: str, date: str, task_id: str | None,
                           turn_id: int | None = None) -> dict:
    title = unit.purpose_title or unit.text[:80]
    body = unit.purpose_body or unit.text
    return {
        "id": f"{session_id}:agent_content:{unit.id}",
        "type": "agent_content",
        "title": title[:120],
        "content": body,
        "project": project,
        "session": session_id,
        "date": date,
        "source_unit_id": unit.id,
        "confidence": SUBTYPE_CONFIDENCE.get(subtype, 0.5),
        "metadata_extra": {
            "subtype": subtype,
            "framing_failed": bool(unit.framing_failed),
            "source_task_id": task_id or "",
            # Index back to agent original via session+turn+unit. RAG can fetch
            # the full turn JSON from session cache if it ever needs more than
            # the purpose_body already stored in `content`.
            "agent_unit_id": unit.id,
            "turn_id": turn_id,
        },
    }


def convert_session(session: Session, date: str = "") -> tuple[list[dict], list[dict]]:
    """Convert a Session to (entities, edges).

    edges follow same conventions as V2-A:
      - {source_title, target_title, relation, ...} for decision↔decision (corrected_to)
      - {source_title|source_id, target_id, relation, ...} for file role edges

    Filtering: junk-title entities dropped at the end; orphan edges (whose source/target
    title was filtered) also dropped.
    """
    entities: list[dict] = []
    edges: list[dict] = []
    project = session.project_path

    # unit lookup + unit→turn map
    unit_by_id: dict[str, AtomicUnit] = {}
    unit_to_turn: dict[str, DialogueTurn] = {}
    for t in session.turns:
        for u in t.units:
            unit_by_id[u.id] = u
            unit_to_turn[u.id] = t

    seen_files: set[str] = set()
    def _emit_file(path: str, source_unit_id: str | None) -> str:
        if path not in seen_files:
            entities.append(_file_entity(path, project, session.session_id, date, source_unit_id))
            seen_files.add(path)
        return _file_id(path)

    seen_dirs: set[str] = set()
    def _emit_dir(path: str, source_unit_id: str | None) -> str:
        if path not in seen_dirs:
            entities.append(_dir_entity(path, project, session.session_id, date, source_unit_id))
            seen_dirs.add(path)
        return _dir_id(path)

    # Track agent_content emit titles by unit_id, for corrected_to edge resolution
    unit_to_emitted_title: dict[str, str] = {}

    for goal in session.goals:
        # Goal intent → context entity
        if goal.tasks and goal.intent:
            entities.append({
                "type": "context",
                "title": goal.intent[:120],
                "content": _summarize_goal(goal),
                "project": project,
                "session": session.session_id,
                "date": date,
                "source_unit_id": goal.source_unit_id,
                "confidence": CONF_GOAL_INTENT,
            })

        # Goal-level constraints
        for c in goal.constraints:
            entities.append({
                "type": "constraint",
                "title": c[:120],
                "content": f"Goal: {goal.intent}",
                "project": project,
                "session": session.session_id,
                "date": date,
                "source_unit_id": goal.source_unit_id,
                "confidence": CONF_GOAL_CONSTRAINT,
            })

        for task in _flat_tasks(goal):
            # ── User-derived constraints (hard + soft) ──
            for c in task.constraints:
                entities.append({
                    "type": "constraint",
                    "title": c[:120],
                    "content": f"Constraint for: {task.name}",
                    "project": project,
                    "session": session.session_id,
                    "date": date,
                    "source_unit_id": task.source_unit_id,
                    "confidence": CONF_TASK_CONSTRAINT,
                })
            for c in task.soft_constraints:
                entities.append({
                    "type": "constraint",
                    "title": c[:120],
                    "content": f"Constraint for: {task.name} (reflexion)",
                    "project": project,
                    "session": session.session_id,
                    "date": date,
                    "source_unit_id": f"reflexion:{task.source_unit_id or task.id}",
                    "confidence": CONF_SOFT_CONSTRAINT,
                })

            # ── Terms ──
            for term in task.terms:
                entities.append({
                    "type": "term",
                    "title": term[:120],
                    "content": None,
                    "project": project,
                    "session": session.session_id,
                    "date": date,
                    "source_unit_id": task.source_unit_id,
                    "confidence": CONF_TERM,
                })

            # ── B core: agent_content entities for each agent unit linked to this task ──
            for uid in task.linked_unit_ids:
                u = unit_by_id.get(uid)
                if u is None or u.speaker != "agent":
                    continue
                turn = unit_to_turn.get(uid)
                is_large = bool(turn and (
                    len(turn.agent_raw) > LARGE_AGENT_CHARS
                    or (turn.agent_segments and (turn.agent_segments[0].get("truncated_chars") or 0) > 0)
                ))
                subtype = _derive_subtype(u, is_large)
                if subtype is None:
                    continue
                ent = _agent_content_entity(u, subtype, project, session.session_id, date, task.id,
                                              turn_id=(turn.turn_id if turn else None))
                entities.append(ent)
                unit_to_emitted_title[u.id] = ent["title"]

                # For decision_rejected, also emit a paired "Avoid: <title>" constraint
                if subtype == "decision_rejected":
                    avoid_title = f"Avoid: {ent['title']}"[:120]
                    entities.append({
                        "type": "constraint",
                        "title": avoid_title,
                        "content": ent["content"],
                        "project": project,
                        "session": session.session_id,
                        "date": date,
                        "source_unit_id": u.id,
                        "confidence": 0.90,
                    })

            # ── corrected_to edges: from rejected propose's avoid-title to its correction ──
            for ab in task.abandoned_unit_ids:
                rejected_uid = ab.get("unit_id")
                correction_uid = ab.get("correction_unit_id")
                if not rejected_uid: continue
                rej_title = unit_to_emitted_title.get(rejected_uid)
                if not rej_title: continue
                avoid_title = f"Avoid: {rej_title}"[:120]
                # Correction may or may not have an emitted entity. Try the agent_content
                # of any subsequent decision_taken on same task as edge target.
                # Otherwise, fall back to using the correction text from the human reject unit.
                target_title = None
                # Look for subsequent decision_taken in same task
                for uid in task.linked_unit_ids:
                    u2 = unit_by_id.get(uid)
                    if u2 is None or u2.speaker != "agent": continue
                    if u2.acceptance == "hard" and u2.act == "propose":
                        t2 = unit_to_emitted_title.get(u2.id)
                        if t2: target_title = t2; break
                if not target_title and correction_uid:
                    cu = unit_by_id.get(correction_uid)
                    if cu and cu.correction:
                        target_title = cu.correction[:120]
                if target_title:
                    edges.append({
                        "source_title": avoid_title,
                        "target_title": target_title,
                        "relation": "corrected_to",
                        "explanation": f"Within task '{task.name}', user rejected and corrected.",
                    })

            # ── File / directory edges (per-turn anchored on agent_content of that turn,
            #    falls back to task name when turn has no emitted agent_content). ──
            fallback_anchor = task.name[:120]
            if task.outcome_unit_id and (t_outcome := unit_to_emitted_title.get(task.outcome_unit_id)):
                fallback_anchor = t_outcome

            # Collect distinct turn_ids linked to this task (preserve dialogue order)
            seen_turn_ids: set[int] = set()
            ordered_turns: list[DialogueTurn] = []
            for uid in task.linked_unit_ids:
                tn = unit_to_turn.get(uid)
                if tn is None or tn.turn_id in seen_turn_ids:
                    continue
                seen_turn_ids.add(tn.turn_id)
                ordered_turns.append(tn)
            ordered_turns.sort(key=lambda x: x.turn_id)

            for turn in ordered_turns:
                # Anchor: prefer this turn's emitted agent_content title; else fallback.
                anchor_title = None
                anchor_id = None
                for u in turn.units:
                    if u.speaker == "agent":
                        if t := unit_to_emitted_title.get(u.id):
                            anchor_title = t
                            anchor_id = f"{session.session_id}:agent_content:{u.id}"
                            break
                anchor_title = anchor_title or fallback_anchor

                touched = _turn_touched_paths(turn)
                mentioned_set = (set(turn.mentioned_paths) | set(turn.resolved_paths)) - set(touched.keys())

                folded_touched = _fold_paths_by_dir(touched)
                folded_mentioned = _fold_paths_by_dir({p: "mentioned_in" for p in mentioned_set})

                edges_to_emit = folded_touched + folded_mentioned
                truncated = 0
                if len(edges_to_emit) > PER_TURN_EDGE_CAP:
                    truncated = len(edges_to_emit) - PER_TURN_EDGE_CAP
                    edges_to_emit = edges_to_emit[:PER_TURN_EDGE_CAP]

                for entry in edges_to_emit:
                    if entry["kind"] == "file":
                        tid = _emit_file(entry["path"], task.source_unit_id)
                        explanation = f"{entry['relation']} in turn {turn.turn_id} of task '{task.name}'"
                    else:  # directory
                        tid = _emit_dir(entry["path"], task.source_unit_id)
                        explanation = (f"{entry['relation']} {len(entry['files'])} files in dir "
                                       f"(turn {turn.turn_id} of task '{task.name}')")
                    edges.append({
                        "source_title": anchor_title,
                        "source_id": anchor_id,
                        "target_id": tid,
                        "relation": entry["relation"],
                        "explanation": explanation,
                    })
                if truncated > 0 and edges:
                    edges[-1]["explanation"] += f" [+{truncated} more paths omitted]"

    # ── junk-title filter ──
    kept_titles: set[str] = set()
    filtered_entities: list[dict] = []
    for e in entities:
        if e.get("type") in ("file", "directory"):
            filtered_entities.append(e)
            kept_titles.add(e["title"])
        elif _is_junk_title(e.get("title", "")):
            continue
        else:
            filtered_entities.append(e)
            kept_titles.add(e["title"])

    filtered_edges = [
        ed for ed in edges
        if ed.get("source_title") in kept_titles
        and (ed.get("target_id") or ed.get("target_title") in kept_titles)
    ]

    return filtered_entities, filtered_edges


def _summarize_goal(goal: Goal) -> str:
    parts = []
    completed = sum(1 for t in _flat_tasks(goal) if t.status == "completed")
    abandoned = sum(1 for t in _flat_tasks(goal) if t.status == "abandoned")
    parts.append(f"Status: {goal.status}; {completed} tasks completed, {abandoned} abandoned")
    outcomes = [t.outcome for t in _flat_tasks(goal) if t.outcome][:3]
    if outcomes:
        parts.append("Outcomes: " + " | ".join(o[:80] for o in outcomes))
    return " | ".join(parts)
