"""Extract aligned dialogue units with stable feedback references and sequential split recovery."""
import json
import time
import context_tree.common.llm as copilot_api
from context_tree.stages.ingest.processor import split_agent_text
from context_tree.common.models import DialogueTurn, AtomicUnit, HUMAN_ACTS, AGENT_ACTS


BATCH_MAX_INPUT_CHARS = 30000
BATCH_MAX_TURNS = 60
RECENT_AGENT_KEEP = 30


SYSTEM_PROMPT = """Atomic unit extraction for human↔AI-coding-agent dialogue.
CN/EN/mixed. Output matches source language.

INPUT:
  [RECENT] — agent unit summaries from prior batches (id+act+80c text), for
             cross-batch target resolution (e.g. "ok" affirming an old propose).
  [TURNS]  — current batch dialogue turns. Each turn shows agent text as
             head + tail with a truncated_chars marker (adapter handles split,
             not you). Treat head+tail as the agent's full reply for that turn.

TURN ANATOMY:
  Each turn contains human_raw followed by agent_after and the tool operations
  triggered by that human message. Emit human units BEFORE the agent unit.
  agent_before is the previous turn's response, shown ONLY to interpret reactions.
  Never emit a second unit for agent_before; reference its existing unit from
  earlier turns or [RECENT]. Human affirm/reject cannot target a future response.
  Empty agent_after means no agent unit. Consecutive human messages remain separate.
  "好的" / "yes" targets the previous proposed response, not the response triggered
  by this agreement. A message can both accept earlier work and instruct new work.

For each turn produce:

skip (bool): true ONLY if BOTH human and agent sides have no decision content.

human_normalized (str): resolve deictic refs from agent_before, else echo human_raw.

resolved_paths (list[str]): if human_raw contains vague file references (e.g.
  "那个文档" / "上次的文件" / "它" / "the doc" / "that file"), resolve to
  concrete absolute paths by matching against [recent_files] and
  [agent_tool_use_this_turn]. STRICT rules:
    - Only emit paths that appear verbatim in those two lists. NEVER invent.
    - Empty list [] if no vague references in human_raw.
    - If human_raw mentions a file path explicitly, do NOT echo it here
      (mentioned_paths covers that downstream — only resolve VAGUE refs).

units (list): atomic dialogue units.

Unit fields:
  id        : "u<N>" — assign next monotonic N (continue from `next_unit_id` hint)
  speaker   : "agent" | "human"
  act       : STRICTLY one of:
              Human: instruct, constrain, ask, affirm, reject, answer, report
              Agent: propose, explain, clarify, report
  target    : "u<M>" only on affirm/reject (prior agent unit, may be from RECENT)
  correction: optional str on reject (corrective text)
  text      : concise, faithful activity/constraint content (≤200 chars).
              Preserve scope, negation, concrete identifiers and conditions.

CRITICAL act rules:
- "ok" / "好的" / "1" alone = affirm with target = most recent unclaimed propose
- Long human turn with multiple acts → split into multiple units
- AGENT side: emit AT MOST ONE agent unit per turn. Two user messages bound a
  single task slice; everything the agent did between them is one unit. Pick
  the dominant act (propose > clarify > explain > report).

DO NOT output any of these (handled by tree layer downstream):
- scope, parent_id, for_task_id  (hierarchy decisions)
- agent_segments  (adapter-level agent_split replaces this)
- tree mutations
- task or goal ids

OUTPUT (strict JSON, single object):
{"turns": [{"turn_id": int, "skip": bool, "human_normalized": str,
            "resolved_paths": [str, ...], "units": [...]}]}
"""


def _format_recent_activity(recent: list[AtomicUnit]) -> str:
    if not recent: return "(none)"
    lines = []
    for u in [unit for unit in recent if unit.speaker == "agent"][-RECENT_AGENT_KEEP:]:
        preview = (u.text or "")[:80].replace("\n", " ")
        lines.append(f"  {u.id} [{u.speaker}/{u.act}] {preview}")
    return "\n".join(lines)


