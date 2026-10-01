"""Shared evaluation protocol; stage-specific gold and scoring live in each stage."""
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from unittest.mock import patch
from . import llm as copilot_api
from .models import DialogueTurn, AtomicUnit, Task


@dataclass
class Case:
    stage: str
    name: str
    system: str
    body: str
    fixture: dict
    gold: dict
    output_limit: int = 4096
    goal: str = ""

    def snapshot(self):
        return {"stage": self.stage, "name": self.name, "system": self.system,
                "body": self.body, "fixture": json.loads(json.dumps(self.fixture, default=sorted)), "gold": self.gold,
                "output_limit": self.output_limit, "goal": self.goal}

    def digest(self):
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def turn(number, human, agent, before="", units=None):
    return DialogueTurn(number, "2026-04-20T10:00:00Z", agent, human,
                        source_uuid=f"turn-{number}", preceding_agent_raw=before, complete=True,
                        agent_split={"head": agent, "tail": "", "truncated_chars": 0},
                        units=units or [])


def fact(turn_id, speaker, acts, patterns):
    return {"turn": turn_id, "speaker": speaker, "acts": acts, "patterns": patterns}


def capture_prompt(fn, *args, **kwargs):
    captured = {}

    class Captured(Exception):
        pass

    def intercept(system, body, **options):
        captured.update(system=system, body=body)
        raise Captured()

    try:
        with patch.object(copilot_api, "chat_content", side_effect=intercept):
            fn(*args, **kwargs)
    except Captured:
        pass
    if not captured:
        raise ValueError("Stage did not construct a model request")
    return captured["system"], captured["body"]


def matches(text, patterns):
    return all(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def ratio(hits, count):
    return round(hits / count, 4) if count else 1.0


def goal_of(sm, task_id):
    task = sm._task_by_id.get(task_id)
    visited = set()
    while task and task.parent_type == "task":
        if task.id in visited:
            raise ValueError("Task cycle")
        visited.add(task.id)
        task = sm._task_by_id.get(task.parent_id)
    return task.parent_id if task else None


def is_under(sm, child, parent):
    task = sm._task_by_id.get(child)
    visited = set()
    while task:
        if task.id == parent:
            return True
        if task.id in visited:
            return False
        visited.add(task.id)
        task = sm._task_by_id.get(task.parent_id)
    return False


def constraint_path(sm, task_id):
    texts, seen = [], set()
    node = sm._task_by_id.get(task_id)
    while node and node.id not in seen:
        seen.add(node.id)
        texts.extend(node.constraints)
        node = sm._task_by_id.get(node.parent_id) or sm._goal_by_id.get(node.parent_id) if isinstance(node, Task) else None
    return " ".join(texts)


def action_lists(result):
    if result.get("action"):
        name = result["action"]
        if name == "done":
            return {"done": True, "candidates": result.get("candidates", [])}
        return {name: [result]}
    return result


def parse_json(text):
    return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
