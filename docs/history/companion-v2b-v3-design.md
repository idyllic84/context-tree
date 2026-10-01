> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Companion V2-B v3 Design — 方案 C: Tree-Native Memory for Agent Continuation

> **C 本质 (one-liner)**: 跨 session 的树形 context 索引，embedding 加速查找。
>
> - 索引结构 = goal/task tree (不是 entity flat list, 不是 graph)
> - 索引范围 = 跨 session 连续 (不是单 session 内闭合)
> - 索引查找 = goal/task 名上的 embedding 匹配 → 返回整棵子树作 context bundle
>
> **统一视角**: 我们做的事和 agent 做的事是 **一样的** ——
> 从 session 开始增量构建任务树。区别只是:
> - Agent: 内部工作记忆，session compact 后丢失
> - 我们: 外部持久化，跨 session 累积成 **森林**
>
> 新 session 不是从 0 开始 —— 借助已有森林匹配，找到该会话的"祖先树"或"姊妹树"，
> 把那些树的 context 注入 agent。Session 结束后，新长出的树并入森林。
>
> **同一原语驱动两端**:
> - 树的成长 (extraction) = mutation ops (push_goal / push_task / affirm_propose ...)
> - 树的匹配 (retrieval) = subtree similarity → bundle return
>
> Major iteration on [companion-v2b-design.md](companion-v2b-design.md).
> Grounded in 2025-2026 research on hierarchical agent memory + intent-aware
> retrieval (refs in §16).
>
> ## ⚠ Status: DRAFT (2026-04-19), not yet implemented

---

## 0. Project context

**Yanmo Companion = AI coding agent's external cross-session memory.**

User talks to Claude/Cursor/etc. Agent has no cross-session memory (or session
compact erases it). We listen to historical sessions, build a knowledge structure,
and **inject relevant context into agent's working memory when user starts a new
session or continues old work**.

Key: user is NOT asking us. User is doing work with agent. We provide the
historical scaffolding agent needs to "continue properly".

---

## 1. Two core insights driving v3

### Insight 1: Tree IS the retrieval primitive (not just an extraction byproduct)

Embedding-only / n-hop graph retrieval works for "find a related fact". But the
real use case is **task continuation** — agent needs to know:
- what user is currently doing
- what was decided already
- what was rejected and why
- which files matter

…as a **coherent bundle**, not scattered top-k entity hits.

A Goal/Task subtree IS that coherent bundle:
- root = goal intent
- branches = tasks (active / completed / abandoned with reasons)
- leaves = decisions / constraints / file edges
- temporal order encoded by tree position

**Tree-match retrieval returns the work-in-progress structure**, not entity
fragments scored by cosine similarity.

