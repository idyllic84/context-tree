"""Aligned dialogue spans, source-linked units, persistent task trees and pending responses."""

from dataclasses import dataclass, field


# Human dialogue acts (spec §2)
HUMAN_ACTS = {"instruct", "constrain", "ask", "affirm", "reject", "answer", "report"}

# Agent dialogue acts (spec §2)
AGENT_ACTS = {"propose", "explain", "clarify", "report"}

ALL_ACTS = HUMAN_ACTS | AGENT_ACTS

# Scope classification for `instruct` units (spec §3.1 / §4.3)
INSTRUCT_SCOPES = {"new_goal", "new_task", "subtask"}

# Status lifecycle (spec §3.4)
STATUS_VALUES = {"pending", "in_progress", "blocked", "completed", "abandoned", "achieved"}


@dataclass
class AtomicUnit:
    """A single dialogue act extracted from a turn."""
    id: str                       # session-local: "u1", "u2", ...
    speaker: str                  # "agent" | "human"
    act: str                      # one of ALL_ACTS
    text: str                     # original phrasing (preserve)
    target: str | None = None     # affirm/reject → points to prior agent unit id
    correction: str | None = None # reject's correction text, if any

    # L2 classification (Tier 2 atomizer fills for instruct units)
    scope: str | None = None      # instruct: "new_goal" | "new_task" | "subtask" | None
    parent_id: str | None = None  # subtask: prior instruct unit id whose Task/Goal it belongs to

    # Agent unit attribution (Tier 2 fills for propose/explain)
    for_task_id: str | None = None  # instruct unit id whose Task this propose/explain serves

    # B-specific: state machine fills acceptance based on user reactions
    acceptance: str | None = None    # "hard" | "soft" | "rejected" | "unclaimed" | None
    # B-specific: framing_pass (T3.5) fills purpose-framed title + body
    purpose_title: str | None = None
    purpose_body: str | None = None
    framing_failed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "speaker": self.speaker, "act": self.act, "text": self.text,
            "target": self.target, "correction": self.correction,
            "scope": self.scope, "parent_id": self.parent_id,
            "for_task_id": self.for_task_id,
            "acceptance": self.acceptance,
            "purpose_title": self.purpose_title,
            "purpose_body": self.purpose_body,
            "framing_failed": self.framing_failed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AtomicUnit":
        return cls(
            id=d["id"], speaker=d["speaker"], act=d["act"], text=d["text"],
            target=d.get("target"), correction=d.get("correction"),
            scope=d.get("scope"), parent_id=d.get("parent_id"),
            for_task_id=d.get("for_task_id"),
            acceptance=d.get("acceptance"),
            purpose_title=d.get("purpose_title"),
            purpose_body=d.get("purpose_body"),
            framing_failed=bool(d.get("framing_failed", False)),
        )


