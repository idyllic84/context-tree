"""Claude Code JSONL session parser."""

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from context_tree.common.models import DialogueTurn
from context_tree.common.config import sessions_dir, data_dir

CLAUDE_PROJECTS = sessions_dir()

# Adapter populates DialogueTurn.meta_signals with these markers when consecutive
# turns differ in time / context. Tier 1 / Tier 2 use them as topic-shift hints.
LONG_GAP_THRESHOLD_HOURS = 1.0  # gap >= this triggers "long_gap:Nh"

# File extensions worth tracking when extracting paths from text mentions.
# Matches only ABSOLUTE paths to avoid ambiguity + runtime-cwd contamination:
#   - Unix absolute: /foo or ~/foo
#   - Windows drive: C:\foo or D:/foo
#   - UNC: \\server\share
# Negative lookbehind rejects paths glued to preceding word char or CJK
# (e.g. "更新/home/example/..." or "ab/c.rs" — the former is noise, latter is relative).
# Relative paths in dialogue get resolved via Tier 1 resolved_paths (context-aware).
PATH_REGEX = re.compile(
    r'(?<![\w\u4e00-\u9fff])'
    r'(?:'
    r'[A-Za-z]:[\\/]'
    r'|\\\\[\w-]+\\'
    r'|~?/'
    r')'
    r'[\w./\\_-]+\.'
    r'(rs|py|ts|tsx|js|jsx|vue|swift|md|json|toml|yml|yaml|sh|sql|xml|css|html'
    r'|go|java|kt|cs|cpp|c|h|m|mm|jsonl|txt|csv|conf|ini|env|lock|gradle|proto)\b'
)

# Build / cache / vendor dirs to skip even if inside a project.
TEMP_PATH_PATTERNS = (
    "/node_modules/", "/__pycache__/", "/.venv/", "/venv/",
    "/target/debug/", "/target/release/", "/.next/",
    "/.cache/", "/build/", "/dist/", "/.git/",
)


def get_device_id() -> str:
    path = data_dir() / "device_id"
    if path.exists():
        return str(uuid.UUID(path.read_text(encoding="utf-8").strip()))
    path.parent.mkdir(parents=True, exist_ok=True)
    identifier = str(uuid.uuid4())
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(identifier)
    except FileExistsError:
        return str(uuid.UUID(path.read_text(encoding="utf-8").strip()))
    return identifier


def is_temp_path(path: str) -> bool:
    return any(p in path for p in TEMP_PATH_PATTERNS)


