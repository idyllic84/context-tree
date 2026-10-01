"""C state machine — applies LLM-proposed tree mutations to Goal/Task tree.

Differs from V2-B v2 state_machine:
- `build_session(turns)` autonomous tree-build → REMOVED
- New: `apply_mutations(state, mutations, units)` driven by LLM mutation ops
- New: `compose_view(char_budget)` for hot/cold tree access
- New: `expand(branch_ids)` for round-2 expansion
- Recency tracking (last_accessed_at) on all branches

Mutation ops (from LLM):
  push_goal       {intent, source_unit_id} → returns g<N>
  push_task       {parent_id, name, source_unit_id} → returns t<N>
  push_subtask    {parent_id, name, source_unit_id}
  set_active      {task_id}
  affirm_propose  {task_id, unit_id, outcome_summary}
  reject_propose  {task_id, unit_id, correction_text?}
  affirm_explain  {task_id, unit_id}
  soft_complete   {task_id, propose_unit_id?, explain_unit_id?}
  add_constraint  {container_id, text, source_unit_id}
  add_term        {task_id, text}
  mark_abandoned  {task_id, reason}
  touch           {branch_id}
"""
import time
import copy
from context_tree.common.models import Session, Goal, Task, AtomicUnit, DialogueTurn


class TreeStateMachine:
    """Stateful manager for one Session's task tree, driven by LLM mutations."""

    def __init__(self, initial_session: Session | None = None):
        self.goals: list[Goal] = copy.deepcopy(initial_session.goals) if initial_session else []
        self.active_goal: Goal | None = None
        self.active_task: Task | None = None
        self._goal_counter = max((int(g.id[1:]) for g in self.goals), default=0)
        self._task_counter = max((int(t.id[1:]) for g in self.goals for t in _flatten_tasks(g)), default=0)
        # Maps for cross-batch reference resolution
        self._goal_by_id: dict[str, Goal] = {g.id: g for g in self.goals}
        self._task_by_id: dict[str, Task] = {}
        for g in self.goals:
            for t in _flatten_tasks(g):
                self._task_by_id[t.id] = t
        # Source-unit-id maps (for cross-session chain continuation)
        self._source_to_goal: dict[str, Goal] = {g.source_unit_id: g for g in self.goals if g.source_unit_id}
        self._source_to_task: dict[str, Task] = {}
        for g in self.goals:
            for t in _flatten_tasks(g):
                if t.source_unit_id:
                    self._source_to_task[t.source_unit_id] = t
        # Unit lookup (populated as turns processed)
        self._unit_by_id: dict[str, AtomicUnit] = {
            u.id: u for turn in (initial_session.turns if initial_session else []) for u in turn.units
        }
        # Mutation log (for debug + reflexion audit)
        self.mutation_log: list[dict] = []
        # Warnings collected during mutation application
        self.warnings: list[str] = []

        # Restore active pointer from initial_session (chain continuation)
        if self.goals:
            for g in sorted(self.goals, key=lambda g: g.last_accessed_at, reverse=True):
                if g.status in ("in_progress", "pending"):
                    self.active_goal = g
                    for t in sorted(_flatten_tasks(g), key=lambda t: t.last_accessed_at, reverse=True):
                        if t.status in ("in_progress", "pending"):
                            self.active_task = t
                            break
                    break

    # ─── mutation dispatch ───

    def apply_mutations(self, mutations: list[dict],
                         current_batch_units: list[AtomicUnit]) -> list[str]:
        """Apply LLM-proposed mutations atomically. Returns warnings.

        Mutations are applied IN ORDER; each may reference ids defined by
        earlier mutations in same batch. Invalid mutations logged, not crashed.
        """
        # Index batch units for cross-reference
        for u in current_batch_units:
            self._unit_by_id[u.id] = u

        local_warnings = []
        for mut in mutations:
            try:
                self._apply_one(mut)
                self.mutation_log.append({"applied": True, **mut})
            except StateError as e:
                op = mut.get('op', '?') if isinstance(mut, dict) else '?'
                rest = {k: v for k, v in mut.items() if k != "op"} if isinstance(mut, dict) else {}
                rest_str = ", ".join(f"{k}={str(v)[:40]}" for k, v in rest.items())
                msg = f"{op}({rest_str}) → {e}"
                local_warnings.append(msg)
                self.mutation_log.append({"applied": False, "error": str(e),
                                          **(mut if isinstance(mut, dict) else {})})

        # End-of-batch housekeeping
        self._propagate_status()
        self.warnings.extend(local_warnings)
        return local_warnings

    def _apply_one(self, mut: dict):
        if not isinstance(mut, dict):
            raise StateError("mutation must be an object")
        op = mut.get("op")
        for field in ("source_unit_id", "unit_id", "propose_unit_id", "explain_unit_id"):
            if mut.get(field) and mut[field] not in self._unit_by_id:
                raise StateError(f"unknown {field} {mut[field]}")
        if op in ("affirm_propose", "reject_propose", "affirm_explain"):
            unit = self._unit_by_id.get(mut.get("unit_id"))
            expected_act = "reject" if op == "reject_propose" else "affirm"
            if unit and unit.speaker == "human" and unit.act == expected_act:
                target = self._unit_by_id.get(unit.target)
                if target and target.speaker == "agent":
                    mut = {**mut, "unit_id": target.id}
                    unit = target
            if unit is None or unit.speaker != "agent":
                raise StateError("feedback requires an existing agent unit or its explicit feedback reference")
        now = time.time()
        if op == "push_goal":
            self._goal_counter += 1
            gid = f"g{self._goal_counter}"
            g = Goal(
                id=gid, intent=mut.get("intent", "")[:200],
                status="in_progress",
                source_unit_id=mut.get("source_unit_id"),
                linked_unit_ids=[mut.get("source_unit_id")] if mut.get("source_unit_id") else [],
                last_accessed_at=now,
            )
            self.goals.append(g)
            self._goal_by_id[gid] = g
            if g.source_unit_id:
                self._source_to_goal[g.source_unit_id] = g
            self.active_goal = g
            self.active_task = None
        elif op == "push_task":
            parent_id = mut.get("parent_id")
            if parent_id not in self._goal_by_id and parent_id not in self._task_by_id:
                raise StateError(f"push_task unknown parent {parent_id}")
            self._task_counter += 1
            tid = f"t{self._task_counter}"
            t = Task(
                id=tid, name=mut.get("name", "")[:200],
                parent_id=parent_id,
                parent_type="goal" if parent_id.startswith("g") else "task",
                status="in_progress",
                source_unit_id=mut.get("source_unit_id"),
                linked_unit_ids=[mut.get("source_unit_id")] if mut.get("source_unit_id") else [],
                last_accessed_at=now,
            )
            if parent_id.startswith("g"):
                g = self._goal_by_id.get(parent_id)
                if not g: raise StateError(f"unknown goal {parent_id}")
                g.tasks.append(t)
                g.last_accessed_at = now
            else:
                pt = self._task_by_id.get(parent_id)
                if not pt: raise StateError(f"unknown task {parent_id}")
                pt.subtasks.append(t)
                pt.last_accessed_at = now
            self._task_by_id[tid] = t
            if t.source_unit_id:
                self._source_to_task[t.source_unit_id] = t
                self._unit_by_id[t.source_unit_id].for_task_id = t.id
            self.active_task = t
        elif op == "push_subtask":
            # Same as push_task but parent must be task
            parent_id = mut.get("parent_id")
            if not parent_id or not parent_id.startswith("t"):
                raise StateError(f"push_subtask requires task parent_id, got {parent_id}")
            mut2 = {**mut, "op": "push_task"}
            self._apply_one(mut2)
        elif op == "set_active":
            tid = mut.get("task_id")
            t = self._task_by_id.get(tid)
            if not t: raise StateError(f"unknown task {tid}")
            self.active_task = t
            t.last_accessed_at = now
            # Also bump owning goal
            for g in self.goals:
                if t in _flatten_tasks(g):
                    self.active_goal = g
                    g.last_accessed_at = now
                    break
        elif op == "affirm_propose":
            t = self._task_by_id.get(mut.get("task_id"))
            if not t: raise StateError(f"unknown task {mut.get('task_id')}")
            uid = mut.get("unit_id")
            u = self._unit_by_id.get(uid)
            if u:
                u.acceptance = "hard"
                u.for_task_id = t.id  # link unit to task
            t.outcome = mut.get("outcome_summary", "")[:200]
            t.outcome_unit_id = uid
            t.status = "completed"
            if uid and uid not in t.linked_unit_ids:
                t.linked_unit_ids.append(uid)
            t.last_accessed_at = now
        elif op == "reject_propose":
            t = self._task_by_id.get(mut.get("task_id"))
            if not t: raise StateError(f"unknown task {mut.get('task_id')}")
            uid = mut.get("unit_id")
            u = self._unit_by_id.get(uid)
            if u:
                u.acceptance = "rejected"
                u.for_task_id = t.id
            t.abandoned_unit_ids.append({
                "unit_id": uid,
                "correction_unit_id": None,
            })
            t.abandoned_alternatives.append({
                "approach": (u.text if u else "")[:120],
                "reason": mut.get("correction_text", "user rejected"),
                "corrected_to": mut.get("correction_text"),
            })
            corr = mut.get("correction_text")
            if corr and corr not in t.constraints:
                t.constraints.append(corr[:200])
            if uid and uid not in t.linked_unit_ids:
                t.linked_unit_ids.append(uid)
            t.last_accessed_at = now
        elif op == "affirm_explain":
            t = self._task_by_id.get(mut.get("task_id"))
            if not t: raise StateError(f"unknown task {mut.get('task_id')}")
            uid = mut.get("unit_id")
            u = self._unit_by_id.get(uid)
            if u:
                u.acceptance = "hard"
                u.for_task_id = t.id
            if uid not in t.lesson_unit_ids:
                t.lesson_unit_ids.append(uid)
            if u and u.text and u.text not in t.lessons:
                t.lessons.append(u.text[:200])
            if uid and uid not in t.linked_unit_ids:
                t.linked_unit_ids.append(uid)
            t.last_accessed_at = now
        elif op == "soft_complete":
            t = self._task_by_id.get(mut.get("task_id"))
            if not t: raise StateError(f"unknown task {mut.get('task_id')}")
            puid = mut.get("propose_unit_id")
            euid = mut.get("explain_unit_id")
            if puid:
                pu = self._unit_by_id.get(puid)
                if pu:
                    pu.acceptance = "soft"
                    pu.for_task_id = t.id
                if t.outcome is None:
                    t.outcome = (pu.text if pu else "")[:200]
                    t.outcome_unit_id = puid
                    t.outcome_soft = True
                    t.status = "completed"
                if puid not in t.linked_unit_ids:
                    t.linked_unit_ids.append(puid)
            if euid:
                eu = self._unit_by_id.get(euid)
                if eu:
                    eu.acceptance = "soft"
                    eu.for_task_id = t.id
                if euid not in t.lesson_unit_ids:
                    t.lesson_unit_ids.append(euid)
                if eu and eu.text and eu.text not in t.soft_lessons:
                    t.soft_lessons.append(eu.text[:200])
                if euid not in t.linked_unit_ids:
                    t.linked_unit_ids.append(euid)
            t.last_accessed_at = now
        elif op == "add_constraint":
            cid = mut.get("container_id")
            text = mut.get("text", "")[:300]
            if not text: raise StateError("add_constraint empty text")
            container = self._goal_by_id.get(cid) or self._task_by_id.get(cid)
            if not container: raise StateError(f"unknown container {cid}")
            if text not in container.constraints:
                container.constraints.append(text)
            container.last_accessed_at = now
        elif op == "add_term":
            t = self._task_by_id.get(mut.get("task_id"))
            if not t: raise StateError(f"unknown task {mut.get('task_id')}")
            text = mut.get("text", "")[:120]
            if text and text not in t.terms:
                t.terms.append(text)
            t.last_accessed_at = now
        elif op == "mark_abandoned":
            t = self._task_by_id.get(mut.get("task_id"))
            if not t: raise StateError(f"unknown task {mut.get('task_id')}")
            t.status = "abandoned"
            t.last_accessed_at = now
        elif op == "reparent":
            tid = mut.get("task_id")
            new_pid = mut.get("new_parent_id")
            t = self._task_by_id.get(tid)
            if not t: raise StateError(f"unknown task {tid}")
            new_p = self._goal_by_id.get(new_pid) or self._task_by_id.get(new_pid)
            if not new_p: raise StateError(f"unknown new parent {new_pid}")
            cursor = new_p
            while isinstance(cursor, Task):
                if cursor.id == tid:
                    raise StateError("reparent would create a cycle")
                cursor = self._task_by_id.get(cursor.parent_id)
            # Remove from old parent's children list
            if t.parent_type == "goal":
                old = self._goal_by_id.get(t.parent_id)
                if old and t in old.tasks: old.tasks.remove(t)
            else:
                old = self._task_by_id.get(t.parent_id)
                if old and t in old.subtasks: old.subtasks.remove(t)
            # Add under new parent
            if new_pid.startswith("g"):
                new_p.tasks.append(t); t.parent_type = "goal"; t.parent_id = new_pid
            else:
                new_p.subtasks.append(t); t.parent_type = "task"; t.parent_id = new_pid
            t.last_accessed_at = now
            new_p.last_accessed_at = now
        elif op == "merge_goals":
            into_id = mut.get("into")
            from_ids = mut.get("from", [])
            into_g = self._goal_by_id.get(into_id)
            if not into_g: raise StateError(f"merge_goals: unknown into {into_id}")
            for fid in from_ids:
                if fid == into_id: continue
                src = self._goal_by_id.get(fid)
                if not src:
                    self.warnings.append(f"merge_goals: unknown source {fid}, skipping")
                    continue
                # Move tasks
                for t in list(src.tasks):
                    t.parent_id = into_id
                    t.parent_type = "goal"
                    into_g.tasks.append(t)
                # Move constraints
                for c in src.constraints:
                    if c not in into_g.constraints:
                        into_g.constraints.append(c)
                # Move linked unit ids
                for uid in src.linked_unit_ids:
                    if uid not in into_g.linked_unit_ids:
                        into_g.linked_unit_ids.append(uid)
                # Remove source goal
                self.goals.remove(src)
                self._goal_by_id.pop(fid, None)
                if self.active_goal is src:
                    self.active_goal = into_g
            into_g.last_accessed_at = now
        elif op == "link_unit":
            t = self._task_by_id.get(mut.get("task_id"))
            u = self._unit_by_id.get(mut.get("unit_id"))
            if t is None or u is None:
                raise StateError("link_unit requires existing task and unit")
            if u.for_task_id and u.for_task_id != t.id:
                previous = self._task_by_id.get(u.for_task_id)
                if previous and u.id in previous.linked_unit_ids:
                    previous.linked_unit_ids.remove(u.id)
            u.for_task_id = t.id
            if u.id not in t.linked_unit_ids:
                t.linked_unit_ids.append(u.id)
            t.last_accessed_at = now
        elif op == "touch":
            bid = mut.get("branch_id")
            target = self._goal_by_id.get(bid) or self._task_by_id.get(bid)
            if not target: raise StateError(f"unknown branch {bid}")
            target.last_accessed_at = now
        else:
            raise StateError(f"unknown op: {op}")

    # ─── status propagation ───

    def _propagate_status(self):
        for g in self.goals:
            statuses = {t.status for t in _flatten_tasks(g)}
            if not statuses:
                continue
            if statuses <= {"completed"}:
                g.status = "achieved"
            elif "in_progress" in statuses or "pending" in statuses or "blocked" in statuses:
                g.status = "in_progress"
            elif statuses <= {"completed", "abandoned"}:
                g.status = "achieved" if "completed" in statuses else "abandoned"

    # ─── tree views ───

    def compose_view(self, char_budget: int = 30000) -> dict:
        """Hot subtree (full tree if fits in budget) + cold metadata.

        For typical sessions (≤300 tasks ≈ 25K chars), full tree fits.
        Hot/cold split only triggers for super-large sessions.
        """
        sorted_goals = sorted(self.goals, key=lambda g: g.last_accessed_at, reverse=True)
        hot = []
        cold = []
        used = 0

        def _goal_view(g: Goal) -> dict:
            return {
                "id": g.id,
                "intent": g.intent[:120],
                "status": g.status,
                "active_task_id": self.active_task.id if (self.active_task and self.active_task in _flatten_tasks(g)) else None,
                "constraints": [c[:80] for c in g.constraints[:3]],
                "tasks": [_task_view(t) for t in g.tasks],  # full task list
            }

        def _task_view(t: Task) -> dict:
            return {
                "id": t.id,
                "name": t.name[:120],
                "status": t.status,
                "outcome_unit_id": t.outcome_unit_id,
                "abandoned": [{"unit_id": a.get("unit_id"), "approach": a.get("approach","")[:80]}
                               for a in t.abandoned_alternatives[:3]],
                "constraints": [c[:80] for c in t.constraints[:2]],
                "subtasks": [_task_view(s) for s in t.subtasks],  # recursive
            }

        for g in sorted_goals:
            view = _goal_view(g)
            view_size = len(str(view))
            if used + view_size <= char_budget:
                hot.append(view)
                used += view_size
            else:
                cold.append({
                    "id": g.id,
                    "intent": g.intent[:60],
                    "status": g.status,
                    "task_count": sum(1 for _ in _flatten_tasks(g)),
                    "abandoned_count": sum(len(t.abandoned_alternatives) for t in _flatten_tasks(g)),
                })

        return {"hot": {"goals": hot}, "cold": cold}

    def expand(self, branch_ids: list[str]) -> dict:
        """Return full subtree for given branch ids, touching them."""
        now = time.time()
        out = {"goals": []}
        for bid in branch_ids:
            g = self._goal_by_id.get(bid)
            if g:
                g.last_accessed_at = now
                out["goals"].append(_full_goal_view(g))
                continue
            t = self._task_by_id.get(bid)
            if t:
                t.last_accessed_at = now
                # Find owning goal and surface that subtree focused on the task
                for owning in self.goals:
                    if t in _flatten_tasks(owning):
                        out["goals"].append(_full_goal_view(owning))
                        break
        return out

    def to_session(self, session_id: str = "", project_path: str = "",
                    display_name: str = "", turns: list[DialogueTurn] | None = None) -> Session:
        """Snapshot current tree as a Session for serialization / framing pass."""
        return Session(
            session_id=session_id, project_path=project_path,
            display_name=display_name,
            goals=self.goals,
            turns=turns or [],
        )