@dataclass
class DialogueTurn:
    """A user message and the assistant response/tool operations it triggers."""
    turn_id: int
    timestamp: str
    agent_raw: str                # full agent content (not truncated)
    human_raw: str                # user message text
    source_uuid: str = ""
    preceding_agent_raw: str = ""
    complete: bool = False

    # Adapter-level metadata signals (populated by claude_adapter from JSONL fields)
    # Used as hints by Tier 1 / Tier 2 to detect topic shifts.
    # Examples: ["long_gap:4h", "cwd_changed:/new/path", "branch_changed:feature-x"]
    meta_signals: list[str] = field(default_factory=list)

    # File paths agent touched via tool_use during the agent's response to this turn.
    # Adapter restricts to in-project paths (any cwd seen in session) excluding temp/build dirs.
    tool_inputs: list[str] = field(default_factory=list)    # Read/Glob/Grep
    tool_outputs: list[str] = field(default_factory=list)   # Write (new file)
    tool_modifies: list[str] = field(default_factory=list)  # Edit/MultiEdit/NotebookEdit
    # File paths mentioned in human_raw text (regex), any location (user's explicit refs).
    mentioned_paths: list[str] = field(default_factory=list)
    # Sliding window of recent tool-use paths from the session (most recent first),
    # passed as Tier 1 prompt context to help LLM resolve vague refs ("更新那个文档").
    recent_paths_context: list[dict] = field(default_factory=list)  # [{path, action, turns_ago}]

    # Tier 1 output
    skip: bool = False
    agent_key_points: list[str] = field(default_factory=list)  # V2-A field, B leaves empty
    human_normalized: str = ""
    # Tier 1 also resolves vague file refs in human_raw using recent_paths_context.
    resolved_paths: list[str] = field(default_factory=list)
    # B-specific: head/tail-preserved agent text per activity
    # Each entry: {"activity": "propose|explain|clarify|report",
    #              "head": str, "tail": str, "truncated_chars": int}
    agent_segments: list[dict] = field(default_factory=list)
    # Adapter-level dynamic split of agent_raw (per-turn, replaces L1 segment splitting):
    #   {"head": str, "tail": str, "truncated_chars": int}
    # Rule: len ≤ 400 → full (head=text, tail="", truncated=0)
    #       len > 400 → head=text[:200], tail_size=min(800, (len//1000)*100), tail=text[-tail_size:]
    agent_split: dict = field(default_factory=dict)

    # Tier 2 output
    units: list[AtomicUnit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id, "timestamp": self.timestamp,
            "agent_raw": self.agent_raw, "human_raw": self.human_raw,
            "source_uuid": self.source_uuid,
            "preceding_agent_raw": self.preceding_agent_raw,
            "complete": self.complete,
            "meta_signals": list(self.meta_signals),
            "tool_inputs": list(self.tool_inputs),
            "tool_outputs": list(self.tool_outputs),
            "tool_modifies": list(self.tool_modifies),
            "mentioned_paths": list(self.mentioned_paths),
            "recent_paths_context": list(self.recent_paths_context),
            "skip": self.skip,
            "agent_key_points": list(self.agent_key_points),
            "human_normalized": self.human_normalized,
            "resolved_paths": list(self.resolved_paths),
            "agent_segments": list(self.agent_segments),
            "agent_split": dict(self.agent_split),
            "units": [u.to_dict() for u in self.units],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DialogueTurn":
        return cls(
            turn_id=d["turn_id"], timestamp=d["timestamp"],
            agent_raw=d["agent_raw"], human_raw=d["human_raw"],
            source_uuid=d.get("source_uuid", ""),
            preceding_agent_raw=d.get("preceding_agent_raw", ""),
            complete=bool(d.get("complete", False)),
            meta_signals=list(d.get("meta_signals", [])),
            tool_inputs=list(d.get("tool_inputs", [])),
            tool_outputs=list(d.get("tool_outputs", [])),
            tool_modifies=list(d.get("tool_modifies", [])),
            mentioned_paths=list(d.get("mentioned_paths", [])),
            recent_paths_context=list(d.get("recent_paths_context", [])),
            skip=bool(d.get("skip", False)),
            agent_key_points=list(d.get("agent_key_points", [])),
            human_normalized=d.get("human_normalized", ""),
            resolved_paths=list(d.get("resolved_paths", [])),
            agent_segments=list(d.get("agent_segments", [])),
            agent_split=dict(d.get("agent_split", {})),
            units=[AtomicUnit.from_dict(u) for u in d.get("units", [])],
        )


# ─── L2 Task hierarchy ───


@dataclass
class Task:
    """Concrete step serving a Goal. Can contain subtasks recursively."""
    id: str
    name: str                                    # concrete step: "check git log"
    parent_id: str                               # Goal.id or parent Task.id
    parent_type: str                             # "goal" | "task"
    status: str = "pending"                      # STATUS_VALUES
    constraints: list[str] = field(default_factory=list)
    soft_constraints: list[str] = field(default_factory=list)  # added by reflexion (lower confidence)
    outcome: str | None = None
    outcome_soft: bool = False                   # True if outcome from implicit feedback (no explicit affirm)
    abandoned_alternatives: list[dict] = field(default_factory=list)  # [{approach, reason}]
    lessons: list[str] = field(default_factory=list)
    soft_lessons: list[str] = field(default_factory=list)  # implicit-promoted explain or reflexion-added
    terms: list[str] = field(default_factory=list)
    subtasks: list["Task"] = field(default_factory=list)
    source_unit_id: str | None = None            # instruct unit that created this task
    linked_unit_ids: list[str] = field(default_factory=list)
    # C: recency for hot/cold tree access pattern
    last_accessed_at: float = 0.0                 # epoch seconds; 0 = never touched

    # B-specific: unit_id refs replace V2-A's flat string folding
    outcome_unit_id: str | None = None
    lesson_unit_ids: list[str] = field(default_factory=list)
    abandoned_unit_ids: list[dict] = field(default_factory=list)  # [{unit_id, correction_unit_id?}]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "parent_id": self.parent_id, "parent_type": self.parent_type,
            "status": self.status,
            "constraints": list(self.constraints),
            "soft_constraints": list(self.soft_constraints),
            "outcome": self.outcome,
            "outcome_soft": self.outcome_soft,
            "abandoned_alternatives": list(self.abandoned_alternatives),
            "lessons": list(self.lessons),
            "soft_lessons": list(self.soft_lessons),
            "terms": list(self.terms),
            "subtasks": [s.to_dict() for s in self.subtasks],
            "source_unit_id": self.source_unit_id,
            "linked_unit_ids": list(self.linked_unit_ids),
            "last_accessed_at": self.last_accessed_at,
            "outcome_unit_id": self.outcome_unit_id,
            "lesson_unit_ids": list(self.lesson_unit_ids),
            "abandoned_unit_ids": list(self.abandoned_unit_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d["id"], name=d["name"],
            parent_id=d["parent_id"], parent_type=d["parent_type"],
            status=d.get("status", "pending"),
            constraints=list(d.get("constraints", [])),
            soft_constraints=list(d.get("soft_constraints", [])),
            outcome=d.get("outcome"),
            outcome_soft=bool(d.get("outcome_soft", False)),
            abandoned_alternatives=list(d.get("abandoned_alternatives", [])),
            lessons=list(d.get("lessons", [])),
            soft_lessons=list(d.get("soft_lessons", [])),
            terms=list(d.get("terms", [])),
            subtasks=[Task.from_dict(s) for s in d.get("subtasks", [])],
            source_unit_id=d.get("source_unit_id"),
            linked_unit_ids=list(d.get("linked_unit_ids", [])),
            last_accessed_at=float(d.get("last_accessed_at", 0.0)),
            outcome_unit_id=d.get("outcome_unit_id"),
            lesson_unit_ids=list(d.get("lesson_unit_ids", [])),
            abandoned_unit_ids=list(d.get("abandoned_unit_ids", [])),
        )


@dataclass
class Goal:
    """High-level purpose of a session segment. Contains tasks."""
    id: str
    intent: str                                  # high-level purpose: "diagnose data loss"
    status: str = "pending"                      # STATUS_VALUES
    constraints: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    source_unit_id: str | None = None            # instruct unit that created this goal
    linked_unit_ids: list[str] = field(default_factory=list)
    # C: recency for hot/cold tree access pattern
    last_accessed_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "intent": self.intent,
            "status": self.status,
            "constraints": list(self.constraints),
            "tasks": [t.to_dict() for t in self.tasks],
            "source_unit_id": self.source_unit_id,
            "linked_unit_ids": list(self.linked_unit_ids),
            "last_accessed_at": self.last_accessed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        return cls(
            id=d["id"], intent=d["intent"],
            status=d.get("status", "pending"),
            constraints=list(d.get("constraints", [])),
            tasks=[Task.from_dict(t) for t in d.get("tasks", [])],
            source_unit_id=d.get("source_unit_id"),
            linked_unit_ids=list(d.get("linked_unit_ids", [])),
            last_accessed_at=float(d.get("last_accessed_at", 0.0)),
        )


@dataclass
class Session:
    """Session-level container for L1 (turns) + L2 (goals)."""
    session_id: str
    project_path: str
    display_name: str
    goals: list[Goal] = field(default_factory=list)
    turns: list[DialogueTurn] = field(default_factory=list)
    pending_turns: list[DialogueTurn] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_path": self.project_path,
            "display_name": self.display_name,
            "goals": [g.to_dict() for g in self.goals],
            "turns": [t.to_dict() for t in self.turns],
            "pending_turns": [t.to_dict() for t in self.pending_turns],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        return cls(
            session_id=d["session_id"],
            project_path=d["project_path"],
            display_name=d["display_name"],
            goals=[Goal.from_dict(g) for g in d.get("goals", [])],
            turns=[DialogueTurn.from_dict(t) for t in d.get("turns", [])],
            pending_turns=[DialogueTurn.from_dict(t) for t in d.get("pending_turns", [])],
        )