def split_agent_text(text: str) -> dict:
    """Dynamic head/tail truncation for per-turn agent_raw.

    Rule (per design discussion):
      len ≤ 400  → full text (head=text, tail="", truncated=0)
      len > 400  → head = text[:200]
                   tail_size = min(800, (len // 1000) * 100)
                   tail = text[-tail_size:]
      Safety: if 200 + tail_size ≥ len → keep full (avoid head+tail overshoot).

    Examples:
      400   → full
      999   → head 200, tail 0   (truncated 799)
      1500  → head 200, tail 100 (truncated 1200)
      3500  → head 200, tail 300 (truncated 3000)
      8000+ → head 200, tail 800 (cap)
    """
    n = len(text)
    if n <= 400:
        return {"head": text, "tail": "", "truncated_chars": 0}
    tail_size = min(800, (n // 1000) * 100)
    if 200 + tail_size >= n:
        return {"head": text, "tail": "", "truncated_chars": 0}
    return {
        "head": text[:200],
        "tail": text[-tail_size:] if tail_size else "",
        "truncated_chars": n - 200 - tail_size,
    }


def in_project(path: str, project_paths: set[str]) -> bool:
    canonical = os.path.normpath(path)
    return any(canonical == p or canonical.startswith(p + os.sep)
                for p in project_paths)


def canonicalize_path(path: str) -> str:
    """Expand ~, make absolute, normalize separators."""
    return os.path.normpath(os.path.abspath(os.path.expanduser(path)))


@dataclass
class SessionRecord:
    session_id: str
    project_path: str
    display_name: str
    file_path: str
    file_count: int = 0  # Total lines in JSONL (for change detection)
    # L2 cross-session linkage (Spec V1 §3.7)
    parent_session_id: str | None = None  # /resume or /fork: parent session uuid
    parent_leaf_uuid: str | None = None   # uuid in parent session this one branched from
    is_fork: bool = False                  # True if /fork (mid-branch) vs /resume (leaf-extend)
    chain_root_id: str | None = None      # root of this conversation chain (= self if root)


def discover_sessions() -> list[SessionRecord]:
    """Find all Claude Code session JSONL files, sorted by mtime desc.

    Also resolves cross-session parent-child links (Spec V1 §3.7):
      /resume → new session's first user message has parentUuid pointing to
                a leaf message in another session
      /fork   → similar but mid-branch
      Both leave a `type: "summary"` entry with leafUuid in the new session
    """
    sessions = []
    if not CLAUDE_PROJECTS.exists():
        return sessions

    # Pass 1: enumerate JSONLs, collect basic metadata + summary entries
    for jsonl in CLAUDE_PROJECTS.rglob("*.jsonl"):
        if "subagents" in str(jsonl) or "tool-results" in str(jsonl):
            continue
        if jsonl.name.startswith("agent-"):
            continue

        sid = jsonl.stem
        display = sid[:8]
        leaf_uuid_ref: str | None = None  # leafUuid this session's summary references

        try:
            with open(jsonl) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "summary" and msg.get("leafUuid") and not leaf_uuid_ref:
                        leaf_uuid_ref = msg.get("leafUuid")
                    if slug := msg.get("slug"):
                        if display == sid[:8]:
                            display = slug
                    if msg.get("type") == "custom-title":
                        display = msg.get("customTitle", display)
        except Exception:
            continue

        project = str(jsonl.parent.name).replace("-", "/")
        file_count = sum(1 for _ in open(jsonl))

        rec = SessionRecord(
            session_id=sid, project_path=project,
            display_name=display, file_path=str(jsonl),
            file_count=file_count,
        )
        rec.parent_leaf_uuid = leaf_uuid_ref  # resolved to parent_session_id in Pass 2
        sessions.append(rec)

    # Pass 2: build uuid → session_id map (per project), then resolve parents
    by_project: dict[str, list[SessionRecord]] = {}
    for s in sessions:
        by_project.setdefault(s.project_path, []).append(s)

    for project, recs in by_project.items():
        uuid_to_session: dict[str, str] = {}
        for r in recs:
            try:
                with open(r.file_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        u = msg.get("uuid")
                        if u:
                            uuid_to_session[u] = r.session_id
            except Exception:
                pass

        # Resolve parent_session_id from parent_leaf_uuid
        for r in recs:
            if r.parent_leaf_uuid:
                r.parent_session_id = uuid_to_session.get(r.parent_leaf_uuid)

        # Compute chain_root_id by walking parent links
        for r in recs:
            seen = set()
            cur = r
            while cur.parent_session_id and cur.parent_session_id not in seen:
                seen.add(cur.parent_session_id)
                parent = next((x for x in recs if x.session_id == cur.parent_session_id), None)
                if not parent:
                    break
                cur = parent
            r.chain_root_id = cur.session_id

    sessions.sort(key=lambda s: os.path.getmtime(s.file_path), reverse=True)
    return sessions


# ─── V2 raw turn extraction (no filtering, no truncation) ───

def parse_turns(file_path: str) -> tuple[list[DialogueTurn], str]:
    """Parse JSONL → list[DialogueTurn] with FULL agent + human content.

    Groups each user message with its following assistant response and tool paths.
    No trivial filter, no length truncation, no code fence stripping.
    Output turns have only raw fields populated; downstream tiers fill the rest.

    Filters applied (data-source hygiene only):
      - isSidechain: subagent messages
      - isCompactSummary: auto-generated compression summaries
      - isMeta: CLI-synthesized wrappers (e.g., <local-command-caveat>)
      - CLI tag prefixes: <task-notification>, <command-name>, <system-reminder>, ...
      - tool_result blocks: not user input

    Returns: (turns, project_path)
    """
    turns: list[DialogueTurn] = []
    last_agent_text = ""
    response_complete = False
    last_agent_cwd: str | None = None
    last_agent_branch: str | None = None
    last_agent_ts: str | None = None
    project_path = ""
    turn_id = 0
    prev_turn_cwd: str | None = None
    prev_turn_branch: str | None = None
    prev_turn_ts: str | None = None

    # File-path extraction state
    session_project_paths: set[str] = set()
    pending_tool_uses: list[tuple[str, str]] = []  # [(tool_name, canonical_path), ...]
    # Sliding window of recent (path, action_label, source_turn_id) for fuzzy ref resolution.
    recent_paths_window: list[dict] = []
    RECENT_WINDOW = 15
    TOOL_ACTION_LABELS = {
        "Read": "read", "Glob": "searched", "Grep": "searched",
        "Write": "created",
        "Edit": "modified", "MultiEdit": "modified", "NotebookEdit": "modified",
    }

    def _flush_pending_to_last_turn():
        """Attribute accumulated tool_use paths to the most recent turn (which triggered them).
        Also updates the recent_paths sliding window for downstream Tier 1 context.
        """
        if not turns or not pending_tool_uses:
            return
        last = turns[-1]
        for tool_name, path in pending_tool_uses:
            if tool_name in ("Read", "Glob", "Grep"):
                if path not in last.tool_inputs:
                    last.tool_inputs.append(path)
            elif tool_name == "Write":
                if path not in last.tool_outputs:
                    last.tool_outputs.append(path)
            elif tool_name in ("Edit", "MultiEdit", "NotebookEdit"):
                if path not in last.tool_modifies:
                    last.tool_modifies.append(path)
            # Update sliding window (most recent first, dedup by path keeping latest)
            recent_paths_window[:] = [e for e in recent_paths_window if e["path"] != path]
            recent_paths_window.insert(0, {
                "path": path,
                "action": TOOL_ACTION_LABELS.get(tool_name, tool_name.lower()),
                "source_turn_id": last.turn_id,
            })
            del recent_paths_window[RECENT_WINDOW:]
        pending_tool_uses.clear()

    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if cwd := msg.get("cwd"):
                if not project_path:
                    project_path = cwd
                session_project_paths.add(os.path.normpath(cwd))

            msg_type = msg.get("type", "")

            if msg_type == "assistant" and not msg.get("isSidechain"):
                message = msg.get("message", {})
                content = message.get("content", "")
                if message.get("stop_reason") in ("end_turn", "stop_sequence"):
                    response_complete = True
                elif message.get("stop_reason") == "tool_use":
                    response_complete = False
                parts = []
                if isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text":
                            if t := block.get("text", "").strip():
                                parts.append(t)
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {}) or {}
                            fp = tool_input.get("file_path")
                            # MultiEdit may carry multiple via edits[]; NotebookEdit similar
                            paths_in_call: list[str] = []
                            if fp:
                                paths_in_call.append(fp)
                            for sub in (tool_input.get("edits") or []):
                                if isinstance(sub, dict) and (p := sub.get("file_path")):
                                    paths_in_call.append(p)
                            for raw_path in paths_in_call:
                                canonical = canonicalize_path(raw_path)
                                if not in_project(canonical, session_project_paths):
                                    continue
                                if is_temp_path(canonical):
                                    continue
                                pending_tool_uses.append((tool_name, canonical))
                elif isinstance(content, str) and content.strip():
                    parts.append(content.strip())
                if parts:
                    last_agent_text = "\n\n".join(filter(None, [last_agent_text, *parts]))
                last_agent_cwd = msg.get("cwd")
                last_agent_branch = msg.get("gitBranch")
                last_agent_ts = msg.get("timestamp")

            elif msg_type in ("user", "human"):
                # Filter non-real-user messages:
                #   - sidechain (sub-agent conversations)
                #   - compact summary (Claude Code auto-generated)
                #   - isMeta=true (CLI-synthesized wrappers like <local-command-caveat>)
                if msg.get("isSidechain") or msg.get("isCompactSummary") or msg.get("isMeta"):
                    continue

                content = msg.get("message", {}).get("content", "")

                if isinstance(content, list):
                    if any(b.get("type") == "tool_result" for b in content):
                        continue
                    text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
                elif isinstance(content, str):
                    text = content
                else:
                    continue

                text = text.strip()
                if not text:
                    continue

                # Claude Code CLI injects synthesized content as type:"user" messages
                # without a distinguishing metadata field. Filter by known tag prefixes.
                # (isMeta handles <local-command-caveat>; others have no flag.)
                CLI_SYNTHESIZED_PREFIXES = (
                    "<task-notification>",
                    "<command-name>",
                    "<command-message>",
                    "<command-args>",
                    "<local-command-stdout>",
                    "<local-command-stderr>",
                    "<system-reminder>",
                    "[Request interrupted by user",
                )
                if text.startswith(CLI_SYNTHESIZED_PREFIXES):
                    continue

                # Before pushing this new turn, flush in-flight tool_use paths
                # to the previous turn (those tool ops were the agent responding to it).
                _flush_pending_to_last_turn()
                if turns:
                    turns[-1].agent_raw = last_agent_text
                    turns[-1].agent_split = split_agent_text(last_agent_text)
                    turns[-1].complete = True

                ts = msg.get("timestamp", "")
                cur_cwd = msg.get("cwd") or last_agent_cwd
                cur_branch = msg.get("gitBranch") or last_agent_branch

                # Compute meta_signals vs previous turn
                meta_signals: list[str] = []
                if prev_turn_ts and ts:
                    gap_h = _hours_between(prev_turn_ts, ts)
                    if gap_h is not None and gap_h >= LONG_GAP_THRESHOLD_HOURS:
                        if gap_h >= 24:
                            meta_signals.append(f"long_gap:{gap_h/24:.0f}d")
                        else:
                            meta_signals.append(f"long_gap:{gap_h:.0f}h")
                if prev_turn_cwd and cur_cwd and cur_cwd != prev_turn_cwd:
                    meta_signals.append(f"cwd_changed:{cur_cwd.split('/')[-1]}")
                if prev_turn_branch and cur_branch and cur_branch != prev_turn_branch:
                    meta_signals.append(f"branch_changed:{cur_branch}")

                # Extract path mentions from human text. Regex only matches absolute
                # paths; don't canonicalize (already absolute by construction).
                mentioned: list[str] = []
                for m in PATH_REGEX.finditer(text):
                    raw = m.group(0)
                    # Expand ~ but keep as-is otherwise
                    if raw.startswith("~"):
                        raw = os.path.expanduser(raw)
                    if raw not in mentioned:
                        mentioned.append(raw)

                # Snapshot current recent_paths_window with relative turns_ago for this turn
                recent_ctx = [
                    {
                        "path": e["path"],
                        "action": e["action"],
                        "turns_ago": turn_id - e["source_turn_id"],
                    }
                    for e in recent_paths_window
                ]

                turns.append(DialogueTurn(
                    turn_id=turn_id,
                    timestamp=ts,
                    agent_raw="",
                    human_raw=text,
                    preceding_agent_raw=last_agent_text,
                    source_uuid=msg.get("uuid", ""),
                    meta_signals=meta_signals,
                    mentioned_paths=mentioned,
                    recent_paths_context=recent_ctx,
                    agent_split=split_agent_text(""),
                ))
                turn_id += 1
                last_agent_text = ""
                response_complete = False
                prev_turn_ts = ts
                prev_turn_cwd = cur_cwd
                prev_turn_branch = cur_branch

    # End of session: flush any remaining tool_use paths to the last turn
    _flush_pending_to_last_turn()
    if turns:
        turns[-1].agent_raw = last_agent_text
        turns[-1].agent_split = split_agent_text(last_agent_text)
        turns[-1].complete = response_complete

    return turns, project_path


def _hours_between(ts_a: str, ts_b: str) -> float | None:
    """Hours between two ISO 8601 timestamps. Returns None if either is unparseable."""
    try:
        ta = datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
        tb = datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
        return abs((tb - ta).total_seconds()) / 3600.0
    except (ValueError, TypeError):
        return None