def _format_agent(t: DialogueTurn) -> str:
    """Render agent reply using adapter's pre-computed split (head + tail + truncated marker)."""
    sp = t.agent_split or {}
    head = sp.get("head", "") or ""
    tail = sp.get("tail", "") or ""
    trunc = int(sp.get("truncated_chars") or 0)
    if not tail and not trunc:
        return head
    if not tail:
        return f"{head}\n…[{trunc} chars omitted]…"
    return f"{head}\n…[{trunc} chars omitted]…\n{tail}"


def _format_turns(batch: list[DialogueTurn]) -> str:
    parts = []
    for t in batch:
        parts.append(f"## turn {t.turn_id}")
        if t.meta_signals:
            parts.append(f"meta_signals: {', '.join(t.meta_signals)}")
        if t.recent_paths_context:
            parts.append("recent_files (sliding window across recent turns):")
            for e in t.recent_paths_context[:15]:
                parts.append(f"  - {e['path']} ({e['action']}, {e['turns_ago']}t ago)")
        # This turn's own agent tool ops — typically agent processes files
        # in response to user msg of the SAME turn (so paths user mentions
        # vaguely "那个文档" usually refer to these).
        this_turn_ops = []
        for p in t.tool_inputs: this_turn_ops.append(f"read {p}")
        for p in t.tool_outputs: this_turn_ops.append(f"created {p}")
        for p in t.tool_modifies: this_turn_ops.append(f"modified {p}")
        if this_turn_ops:
            parts.append("agent_tool_use_this_turn:")
            for op in this_turn_ops[:15]:
                parts.append(f"  - {op}")
        before = split_agent_text(t.preceding_agent_raw)
        parts.append(f"agent_before (context only):\n{before['head']}\n{before['tail']}")
        parts.append(f"human_raw:\n{t.human_raw}")
        parts.append(f"agent_after:\n{_format_agent(t)}")
        parts.append("")
    return "\n".join(parts)


def _compose_body(batch: list[DialogueTurn], recent: list[AtomicUnit],
                   next_unit_id: int) -> str:
    parts = [
        f"[NEXT_UNIT_ID]\nu{next_unit_id}",
        "",
        "[RECENT]",
        _format_recent_activity(recent),
        "",
        "[TURNS]",
        _format_turns(batch),
    ]
    return "\n".join(parts)


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


def _build_unit(u: dict) -> AtomicUnit | None:
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
            for_task_id=None,  # L2 will set via mutations
        )
    except Exception:
        return None


def _batch_turns(turns: list[DialogueTurn]) -> list[list[DialogueTurn]]:
    out, cur, cur_size = [], [], 0
    for t in turns:
        sp = t.agent_split or {}
        agent_size = len(sp.get("head", "") or "") + len(sp.get("tail", "") or "")
        size = agent_size + len(t.human_raw) + 100
        if cur and (cur_size + size > BATCH_MAX_INPUT_CHARS or len(cur) >= BATCH_MAX_TURNS):
            out.append(cur); cur = []; cur_size = 0
        if not cur and size > BATCH_MAX_INPUT_CHARS:
            out.append([t]); continue
        cur.append(t); cur_size += size
    if cur: out.append(cur)
    return out