# ─── helpers ───

class StateError(Exception):
    """Raised when a mutation can't be applied (invalid id / inconsistent state)."""


def _count_tasks(g: Goal) -> int:
    n = 0
    def walk(t):
        nonlocal n
        n += 1
        for s in t.subtasks: walk(s)
    for t in g.tasks: walk(t)
    return n


def _flatten_tasks(g: Goal) -> list[Task]:
    out: list[Task] = []
    def walk(t):
        out.append(t)
        for s in t.subtasks: walk(s)
    for t in g.tasks: walk(t)
    return out


def _full_goal_view(g: Goal) -> dict:
    """Full subtree dump (no truncation) for round-2 expansion."""
    return {
        "id": g.id, "intent": g.intent, "status": g.status,
        "constraints": list(g.constraints),
        "tasks": [_full_task_view(t) for t in g.tasks],
    }


def _full_task_view(t: Task) -> dict:
    return {
        "id": t.id, "name": t.name, "status": t.status,
        "outcome": t.outcome, "outcome_unit_id": t.outcome_unit_id,
        "constraints": list(t.constraints),
        "soft_constraints": list(t.soft_constraints),
        "abandoned_alternatives": list(t.abandoned_alternatives),
        "lesson_unit_ids": list(t.lesson_unit_ids),
        "lessons": list(t.lessons),
        "soft_lessons": list(t.soft_lessons),
        "terms": list(t.terms),
        "linked_unit_ids": list(t.linked_unit_ids),
        "subtasks": [_full_task_view(s) for s in t.subtasks],
    }