Research alignment:
- [Branch-and-Browse (arXiv 2510.19838)](https://arxiv.org/abs/2510.19838) —
  tree-structured reasoning with subtask manager + replay
- [HMT — Hierarchical Memory Tree (arXiv 2603.07024)](https://arxiv.org/abs/2603.07024)
  — three-level intent→stage→action hierarchy with stage-aware retrieval
- [ReAcTree (arXiv 2511.02424)](https://arxiv.org/abs/2511.02424) — hierarchical
  LLM agent trees with subgoal-level episodic memory
- [TaciTree / ImplexConv](https://arxiv.org/abs/2403.13013) — hierarchical
  conversation tree with multi-level summarization for cross-session retrieval

### Insight 2: Goal vs Task distinction is critical for retrieval

Per [IntentFlow (arXiv 2507.22134)](https://arxiv.org/abs/2507.22134) and
[DiscoverLLM (arXiv 2602.03429)](https://arxiv.org/abs/2602.03429), there's a
stable hierarchy:

| Level | Stability | Example |
|---|---|---|
| Goal | High-level, stable, often hidden | "重构 FRE 引导页交互一致性" |
| Task | Concrete unit of work | "把权限按钮放底部" |
| Action | Specific operation | "修改 LlmSetupPage.swift L42" |

User typically states a TASK explicitly but has a HIDDEN GOAL. Retrieval should
recover the goal layer because:
- Sibling tasks under same goal are highly relevant context
- Abandoned alternatives only make sense in goal context
- File edges accumulate at goal level (multiple tasks touch same files)

Two retrieval strategies:

**Strategy A — Goal extraction from current session ("inverse planning")**
- Current session has been running for some turns
- Run Tier 1 (extraction) on it → emerging goal/task signature
- Match current_goal vs historical goals
- Return matching historical goal's full subtree

Aligned with [EARL (ICML 2025)](https://arxiv.org/abs/2407.04525) — early intent
recognition from partial trajectories using inverse planning.

**Strategy B — Task → Goal reverse inference**
- User's query string matches a task (most granular level)
- Find top-K historical tasks by name+intent embedding
- Walk UP to each task's parent goal
- Return goal + sibling tasks + abandoned alts as context bundle

Aligned with [HiAgent (ACL 2025)](https://arxiv.org/abs/2408.09559) — subgoals
as memory chunks for hierarchical retrieval.

**Strategy A** for cross-session task chaining (best when current session has
signal). **Strategy B** for cold-start queries with explicit task statements.
Both routes converge on returning a goal-anchored subtree.

### Insight 3 (corollary): Why graph n-hop falls short for task context

n-hop is good for "this fact's neighbors" (knowledge network). It doesn't
respect:
- **Temporal order** — which decision came first / who supersedes whom
- **Hierarchy** — this task ⊂ this goal ⊂ this project
- **Status semantics** — active vs abandoned weighted differently for an
  "in progress" recall

Tree match preserves all three.

---

## 1.6 Hierarchy model — user goal vs agent task tree

Per [context-tree-design.md](context-tree-design.md), the tree has multiple
semantic layers, but **agent_goal and agent_task are two aspects of the same
Task node**:

```
USER GOAL  (Goal class — usually 1 per session, sometimes pivots)
  ├─ Task    (functions as agent_goal when it has subtasks)
  │    ├─ Task  (leaf = agent_task — concrete work)
  │    └─ Task  (leaf)
  └─ Task    (leaf)
```

A task's role (goal-like vs task-like) emerges from **whether it has children**:
- `Task` with subtasks → coordinator/aggregator role (= agent_goal in spirit)
- `Task` without subtasks → concrete work (= agent_task in spirit)

No separate `kind` field — same data, role is emergent.

### Why this matters for tree quality

When LLM creates new tasks, the parent-child relationship IS goal detection.
Sibling tasks under the same parent share an implicit "why" (the parent task
acts as their agent_goal).

If LLM flat-pushes everything as siblings under user_goal, the agent_goal
layer collapses → retrieval can't return coherent sub-bundles, and "all auth
work belongs together" is lost.

### Operations supporting hierarchy

- `push_subtask` for "this is a step of an existing task" (NOT push_task)
- `reparent` for "I realize this should be under that other task" — fix
  hierarchy mistakes after the fact (LLM may notice in later batches)

### User goal pivot detection

Pivot signals (LLM watches for):
- Explicit "let's do something else" / "回到上次那个问题" / "换个事情做"
- `long_gap` meta_signal AND new topic
- `cwd_changed` / `branch_changed` + unrelated content

On pivot → `push_goal` (new) + `set_active` to new task.
Without pivot → `push_task` / `push_subtask` under current goal.

### 6-dimension intent richness (per context-tree-design)

While our mutations capture structural deltas (push/affirm/reject), each
underlying intent has 6 dimensions. C's prompt covers them implicitly:

| Dimension | Mutation expression |
|---|---|
| Task operation (NEW/REFINE/EXTEND/FIX/ROLLBACK/REPLACE) | push_task vs push_subtask vs reparent vs reject_propose |
| Goal stability (NEW/STABLE/PIVOT/EXPAND) | push_goal vs no-op vs explicit pivot detection |
| Dependency | parent_id (subtask = sequential under parent's coordination) |
| Constraint change (ADD/RELAX/CHANGE) | add_constraint with ADD/RELAX/CHANGE in text |
| Scope (CURRENT/SIBLING/SUBTREE/GLOBAL) | container_id (g for global / t for current / parent for subtree) |
| Feedback type (APPROVAL/CLARIFY/CORRECT/EVALUATE) | affirm_propose / affirm_explain / reject_propose |

Future: explicit dimension annotation on each mutation could enable finer
retrieval (e.g. "show me all CONSTRAINT_CHANGE events in this goal subtree").

---

## 2. Pipeline architecture

### Two-phase: extraction (offline-ish) + retrieval (online)

```
EXTRACTION (per session sync, batch-driven):
  Adapter pre-pass:
    - parse JSONL → DialogueTurn with adapter-supplied agent_split
      {head, tail, truncated_chars} (per stage 17 dynamic rule, no LLM)
    - tool_use paths classified into tool_inputs/outputs/modifies (deterministic)
  for each batch of turns:
    1. Compose prompt: [system rules] + [hot tree subtree + cold metadata]
                        + [recent agent unit summaries] + [batch turns: head+tail]
    2. L1 LLM call → returns:
         - per-turn: { skip, human_normalized, atomic units }
         - L1 enforces ≤ 1 agent unit per turn (per-turn agent_content alignment)
    3. L2 LLM call → tree_mutations: structural ops [push_goal | push_task | affirm_propose | ...]
    4. State machine apply_mutations → new tree state
    5. Tree compacted → fed into next batch prompt
  After all batches:
    6. Tier 3.5 framing pass (per task: fact-first agent_content entities)
       — uses split-on-missing recovery when LLM omits unit_ids in large batch
    7. tree_to_entities (file/dir edges + agent_content emit + corrected_to)
       — per-turn anchored; ≥3 same-dir files folded into directory entity
    8. Entity resolver / store / embed
       — file + directory bypass embedding/disambig (path-based slug dedup)

RETRIEVAL (online, per query / per session-context-injection):
  Input: user query OR current session early turns
  Output: context bundle (goal + active task path + decisions + abandoned + files)

  Strategy A (current session has signal):
    1. Run extraction Tier 1 on current session turns → goal/task signature
    2. Subtree-match: cosine(current_goal_embed, historical_goal_embeds)
    3. Top match → return that goal's full subtree as bundle

  Strategy B (query-driven cold start):
    1. Embed query → cosine vs all task name+intent embeddings
    2. Top-K matched tasks → walk up to parent goals
    3. Return each goal's relevant subtree (with task sibling + abandoned context)

  Fallback (no good tree match):
    Drop to V2's entity embedding + n-hop expand.
```

### What's new in C vs V2-B v2

| Component | V2-B v2 | C |
|---|---|---|
| Tier 1 LLM | Per-turn skip + key extraction | Merged: tree mutations + units + segments |
| Tier 2 LLM | Per-batch atomic unit extraction | **Removed** — pure-code projection |
| State machine | Autonomous tree builder | **Mutation applier** (LLM is the author) |
| Tree role | Extraction byproduct | **Primary retrieval primitive** |
| Retrieval | Entity embedding + n-hop | **Tree-match → goal subtree bundle** |
| Goal/task distinction | Implicit | **Explicit retrieval-aware** |

---

## 3. Why atomic units stay (critical gap analysis)

Considered cutting atomic units entirely. Found 4 fatal gaps:

1. **Human acts that don't trigger tree mutations** — `ask` / `answer` / `report`
   carry no tree implication but matter for cross-session recall ("我当时报过 crash
   吗", "上次问过的 X 解决了吗"). Without atomic units these get lost.
2. **Cross-turn target resolution** — "ok" in turn 50 affirming a propose from
   turn 45 needs explicit unit_id reference (cross-batch handle).
3. **Implicit constraints embedded in flowing dialogue** — "改成 GRDB，记得不要
   raw SQL" splits into instruct + constrain. Mutation-only loses the second
   if LLM doesn't emit `add_constraint` AND `push_task` simultaneously.
4. **source_unit_id provenance** — entities, file edges, reflexion all reference
   atomic unit ids. Without units we'd need a new addressing scheme.

**Resolution**: atomic units stay, but produced by the SAME LLM call that emits
tree mutations. Tier 2 LLM disappears (becomes pure-code projection that
validates consistency + fills derived fields).

---

## 4. Tree access strategy — recency-ordered, no compaction loss

Goal: LLM always has the most recently relevant tree context, with **zero
information loss**. Cold branches stay in memory + checkpoint, surfaced via
LLM-driven expand.

### Recency tracking

Every Goal and Task carries `last_accessed_at: float` (epoch seconds). Updated
when:
- Any mutation touches the branch
- A new unit links into the task via `for_task_id`
- The task's name/id appears in agent unit text (regex match)
- LLM emits explicit `touch(branch_id)` op

State machine maintains this; persisted with tree checkpoint.

### Prompt composition: hot subtree + cold metadata

```
[Hot branches — most-recently-accessed, ≤4000 chars]
{
  "goals": [
    {"id": "g3", "intent": "OTel telemetry", "status": "in_progress",
     "active_task_id": "t52",
     "tasks": [
       {"id": "t52", "name": "Migrate to Collector", "status": "in_progress",
        "abandoned": [{"unit_id": "u401", "approach": "WPF direct Azure"}]},
       {"id": "t51", "name": "Fix Mode field", "status": "completed",
        "outcome_unit_id": "u395"}
     ]
    }
  ]
}

[Cold branches — metadata only]
- g0 "Refactor FRE"            achieved   12 tasks, last touched ~200 turns ago
- g1 "Heatmap design"          achieved   5 tasks,  3 abandoned, ~150 turns ago
- t38 "8px stroke icon attempt" abandoned   inside g1, ~180 turns ago

[Recent agent activity hint, ≤2000 chars]
- u184 [propose, hard] checkForUpdateInformation 静默 Sparkle 更新
- u192 [explain, soft] FRE 跳过按钮逻辑

To pull cold branch detail emit: {"expand_branches": ["g0", "t38"]}
```

### Two-pass per batch (only when needed)

```
Round 1: prompt with hot tree + cold metadata. LLM may emit expand_branches.
Round 2 (only if expand requested): re-issue with expanded subtrees.
```

Empirically most batches won't need round 2 (user activity locality strong —
~80% references stay within last 5-20 turns of tree).

Aligned with [PersonaTree / Inside Out (arXiv)](https://arxiv.org/abs/2511.02424)
— globally maintained tree with structural mutation ops (add/update/delete/no_op).

---

## 5. LLM contract — extraction (Tier 1)

### Per-turn fields

```json
{
  "turn_id": int,
  "skip": bool,
  "human_normalized": "str",
  "agent_segments": [
    {"activity": "propose|explain|clarify|report",
     "head": "≤200chars from start",
     "tail": "≤200chars from end",
     "mid_summary": "≤150chars or null"}
  ],
  "units": [
    {"id": "u<N>",
     "speaker": "agent|human",
     "act": "<7-act human OR 4-act agent>",
     "target": "u<M>?", "correction": "str?",
     "scope": "new_goal|new_task|subtask|null",
     "parent_id": "u<M>?",
     "for_task_id": "t<N>?",
     "text": "≤30 char hint or empty"}
  ]
}
```

### Tree mutation ops

| op | Required fields | Effect |
|---|---|---|
| `push_goal` | intent, source_unit_id | new Goal at session level |
| `push_task` | parent_id (g/t), name, source_unit_id | new Task |
| `push_subtask` | parent_id (must be t), name, source_unit_id | new subtask |
| `reparent` | task_id, new_parent_id | move task (and subtree) to fix hierarchy mistakes |
| `set_active` | task_id | switch active task pointer |
| `affirm_propose` | task_id, unit_id, outcome_summary | task complete |
| `reject_propose` | task_id, unit_id, correction_text? | task abandoned alt |
| `affirm_explain` | task_id, unit_id | add to lessons |
| `soft_complete` | task_id, propose_unit_id?, explain_unit_id? | implicit pivot acceptance |
| `add_constraint` | container_id (g/t), text, source_unit_id | hard user constraint |
| `add_term` | task_id, text | glossary term |
| `mark_abandoned` | task_id, reason | force task → abandoned |
| `touch` | branch_id | bump access timestamp only |

Top-level optional field: `expand_branches: [id,...]` — request full subtree
of cold branches; on emit, drop round-1 mutations and re-issue with augmented
context.

Aligned with [PersonaTree](https://arxiv.org/abs/2511.02424) `{add, update,
delete, no_op}` ops (we use richer vocabulary for task tree semantics).

---

## 6. State machine — `apply_mutations`

```python
class StateMachine:
    def __init__(self, initial_session=None):
        self.goals = list(initial_session.goals) if initial_session else []
        self.active_goal = None
        self.active_task = None
        self._unit_by_id = {}
        # ... counters, source maps, recency timestamps

    def apply_mutations(self, mutations: list[dict],
                         current_batch_units: list[AtomicUnit]) -> list[str]:
        """Apply LLM-proposed mutations atomically with conflict detection.
        Returns warnings for invalid ops (referenced unknown id, conflicting state)."""

    def compose_view(self, char_budget: int = 4000) -> dict:
        """Return {hot: subtree-by-recency, cold: [branch_metadata]}."""

    def expand(self, branch_ids: list[str]) -> dict:
        """Return full subtree JSON for given branch ids. Touches them."""
```

State machine is now **CRUD over the tree**, driven by LLM. Still enforces:
- Task status propagation (Goal status from task statuses)
- Soft completion housekeeping
- `acceptance` field on units after mutations applied

---

## 7. Tier 2 — pure-code projection

Mutations + segments + activity tags from Tier 1 contain the SUPERSET info for
atomic units. Tier 2 is a deterministic projection (no LLM call):

| Atomic unit field | Source |
|---|---|
| speaker | segments→agent / human_normalized→human |
| act (agent) | segment activity tag |
| act (human) | mutation type → instruct / affirm / reject / constrain |
| scope (instruct) | push_goal=new_goal / push_task=new_task / push_subtask=subtask |
| target (affirm/reject) | mutation `unit_id` field |
| correction | mutation `correction_text` |
| for_task_id (agent) | mutation `task_id` |
| text | segment head/tail concat |

Validation: cross-check (mutations → unit_ids referenced) all exist in the
units list. Conflict → log warning, skip mutation.

Cost: < 1s per session (pure Python).

---

## 8. Framing pass (Tier 3.5) — unchanged from V2-B v2

- Per-task LLM call produces fact-first purpose_title + body
- Subtype derived from `acceptance × act × size` (decision_taken / rationale_soft / etc)
- agent_content emit + Avoid: pairing for rejected
- file entities + 4 role edges (references/creates/modifies/mentioned_in)
- Low-conf entities skip embedding

The tree being LLM-authored means task→unit linkage is more semantically correct,
which improves framing input quality. No change to framing logic itself.

---

## 9. Retrieval — tree-match as first-class

### Storage of subtree-matchable indexes

Per Goal: `(goal_intent_text, goal_intent_embed, status, last_accessed_at, task_count)`
Per Task: `(task_name_text, task_intent_embed, status, parent_goal_id, ...)`

Stored as separate `goal_index` / `task_index` tables in companion-b-v3.db,
populated during sync. Embedding text = `goal.intent + key_constraint_summary`
(richer than name alone).

### Strategy A — current session inverse-planning

```python
def retrieve_via_current_session(current_turns: list[DialogueTurn]) -> Bundle:
    # Run lightweight extraction on current turns (just enough for goal sig)
    state = quick_extract_goal(current_turns[-10:])  # cheap LLM call
    if not state.goals:
        return None  # no signal yet
    current_goal_embed = embed(state.goals[-1].intent)

    # Match against historical goal_index
    candidates = sql_top_k_by_cosine(goal_index_table, current_goal_embed, k=3)
    if candidates[0].score < 0.6:
        return None  # no good match → fallback to Strategy B

    matched_goal = candidates[0]
    return load_subtree_as_bundle(matched_goal.id, depth=full)
```

### Strategy B — query-text task→goal reverse inference

```python
def retrieve_via_query(query: str) -> Bundle:
    # 1. Match query text against task index
    query_embed = embed(query)
    task_hits = sql_top_k_by_cosine(task_index_table, query_embed, k=5)

    # 2. Walk up to parent goals (deduplicate)
    goal_set = unique([t.parent_goal_id for t in task_hits])

    # 3. For each goal, return relevant subtree
    bundles = [load_subtree_as_bundle(gid, focus_task_ids=[t.id for t in task_hits if t.parent_goal_id == gid]) for gid in goal_set]

    # 4. Rank bundles by aggregate task-hit score
    return ranked(bundles)[0]  # or top-N
```

### Subtree as bundle structure

```json
{
  "goal": {"intent": "...", "status": "in_progress"},
  "active_task": {"name": "...", "outcome": "...", "constraints": [...]},
  "completed_tasks": [{"name": "...", "outcome": "..."}, ...],
  "abandoned_alternatives": [{"approach": "...", "reason": "...", "corrected_to": "..."}, ...],
  "constraints": ["...", ...],
  "files_touched": ["/abs/path", ...]
}
```

Bundle is the **atomic context unit** injected into agent. ~1-3K chars typical,
captures coherent task state.

### Fallback chain

1. Tree match (Strategy A or B) with score threshold
2. Entity embedding + n-hop file expand (V2 mechanism)
3. Empty + "no relevant history" marker

Aligned with [Semantic XPath](https://arxiv.org/abs/2403.13013) — tree-structured
memory with structural matching for conversational tasks.

---

## 10. Tier 4 — Reflexion (unchanged scope, tighter inputs)

Same as V2-B v2 but with cleaner inputs (LLM-authored tree → fewer misclassifications
for reflexion to catch). Audit purpose_title fidelity vs head/tail; check for
hallucinated entities; surface missing user constraints.

Confidence thresholds same: ≥0.7 to remove, ≥0.5 to add as soft, ≥0.7 to move.

---

## 11. Cost / time projection (re-estimate)

| Stage | V2-B v2 measured | C estimated |
|---|---|---|
| Tier 1 LLM (per-turn) | 6 min | — |
| Tier 2 LLM (per-batch) | 9 min | — |
| Merged Tier 1+2 LLM | — | **~14 min** |
| Tier 2 code projection | — | < 1s |
| Tier 3 (state machine) | < 1s | < 1s |
| Tier 4 reflexion | 1 min | 1 min |
| Tier 3.5 framing | 6 min | 6 min |
| Sync (embed + DB) | 5 min | 5 min |
| **Total extraction** | **~30 min** | **~26 min** |
| **Retrieval per query** | ~4-8s (RAG multi-round) | **~1-3s** (tree-match SQL + bundle load) |

C wins on retrieval latency too — tree-match is mostly SQL + cosine, no multi-round
LLM. RAG only triggers as fallback.

---

## 12. Risks

### Tree mutation prompt complexity

Single batch prompt now must explain:
- Tree mutation schema (12+ ops)
- Atomic unit schema (7+4 acts)
- Tree state (compacted JSON)
- Recent activity hint

Total system prompt ~2500 chars. Plus per-batch state ~4-6K. Plus turns ~20K.
Output bigger too.

**Mitigation**: SIGALRM watchdog (already proven). Split-and-retry on partial
failure. Few-shot examples in prompt.

### Tree compaction loss
Solved by recency-ordered hot/cold + on-demand expand (no information loss).

### Tighter LLM coupling
V2 separated extract/atomize/build into testable stages. C collapses two of them.

**Mitigation**: Mutation log makes LLM decisions inspectable. Atomic units still
produced — can be eval'd independently. Per-batch fail-fast + split — partial
failure isolated.

### Goal extraction quality (Strategy A)

Inverse-planning from partial trajectories is hard
([EARL](https://arxiv.org/abs/2407.04525) reports 60-70% accuracy on partial
GUI traces).

**Mitigation**: only use Strategy A when current session ≥10 turns. Confidence
threshold ≥0.6 on goal match. Fall back to Strategy B + entity embedding if
inverse-plan signal weak.

---

## 13. Implementation plan

### Phase 1 — extraction skeleton
- [ ] Define `tree_mutations` JSON schema (Pydantic)
- [ ] Write merged extraction prompt with mutation examples
- [ ] Tree compactor (`compose_view(state, char_budget)`)
- [ ] Few-shot examples for common patterns

### Phase 2 — state machine `apply_mutations`
- [ ] Refactor `state_machine.build_session` → `StateMachine.apply_mutations`
- [ ] Validation rules per op type
- [ ] End-of-batch propagation logic preserved

### Phase 3 — orchestration
- [ ] New `tree_extractor.py` replaces `preprocessor_v2.py + atomizer_v2.py`
- [ ] companion.py wired to call extractor per batch + apply mutations
- [ ] Checkpoint after each batch (tree state + units cache)

### Phase 4 — retrieval
- [ ] `goal_index` / `task_index` tables in store schema
- [ ] `retrieve_via_current_session` (Strategy A)
- [ ] `retrieve_via_query` (Strategy B)
- [ ] `load_subtree_as_bundle` formatter
- [ ] Fallback chain (tree → entity → empty)

### Phase 5 — validation
- [ ] Smoke on 3-turn + 99-turn sessions
- [ ] 695-turn full extraction run
- [ ] Retrieval benchmark: same 15 task-style queries from B v2 bench
- [ ] A/B/C three-way comparison: time + entity quality + retrieval quality

### Phase 6 — decide
- If C ships clean wins → promote to main
- Else: ship B v2, archive C learnings

Estimate: **~5-7 days** focused work.

---

## 14. Migration / coexistence

```
companion-py/             # V2-A
companion-py-b/           # V2-B v2 (current "best ship")
companion-py-b-v3/        # C (new)
  ├── claude_adapter.py    → softlink ../companion-py
  ├── copilot_api.py       → softlink ../companion-py
  ├── entity_resolver.py   → softlink ../companion-py
  ├── reflexion.py         → softlink ../companion-py
  ├── framing_pass.py      → softlink ../companion-py-b
  ├── tree_to_entities.py  → softlink ../companion-py-b
  ├── models.py            → copy + extend (last_accessed_at, mutation log)
  ├── store.py             → copy (separate companion-b-v3.db, +goal_index, +task_index)
  ├── tree_extractor.py    → NEW (merged Tier 1+2 LLM call)
  ├── state_machine.py     → adapted (apply_mutations, compose_view, expand)
  ├── tier2_projection.py  → NEW (pure-code unit projection)
  ├── retrieval.py         → NEW (Strategy A + B + bundle load)
  └── companion.py         → wires extractor + apply
```

---

## 15. Open questions

1. **Tree compaction loss tolerance**: how often do users reference >50-turn-old
   decisions? If rare, simple compaction OK. If common, on-demand expand
   needs to be very fast.
2. **Mutation conflict resolution**: when LLM suggests conflicting mutations
   (e.g. push_task to abandoned parent), silently drop or surface? Default:
   log warning + skip.
3. **Could mutation be implicit?** Instead of LLM emitting explicit mutations,
   have it output the new tree state and we diff. Pros: simpler LLM contract.
   Cons: LLM might produce invalid trees, harder to validate. Lean: explicit.
4. **First-batch tree state**: empty? Pre-seeded with parent session via
   chain? Default: empty unless explicit chain parent.
5. **How many active goals can coexist?** If user juggles 3 goals in parallel,
   Strategy A's "current goal" is ambiguous. Need top-K not top-1.
6. **Goal embedding text quality**: just `goal.intent`? Or `intent + recent
   constraints + abandoned alts`? Needs experimentation.
7. **Strategy A cost**: running quick_extract on every retrieval is 5-10s.
   Cache per-session goal sig with TTL?

---

## 16. References

Hierarchical agent memory:
- [HiAgent (ACL 2025)](https://arxiv.org/abs/2408.09559) — subgoals as memory chunks
- [Agent S (ICLR 2025)](https://arxiv.org/abs/2410.08164) — narrative + episodic hierarchical memory
- [HMT — Hierarchical Memory Tree](https://arxiv.org/abs/2603.07024) — intent → stage → action
- [ReAcTree](https://arxiv.org/abs/2511.02424) — hierarchical agent trees with episodic memory
- [Branch-and-Browse](https://arxiv.org/abs/2510.19838) — tree-structured reasoning + replay

Goal/intent distinction:
- [IntentFlow](https://arxiv.org/abs/2507.22134) — goal vs intent stability hierarchy
- [DiscoverLLM](https://arxiv.org/abs/2602.03429) — intent elicitation vs discovery
- [EARL (ICML 2025)](https://arxiv.org/abs/2407.04525) — early intent recognition / inverse planning

Tree-structured retrieval:
- [Semantic XPath](https://arxiv.org/abs/2403.13013) — XPath-style query for tree memory
- [PersonaTree](https://arxiv.org/abs/2511.02424) — tree mutation ops via RL
- [TaciTree / ImplexConv](https://arxiv.org/abs/2403.13013) — multi-level conversation tree

Multi-vector / hybrid retrieval (alternative orthogonal direction):
- [ColBERTv2](https://arxiv.org/abs/2112.01488) — late interaction MaxSim
- [Jina-ColBERT-v2](https://arxiv.org/abs/2408.16672) — multilingual

Conversation memory infrastructure:
- [Cortex](https://github.com/jina-ai/cortex) — 4-layer ACID + vector + facts + graph
- [Mem0](https://mem0.ai/blog/context-aware-chatbots-with-ai-memory) — fact extraction


## 17. Pipeline provenance — what each step learned from

Quick map of where each step's idea came from. Most steps are mash-ups
(academic core + industry adaptation + our project-specific twist).

### Extraction pipeline

| Step | Inspiration | Our adaptation |
|---|---|---|
| **Adapter `meta_signals`** (long_gap, cwd_changed, branch_changed) | Original — observation that turn-level metadata correlates with topic boundaries | Pre-computed by adapter, fed as L2 hint instead of LLM-derived |
| **L1 atomic units** (act/target/text per turn) | [Wilcock & Jokinen IWSDS 2025](https://aclanthology.org/2025.iwsds-1.0/) — 4-layer Dialogue/Turn/SemanticUnit/Entity model. ConvEngine 7-act dialogue act taxonomy. [DDA (ACL 2025)](https://aclanthology.org/2025.findings-acl/) — typed speech-act edges. | Coding-agent specific 7-act vocabulary (instruct/affirm/reject/propose/explain etc.) ; per-batch with cross-batch RECENT registry. **Stage 17**: enforce ≤ 1 agent unit per turn (per-turn agent_content); reads adapter-supplied agent_split (head/tail), no longer outputs its own segment split. |
| **L2 tree mutations** (push_goal / push_task / reparent / merge_goals / etc.) | [TME / TRIM (arxiv 2504.08525)](https://arxiv.org/abs/2504.08525) — Task Memory Engine with typed mutations. [MemTree (ICLR 2025)](https://openreview.net/forum?id=moXtEmCleY) — write-time tree ops (descend/new-leaf). | LLM emits typed mutations (vs TME's rule + cosine); strict id discipline via [NEXT_IDS] hint; richer op set (merge/reparent/abandon) |
| **State machine `apply_mutations`** | Event sourcing / CRUD applier pattern (general SE) | Validates id refs; rejects placeholder ids ("g_new" / "t_new"); records warnings for replay debugging |
| **Iterative review until convergence** | [H²R — Hierarchical Hindsight Reflection (arxiv 2509.12810)](https://arxiv.org/abs/2509.12810) — post-hoc tree refinement. [Self-Refine (arxiv 2303.17651)](https://arxiv.org/abs/2303.17651) — iterative LLM critique. | Multi-pass (1-4 rounds) until 0 mutations; H²R only does single pass in original. 6-issue boundary detection prompt (split-goal / under-segmented / wrong-goal / etc.) |
| **Reflexion (Tier 4 audit)** | [Reflexion (arxiv 2303.11366)](https://arxiv.org/abs/2303.11366) — verbal self-reflection by Shinn et al. [Zep](https://www.getzep.com/) applied it to KG claim verification. General LLM-as-Judge / [CRITIC (arxiv 2305.11738)](https://arxiv.org/abs/2305.11738) family. | Adapted to extraction self-audit (vs original "agent improvement"); per-item confidence + evidence quote + threshold-based application. Catches hallucinations review can't (it's the only step that compares tree vs raw dialogue). |
| **Framing pass** (per-task agent_content polishing) | Original — our V2-B addition for "decision-centric" extraction | LLM rewrites agent's free-text into purposeful entity titles aligned to the task that owns them. **Stage 17**: split-on-missing recovery (mirrors L1) — if LLM omits unit_ids in a large batch, recursively retry just the affected tasks at half size; fallback to head[:80] only when single-task retry still misses. |
| **Tree → entities + edges** | Standard KG construction; [A-MEM (arxiv 2502.12110)](https://arxiv.org/abs/2502.12110) Zettelkasten note linking. [GraphRAG (arxiv 2404.16130)](https://arxiv.org/abs/2404.16130) entity extraction. | task → file/directory edges (creates/modifies/references); abandoned → corrected_to LINK edges (from [AriadneMem 2603.03290](https://arxiv.org/abs/2603.03290)). **Stage 17**: per-turn anchored (each agent_content owns the file edges for its turn); ≥3 same-dir files in one turn fold into a `directory` entity edge; per-turn cap (15 edges) prevents explore-heavy turns from flooding. |
| **Entity resolver** (cross-session merge with LLM disambig) | Standard fuzzy entity resolution + [LLM-as-Judge](https://arxiv.org/abs/2306.05685) for disambiguation | Slug-exact-match fast path (files **+ directories**); LLM disambig for borderline cosine 0.5-0.85; **type filter** to skip non-file disambig (our own optimization — reduces ~95% of LLM calls in this step). Path-based entities (file/directory) bypass embedding entirely (slug = stable per-device path id). |
| **Embedding** (text-embedding-3-small via Copilot) | OpenAI standard | No fine-tuning; relies on multilingual capability for CN/EN coding sessions |

### Retrieval pipeline

| Step | Inspiration | Our adaptation |
|---|---|---|
| **Flat node recall** (cosine over goal_index ∪ task_index) | Standard dense retrieval; treats goal/task nodes equally rather than privileging goal | Reverse of GraphRAG (which goes entity → community); we go node → branch via structural overlap |
| **Natural branches** (structural overlap, not embedding cluster) | **Our own observation** — embedding cluster fails when same-name concepts span different work contexts. Inspired by **community detection** patterns in social graphs but operating on extracted task tree. | Lit nodes sharing parent OR in parent-of-other relation merge by tree topology; respects review-extracted hierarchy |
| **LLM iterative cross-branch loop** | [GraphRunner (arxiv 2507.08945)](https://arxiv.org/abs/2507.08945) — flat seed + LLM Plan + 3 traversal actions (find/fetch/common). [ReAct (arxiv 2210.03629)](https://arxiv.org/abs/2210.03629) — interleaved reasoning + action. [Youtu-GraphRAG (arxiv 2508.19855)](https://arxiv.org/abs/2508.19855) — agentic retriever with reflection. | Single LLM loop (max 4 rounds) inside retrieve_planned; LLM emits expand/drop/done across all branches; lazy field expansion |
| **Per-branch lazy expand** (evidence/files/abandoned/subtree/see_also) | Lazy-loading pattern (general SE) | Branch lean by default; LLM decides which heavy field to fetch when |
| **N candidate output** (no cross-bundle synthesis) | GraphRunner's divergent output style; user requirement (each session = independent context option for agent) | Per-branch summary in 1-2 sentences; LLM may MERGE branches when same approach used in multiple places ("Used in N places: ...") |
| **Time awareness** (last_at per node, LLM judgment) | [TimeR4 (arxiv 2401.18059 family)](https://arxiv.org/abs/2401.18059) for time-aware retrieval | Pure metadata exposure to LLM (each node carries `@YYYY-MM-DD`); no hard time filter — LLM judges staleness based on query intent |

### Storage layer

| Step | Inspiration | Our adaptation |
|---|---|---|
| **SQLite + JSON tree dump per session** | Standard embedded KG store | Per-session task_tree_json snapshot for replay/audit; goal_index/task_index extracted views with first_at/last_at temporal columns |
| **Bi-temporal `valid_from` / `invalid_from`** | [Graphiti (arxiv 2501.13956)](https://arxiv.org/abs/2501.13956) — bi-temporal KG | Adopted for `superseded_by` edge tracking; less used in V3 since branched retrieval handles temporal via `last_at` directly |
| **AriadneMem-style `corrected_to` LINK** | [AriadneMem (arxiv 2603.03290)](https://arxiv.org/abs/2603.03290) — three-action MERGE/LINK/ADD | abandoned_alternatives carries `corrected_to` text; emit edge avoid-X → corrected_to → chosen-Y |

### Adaptations original to this project

These don't directly trace to a specific paper:

- **Goal vs Task distinction tied to retrieval semantics** — most papers use "task" loosely
- **2-layer L1 + L2 split** — observation that single-call extraction overloads LLM; standard "split-LLM" pattern but applied to atomic units / tree mutations specifically
- **Iterative review prompt with `[NEXT_IDS]` hint** — engineering fix for placeholder id hallucination (LLM emits "g_new" instead of g7)
- **L2 `[TIMELINE]` block** — feed adapter-computed boundary signals to L2 to anchor topic shift detection
- **branch detection by structural concentration** — not LCA-based; just lit nodes sharing parent
- **MERGED candidates** in retrieval output when LLM detects same approach across sessions
- **Skip non-file disambig** in entity resolver (cost optimization based on observed merge rate)

### Approaches we tried but rejected

| Idea | Source | Why rejected |
|---|---|---|
| BM25 + RRF hybrid retrieval | [ColBERT family](https://arxiv.org/abs/2112.01488); standard RAG enhancement | Code identifiers live in raw dialogue not in our extracted task fields → BM25 had nothing to match in our data |
| Single-pass review | H²R original setup | Insufficient — multiple iterations naturally peel off catch-all goals |
| Mechanical cross-session bonus / same-session penalty | Naive RAG enhancement | LLM-driven judgment with `current_session_id` + `last_at` signal works better |
| Embedding cluster (semantic) for branches | Standard RAG | **Wrong**: same-name nodes in different work contexts shouldn't merge. Tree topology is more reliable signal. |
| Cross-bundle synthesis (single answer) | Standard QA pipeline | User wants N independent candidates, not one merged answer |
| LoCoMo benchmark integration | [LoCoMo (arxiv 2402.17753)](https://arxiv.org/abs/2402.17753) | Paradigm mismatch — LoCoMo tests casual-dialogue factoid recall; we're for coding work continuity |