def _normalize_batch(data: dict, batch: list[DialogueTurn], recent: list[AtomicUnit],
                     next_id: int) -> tuple[dict, int]:
    if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
        raise ValueError("L1 missing turns array")
    rows = data["turns"]
    expected = [t.turn_id for t in batch]
    if len(rows) != len(expected) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("L1 turn coverage mismatch")
    by_id = {r.get("turn_id"): r for r in rows}
    if set(by_id) != set(expected):
        raise ValueError("L1 duplicate or missing turns")
    rows = [by_id[tid] for tid in expected]
    old_ids = {u.id for u in recent}
    remap = {}
    for row, turn in zip(rows, batch):
        units = row.get("units")
        if not isinstance(units, list) or not isinstance(row.get("skip"), bool):
            raise ValueError("L1 invalid unit/skip fields")
        if not row["skip"] and not units:
            raise ValueError("L1 non-skipped turn has no units")
        agents = 0
        for unit in units:
            if not isinstance(unit, dict):
                raise ValueError("L1 invalid unit")
            uid = unit.get("id")
            speaker = unit.get("speaker")
            acts = HUMAN_ACTS if speaker == "human" else AGENT_ACTS if speaker == "agent" else set()
            if not isinstance(uid, str) or uid in remap or uid in old_ids or unit.get("act") not in acts:
                raise ValueError("L1 invalid id/speaker/act")
            if not isinstance(unit.get("text"), str) or not unit["text"].strip():
                raise ValueError("L1 missing unit content")
            if speaker == "agent":
                agents += 1
                if not turn.agent_raw or agents > 1:
                    raise ValueError("L1 agent unit has no response or exceeds turn granularity")
            elif agents:
                raise ValueError("L1 human units must precede this turn's response")
            remap[uid] = f"u{next_id}"
            next_id += 1
    prior_agents = {u.id for u in recent if u.speaker == "agent"}
    for row in rows:
        for unit in row["units"]:
            target = unit.get("target")
            if target:
                target = remap.get(target, target)
                if unit["speaker"] != "human" or unit["act"] not in ("affirm", "reject") or target not in prior_agents:
                    raise ValueError("L1 feedback target is not an earlier agent response")
                unit["target"] = target
            unit["id"] = remap[unit["id"]]
            if unit["speaker"] == "agent":
                prior_agents.add(unit["id"])
    return {"turns": rows}, next_id


def _call_with_split(batch: list[DialogueTurn], recent: list[AtomicUnit],
                     next_id: int, model: str | None, verbose: int = 1,
                     _depth: int = 0) -> tuple[dict, int]:
    error = None
    for _ in range(2 if len(batch) == 1 else 1):
        try:
            content = copilot_api.chat_content(
                SYSTEM_PROMPT, _compose_body(batch, recent, next_id), model=model, stage="extract")
            return _normalize_batch(_parse(content), batch, recent, next_id)
        except copilot_api.RequestBudgetExceeded:
            raise
        except Exception as exc:
            error = exc
    if len(batch) == 1:
        raise RuntimeError(f"L1 failed for turn {batch[0].turn_id}: {error}") from error
    mid = len(batch) // 2
    if verbose:
        print(f" split {len(batch)}→{mid}+{len(batch)-mid}", end=" ", flush=True)
    left, after_left = _call_with_split(batch[:mid], recent, next_id, model, verbose, _depth + 1)
    left_units = [AtomicUnit.from_dict(u) for row in left["turns"] for u in row["units"]]
    right, after_right = _call_with_split(batch[mid:], recent + left_units, after_left,
                                          model, verbose, _depth + 1)
    return {"turns": left["turns"] + right["turns"]}, after_right


def extract_session(turns: list[DialogueTurn], model: str | None = None,
                    verbose: int = 1, prior_units: list[AtomicUnit] | None = None,
                    next_unit_id: int | None = None) -> tuple[list[AtomicUnit], list[list[DialogueTurn]]]:
    batches = _batch_turns(turns)
    recent = list(prior_units or [])
    next_id = next_unit_id or (max((int(u.id[1:]) for u in recent if u.id[1:].isdigit()), default=0) + 1)
    all_units = []
    for bi, batch in enumerate(batches):
        started = time.perf_counter()
        data, next_id = _call_with_split(batch, recent, next_id, model, verbose)
        for turn, row in zip(batch, data["turns"]):
            turn.skip = row["skip"]
            turn.human_normalized = str(row.get("human_normalized") or turn.human_raw)
            allowed = {e["path"] for e in turn.recent_paths_context}
            allowed.update(turn.tool_inputs + turn.tool_outputs + turn.tool_modifies)
            turn.resolved_paths = [p for p in row.get("resolved_paths", [])
                                   if isinstance(p, str) and p in allowed]
            turn.units = [AtomicUnit.from_dict(u) for u in row["units"]]
            recent.extend(turn.units)
            all_units.extend(turn.units)
        if verbose:
            print(f"   [L1] batch {bi+1}/{len(batches)}: {len(batch)} turns ({time.perf_counter()-started:.1f}s)")
    return all_units, batches
