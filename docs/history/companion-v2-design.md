> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Yanmo Companion V2 Design

> 最终规范。每次决策变更在此同步更新。历史和推理过程见 [companion-v2-research-log.md](companion-v2-research-log.md)。
> 基础前作: [companion-spec.md](companion-spec.md) (V1 MVP)。

## 0. 场景锚定

本系统处理**单一场景**: 人监督 AI 编码 agent 完成任务的对话记录。

只有两个角色、两种动作:
- **Human**: 指挥（派任务/加约束/定规矩）+ 裁决（对 agent 方案说行/不行）
- **Agent**: 提议（方案/代码/解释）+ 问询（需要澄清时）

所有设计围绕这个场景做取舍。**不追求通用对话理解。**

---

## 1. 核心设计原则

1. 对话由任务驱动。抽取单位是"任务"、"决策"，不是"消息"
2. 模型按能力分级: 便宜模型做识别/压缩，贵模型做推理/消歧
3. 抽取端和检索端共享同一数据模型，禁止中间翻译层
4. 统一规则处理所有对话形态（研究/执行/调试/规划等），不按类型分叉
5. adapter 只做字段级清洁，内容级污染让下游处理

---

## 2. Dialogue Act 词汇表（7-act）

### Human 的 7 个 act

| act | 场景 | State machine 动作 |
|---|---|---|
| `instruct` | 派任务 / 下指令 | 按 `scope` 字段创建 goal / task / subtask |
| `constrain` | 追加约束 / 要求 | 挂到最具体的 active 容器 |
| `answer` | 回答 agent 的 clarify | 同 constrain |
| `ask` | 提问 / 质疑 | 无操作（等 agent explain + 后续 affirm）|
| `affirm(→target)` | 认可 agent 的 propose/explain | 按 target.act 分发 |
| `reject(→target, correction?)` | 否定 agent 的 propose | 记 abandoned_alternative + 可选 constraint |
| `report` | 反馈结果（"crash 了"）| 暂无操作（未来可能触发 lesson 提取）|

### Agent 的 3 个 act

| act | 场景 | 作用 |
|---|---|---|
| `propose` | 建议方案 / 代码 | affirm/reject 的指向目标 |
| `explain` | 解释原因 / 原理 | 被 affirm 后 → lesson |
| `clarify` | 反问用户 | 为下一条 human `answer` 提供上下文 |

### 原子命题拆分粒度

**原则**: 每个 unit 是"可独立被 affirm/reject 的一个 proposition"。

```
Agent 原文: "建议用 SwiftData，因为原生集成好。但 macOS 15 有 NULL 崩溃，
             可以改用 GRDB，它是 Rust wrapper 挺稳定的。"

拆分为 2 个 propose（不是 4 句）:
  P1: "用 SwiftData（原生集成好）"
  P2: "用 GRDB（规避 macOS 15 NULL 崩溃，Rust wrapper 稳定）"

User: "好的用第二个"
  → unit: {act: affirm, target: P2}
```

---

## 3. 数据模型

### 3.1 AtomicUnit

```python
@dataclass
class AtomicUnit:
    id: str                          # session-local: "u1", "u2", ...
    speaker: str                     # "agent" | "human"
    act: str                         # 7-act 之一
    text: str                        # 原句原话
    target: str | None = None        # affirm/reject 指向的 agent unit id
    correction: str | None = None    # reject 的修正文本

    # instruct 专用：scope 分类（Tier 2 atomizer 填充）
    scope: str | None = None         # "new_goal" | "new_task" | "subtask" | None
    parent_id: str | None = None     # subtask 指向父 task 的 source instruct unit id

    # agent propose 专用：归属哪个 task
    for_task_id: str | None = None   # 指向 instruct unit id
```

### 3.2 DialogueTurn

```python
@dataclass
class DialogueTurn:
    turn_id: int
    timestamp: str
    agent_raw: str                   # 完整 agent 内容（不截断）
    human_raw: str                   # 用户原文

    # adapter-level 元信号（claude_adapter 计算填充）
    # 用作 Tier 1 / Tier 2 的 topic-shift hint，不参与 LLM 输出
    meta_signals: list[str] = []     # ["long_gap:4h", "cwd_changed:foo", "branch_changed:bar"]

    # Tier 1 输出
    skip: bool = False
    agent_key_points: list[str] = []
    human_normalized: str = ""

    # Tier 2 输出
    units: list[AtomicUnit] = []
```

**meta_signals 由 adapter 在解析时计算**：跟踪前一 turn 的 timestamp / cwd / gitBranch，差异超阈值产生信号:
- `long_gap:Nh` 或 `long_gap:Nd` —— 时间间隔 ≥ 1 小时
- `cwd_changed:<dir>` —— 工作目录切换
- `branch_changed:<name>` —— git 分支切换

Tier 1 prompt 提示参考这些信号做 skip / 压缩判断；Tier 2 prompt 提示这些信号是 `scope=new_goal` 的强 hint。

### 3.3 Task 层次结构（Layer 2）

```python
@dataclass
class Goal:
    id: str
    intent: str                      # 高层目的: "诊断数据丢失原因"
    status: str                      # pending | in_progress | achieved | abandoned
    constraints: list[str]           # goal-level（可继承给 task）
    tasks: list[Task]                # 服务该 goal 的任务
    source_unit_id: str              # 触发 goal 创建的 instruct unit id
    linked_unit_ids: list[str]       # 所有归属此 goal 的 unit

@dataclass
class Task:
    id: str
    name: str                        # 具体步骤: "从 git log 还原历史"
    parent_id: str                   # Goal.id 或 Task.id
    parent_type: str                 # "goal" | "task"
    status: str                      # pending | in_progress | blocked | completed | abandoned
    constraints: list[str]
    outcome: str | None
    abandoned_alternatives: list[dict]   # [{approach, reason}]
    lessons: list[str]
    terms: list[str]
    subtasks: list[Task]
    linked_unit_ids: list[str]

@dataclass
class Session:
    session_id: str
    project_path: str
    display_name: str
    goals: list[Goal]
    turns: list[DialogueTurn]
```

### 3.4 Status Lifecycle

| status | 触发 |
|---|---|
| `pending` | 容器创建但尚无工作（subtask 预置等） |
| `in_progress` | 首个 propose/explain 出现或首个 unit 关联 |
| `blocked` | agent clarify 发出后 human 尚未 answer |
| `completed` | affirm(propose) 触发 |
| `abandoned` | 所有 propose 都被 reject 且无 correction；或显式放弃 |

Goal 状态推导:
- all tasks completed → `achieved`
- any in_progress → `in_progress`
- all abandoned / 显式放弃 → `abandoned`

### 3.5 容器区别

- **Layer 1 (Dialogue)**: DialogueTurn + AtomicUnit — 对话结构
- **Layer 2 (Task)**: Goal + Task + Subtask — 目标层次
- **Layer 3 (Knowledge)**: constraint / context / lesson / term — 知识产出（从 Layer 2 派生）

---

## 4. 五级处理管线

### 4.1 模型分工

| 用途 | 模型 | 调用方式 |
|---|---|---|
| 识别 / 压缩 / 规范化 | **Gemini 3 Flash Preview**（便宜） | 每 turn 独立（batch 内）|
| 推理 / 消歧 / 归属 | **Gemini 3 Flash Preview** (1M context, 64K output) | batch 内 prior_units registry 跨批引用 |
| 向量相似度 | text-embedding-3-small | 每 entity 一次 |

历史: 早期 Tier 2 用 gpt-5.4 (单次全 session 200k chars)，但 64K output 不够。切到 Flash 1M context + batching 后两者都能处理大档。

### 4.2 Tier 1 — 便宜模型每 turn 预处理

**输入**: 单个 DialogueTurn（agent_raw + human_raw）
**输出**: 填 `skip` / `agent_key_points` / `human_normalized`

判断与压缩三件事:
1. skip 判断（仅两边都无决策才 skip）
2. agent_key_points 抽取（决策相关句，原句保留，宁多勿漏）
3. human_normalized 补全（只还原指代词，禁止添加 agent 内容）

**Prompt 为英文 + 双语示例**。目标: cov ≥90%, purity ≥85%, halluc ≤10%, false-skip ≤15%.

**Batching**（处理大档必需）:
- 按 char 预算 + turn 数双重 cap 切批: `BATCH_MAX_INPUT_CHARS=30000`, `BATCH_MAX_TURNS=50`
- 单 turn 超 30k 字独占一批（极大粘贴块情况）
- 每批一次 LLM 调用，输出 `{"turns": [{turn_id, skip, agent_key_points, human_normalized}, ...]}`
- 失败处理:
  - LLM/parse 失败 → 整批 retry 一次
  - 部分 turn 缺失 → retry 缺失 subset
  - 仍失败 → per-turn fallback（保正确性，牺牲速度）
- 695-turn session: 19 batches × ~30s = ~10 min（vs 串行 35 min）

### 4.3 Tier 2 — 贵模型整 session 原子化

**输入**: list[DialogueTurn] with Tier 1 已填
**输出**: 每 turn 填 `units: list[AtomicUnit]`，含 act + target + scope + parent_id + for_task_id

**Batching**（与 Tier 1 同结构）:
- `ATOMIZER_MAX_INPUT_CHARS=25000`（留余地给 prior_units registry）
- `ATOMIZER_MAX_TURNS=50`
- 每批 prompt 包含**两段**:
  1. `Prior units registry`: 之前所有 batch 产出的 unit 摘要（id + speaker + act + 80字预览，取最近 60 个），供 cross-batch `target` / `parent_id` / `for_task_id` 引用
  2. `New turns`: 本批待原子化 turn
- 全 session 单调递增 unit id (`u1...u2100+`)，跨 batch 不冲突
- 单一模型用 Flash（gemini-3-flash-preview, 1M context, 64K output）替代 GPT-5.4
- 695-turn 实测: 14 batches × ~50s = ~12 min

单次 LLM 调用处理整 session（GPT-5.4 可吃 15k+ 输入）。

**scope 分类规则**:
- `new_goal`: 新的高层次目的，与 active goal 无关
- `new_task`: 服务于 active goal 的具体步骤
- `subtask`: 当前 active task 的更细分解
- `None`: atomizer 判断不确定时置空，state machine 走默认规则

**归属规则**:
- 每个 agent propose 标 `for_task_id`（指向其 turn 时 active 的 task instruct）
- human reject.correction → 作为被 reject propose 的 reason

目标: act accuracy ≥90%, target ≥85%, granularity ≥80%, coverage ≥90%, **scope 分类 ≥85%**.

### 4.4 Tier 3 — 状态机构建 Goal/Task 树（纯代码）

**输入**: list[DialogueTurn] with Tier 2 已填
**输出**: Session with goals / tasks / subtasks 填好

状态机规则（按 unit 顺序）:

```
instruct + scope=new_goal      → session.push_goal(intent, source=unit.id)
instruct + scope=new_task      → active_goal.push_task(name, parent=active_goal)
instruct + scope=subtask       → 根据 parent_id 找到父 task, push_subtask
instruct + scope=None          → 有 active_goal 时作为 new_task, 无则作为 new_goal

constrain / answer             → 挂到最具体的 active 容器（task > goal）

affirm(target.act=propose)     → find task via target.for_task_id or active_task
                                  → task.outcome = target.text, status=completed
                                  → 触发 goal status 重算
affirm(target.act=explain)     → 对应 task.lessons.append(target.text)
affirm(target.act=clarify)     → 无操作（下一条 human answer 会变 constrain）

reject(target.act=propose)     → 对应 task.abandoned_alternatives.append({approach, reason, corrected_to?})
                                  → 若有 correction: task.constraints.append(correction)
                                  → tree_to_entities 把 corrected_to 编码为 `corrected_to` 边
                                    （avoid-X --corrected_to--> use-Y），保留演化轨迹

ask / report / propose / explain / clarify 单独出现 → 等待响应（状态机不操作）
但 propose / explain 跟踪 last unclaimed per task，用于软完成

**Soft completion (隐式接受)**: 当 human pivot 到新 task（无显式 affirm/reject）时:
- 该 task 的 last unclaimed propose → outcome (outcome_soft=True, confidence=0.65)
- 该 task 的 last unclaimed explain → soft_lessons (confidence=0.55)
- 解决探索型 session "agent 说了堆，user 不 affirm 直接 pivot" 的信号丢失
```

Goal status 重算: all tasks completed → achieved, any in_progress → in_progress, all abandoned → abandoned.

**边界处理**:
- target 找不到或类型不符 → 安全跳过（可能 correction 仍可挂）
- subtask parent_id 找不到 → 回退为 new_task under active_goal
- 从未出现 new_goal → 第一个 instruct 自动成为默认 goal

### 4.5 Tier 4 — Reflexion 自审（可选 / 贵模型）

**输入**: 原压缩对话 + Tier 3 产出的实体集合
**输出**: 修正 JSON { hallucinations, missing, misassignments }，每项含 `confidence (0-1) + evidence quote`

LLM 审查（含自评 confidence）:
1. 哪些实体在对话里无依据？（幻觉，confidence + evidence）
2. 哪些用户明示的 constraint/lesson 漏了？（缺失）
3. 哪些 affirm/reject 的 target_ref 指错了？（错配）

应用阈值:
- 幻觉：confidence ≥ 0.7 才删（避免误杀）
- 缺失：confidence ≥ 0.5 才补，且只入 soft_constraints / soft_lessons（lower confidence in entities）
- 错配：confidence ≥ 0.7 才移动

### 4.6 Tier 5 — 嵌入实体消解 & 检索

沿用 V1 entity_resolver：0.85 auto-merge / 0.5 LLM disambig / <0.5 new.
检索走 agentic RAG (rag.py)，接收 Goal/Task 结构额外作为 context 标签（不影响核心流程）。

---

## 5. Bi-Temporal Schema
ALTER TABLE nodes ADD COLUMN created_at TEXT;    -- 系统摄入时间
ALTER TABLE nodes ADD COLUMN expired_at TEXT;    -- 被新知识取代时的摄入时间
-- 保留 valid_from / invalid_from 为真实世界有效区间
```

矛盾处理: 不 UPDATE 老节点，而是:
- 老节点: `invalid_from = now, expired_at = now`
- 新节点: `created_at = now`
- 加 `superseded_by` 边

支持 point-in-time 查询: "2026-05-01 时系统认为什么有效？"

---

## 6. Confidence

```sql
ALTER TABLE nodes ADD COLUMN confidence REAL DEFAULT 0.5;
```

赋值规则（state machine 写入）:

| 来源 | confidence |
|---|---|
| affirm(propose) → constraint/context | 0.95 |
| human instruct | 0.90 |
| human constrain | 0.90 |
| reject → abandoned_alternative | 0.90 |
| reject.correction → constraint | 0.85 |
| affirm(explain) → lesson | 0.85 |
| **soft outcome (implicit pivot)** | **0.65** |
| **soft lesson (implicit explain promo)** | **0.55** |
| **reflexion-added soft constraint** | **0.55** |
| Reflexion 标记可疑（保留但降权）| 0.3 |

检索按 confidence 降序 + 阈值过滤。UI 低分灰色显示。

---

## 7. 增量处理

```python
processing_state:
  session_id PRIMARY KEY
  last_processed_uuid TEXT        # 最后处理过的 message uuid
  last_turn_count INTEGER
  task_tree_json TEXT             # Tier 3 snapshot 用于断点续传
```

增量判断:
1. 扫 JSONL 找到 `last_processed_uuid` 对应行号
2. 之后的行为新增 turn
3. 只对新增 turn 跑 Tier 1 + Tier 2
4. 状态机从 task_tree_json 续跑新 units

跨文件 DAG（/resume, /fork）: V2 阶段已实现。`claude_adapter.discover_sessions()` 解析每个 session 的
`type:"summary"` 条目，通过 `leafUuid → uuid → session_id` 映射建立 chain。
sync 按 chain root → descendants 顺序处理，state machine 用 `initial_session` 参数从父 session 的
task tree 续跑（goals/active_task/source-id 全继承），保证跨文件对话的任务延续性。
Cache 仍按单 session 存。处理后将 v2_session 完整 dump 进 `processing_state.task_tree_json` 供子 session 加载。

---

## 8. 模块结构

```
companion-py/
├── companion.py           # CLI 入口
├── models.py              # DialogueTurn / AtomicUnit / Goal / Task / Session
├── claude_adapter.py      # JSONL → list[DialogueTurn]（字段级过滤）
├── preprocessor.py        # Tier 1 cheap model
├── atomizer.py            # Tier 2 smart model
├── state_machine.py       # Tier 3 纯代码
├── reflexion.py           # Tier 4 自审
├── tree_to_entities.py    # Task 树 → list[Entity]
├── entity_resolver.py     # 实体消解
├── store.py               # SQLite + bi-temporal + confidence
├── copilot_api.py         # 模型切换 + retry
├── rag.py                 # 检索 agentic RAG
├── eval_tier1.py          # Tier 1 评估 + audit
├── eval_tier2.py          # Tier 2 评估 + audit
├── eval_tier3.py          # Tier 3 结构审查
├── eval_tier4.py          # Reflexion 评估
├── eval_e2e.py            # 端到端 golden set 对比
└── eval_dialogue_model.py # 7-act taxonomy 覆盖审查
```

---

## 9. CLI 命令

| 命令 | 作用 |
|---|---|
| `sync` | 全管线: adapter → Tier1 → Tier2 → Tier3 → Tier4 → entity_resolve |
| `preprocess <sid> [--limit N]` | Tier 1 预览 |
| `atomize <sid>` | Tier 1+2 |
| `tree <sid> [--save]` | Tier 1+2+3（任务树）|
| `reflexion <sid>` | 在已存任务树上单独跑 Tier 4 |
| `query-at <date>` | bi-temporal 查某时间点知识图 |
| `search <query> [--project] [--session]` | agentic RAG 检索 |
| `eval-tier1 <sid> [--audit] [--model]` | Tier 1 评估 |
| `eval-tier2 <sid> [--audit]` | Tier 2 评估 |
| `eval-tier3 <sid>` | Tier 3 结构评估 |
| `eval-tier4 <sid>` | Reflexion 评估（diff 前后）|
| `eval-e2e <sid> --golden PATH` | 端到端 F1 对比 |
| `eval-dialogue-model <sid>` | 7-act 覆盖率验证 |
| `stats` / `sessions` / `parse` / `match` / `inspect` / `dump` | 工具类 |

---

## 10. 成本估算

对一个 100 turn 的典型 session:

| 组件 | 调用构成 | 估算成本 |
|---|---|---|
| Tier 1 | 100× Flash | ~$0.01 |
| Tier 2 | 1× GPT-5.4 (~15k in/3k out) | ~$0.15 |
| Tier 3 | 0（纯代码） | $0 |
| Tier 4 | 1× GPT-5.4（audit full session）| ~$0.20 |
| Entity 消解 | ~30× cheap disambig + embeddings | ~$0.05 |
| **Total sync** | | **~$0.40/session** |

对比 V1 (~$3/session)，降到 **1/7** 成本。

单次 eval 回归（一 session 全 tier）: ~$3.5。Golden set 3 session 完整回归: ~$10.

---

## 11. 评估方法

评估分三个视角: **Tier 级**（每个管线步骤内部正确）/ **Layer 级**（跨 tier 的结构产物正确）/ **端到端**（最终知识产出对齐人工标注）。每视角有对应的 `eval-*` 命令和达标阈值。

### 11.A 三视角对照

| 视角 | 评估对象 | 目的 | 命令 |
|---|---|---|---|
| Tier | 单步算法输出 | 验证"这步做对了吗" | `eval-tierN [--audit]` |
| Layer | 跨 tier 积累的数据结构 | 验证"整层结构合理吗" | `eval-layerN` |
| 端到端 | 最终 entities | 验证"和人工期望一致吗" | `eval-e2e` |

### 11.1 Tier 1（preprocessor）

**量化**: skip ratio / compression ratio / latency / cost

**Smart-model audit** (`eval-tier1 --audit`):
- coverage ≥ 90%（agent 决策点捕获率）
- purity ≥ 85%（非决策内容未被抽）
- hallucination ≤ 10%（human_normalized 无编造）
- false_skip ≤ 15%（skip 的 turn 真无决策）

### 11.2 Tier 2（atomizer）

**Smart-model audit** (`eval-tier2`):
- act accuracy ≥ 90%（act 标签正确）
- target_ref ≥ 85%（affirm/reject 指对 agent unit）
- granularity ≥ 80%（atomic，一个 unit 一个独立 propose）
- coverage ≥ 90%（每个 agent_key_point 至少产出 1 unit）
- scope classification ≥ 85%（new_goal/new_task/subtask 判断）
- parent_id ≥ 90%（subtask 指对父 task）
- for_task_id ≥ 85%（agent propose 归对 task）

### 11.3 Tier 3（state machine）

**量化**: 覆盖所有转移规则 + 边界 case（循环 reject / 跨 turn target / missing parent）

**Smart-model 结构审查** (`eval-tier3`):
- Goal count / session 合理（多数 1-3，过多说明 scope 判错）
- Tasks per Goal 分布（执行型 3-8，研究型 2-5）
- Subtask 深度（>3 罕见）
- Parent 链完整性（每 task 能追溯到 goal）
- Status 合理性（不应有大量悬挂 in_progress 或 blocked）

### 11.4 Tier 4（reflexion）

- 幻觉检出 precision ≥ 80%
- 缺失 recall ≥ 50%
- 修正后误杀率 ≤ 10%

### 11.5 Layer 1（对话结构）

**eval-layer1**（含 `eval-dialogue-model`）:
- 7-act taxonomy fit rate ≥ 95%（真实 turn 都能映射到 7 act，无 none-fit）
- Unit id 唯一性 + 引用完整（每个 target / parent_id / for_task_id 能解析）
- Turn 覆盖率（非 skip 的 turn 都至少产出 1 unit）

### 11.6 Layer 2（任务结构）

**eval-layer2**:
- 树形拓扑合法性: 无环 / 所有 Task 有 parent / Subtask 深度有界
- 归属一致性: 每个 AtomicUnit 能找到它所属的 Task/Goal
- Status 单调性: 状态迁移符合 pending→in_progress→{completed|abandoned} 链（不回退）
- Session-level coherence: Goal 间是否真的独立（避免把应合并的 Goal 拆多了）

### 11.7 Layer 3（知识产出）

**eval-layer3**:
- 类型分布合理（constraint/context/lesson/term 占比在预期区间）
- 重复去重率（同 project 下 title 高度相似的 entity 合并率）
- 可追溯性: 每个 entity 能映射回 Task + AtomicUnit 源（provenance 无断链）
- Confidence 分布合理（主流 0.85-0.95，低分 <0.5 占比 <10%）

### 11.8 跨 Layer 一致性

**eval-consistency**（无 LLM，纯代码审查）:
- L1 → L2: 所有 non-skip turn 的 instruct unit 都参与了某个 Goal 或 Task 的创建
- L2 → L3: 所有 completed Task 产出了至少 1 个 entity；所有 abandoned_alternatives 产出了 constraint
- L3 → L1: 每个 entity 的 source_unit_id 能在原 AtomicUnit 列表中找到

### 11.9 端到端

**Golden set**: 3-5 session 人工标注应产出的实体集合（存 `docs/ac/golden/<sid>.json`）。

**自动回归** (`eval-e2e`):
- precision = 产出 ∩ golden / 产出
- recall = 产出 ∩ golden / golden
- F1 目标: ≥ 0.7
- 实体匹配用 embedding (cos > 0.8) + LLM 判同 fallback

### 11.10 回归机制

每 tier prompt / 代码改动前后:
1. 跑对应 `eval-tierN`
2. 记录到 `docs/ac/eval-logs/tier<N>-<sid>-<version>.json`
3. 指标退化 → rollback

Layer / 端到端回归频率: 每个 Tier 改完、major feature 改完。

每次 commit 结构性改动（模块接口、数据模型、prompt）都至少跑对应 Tier eval + 下游一个 Layer eval。

---

## 12. 已知风险

1. **scope 分类边界模糊**（new_task vs subtask）
   - 缓解: eval-tier2 新增 audit，迭代 prompt 加示例

2. **多 Goal 混合 session**
   - 用户中途切换 topic → atomizer 判 new_goal
   - 当前设计支持但缺端到端验证

3. **Task 状态悬挂**
   - 现实 session 常结束时仍有 in_progress task
   - 缓解: session 结束自动转为 "abandoned by session end" 或标 suspended

4. **Reflexion 自审成本**
   - 1 次/session Opus/GPT-5 调用 ~$0.5
   - 默认可关（仅 --reflexion 启用）

5. **跨 session 实体消解的 Goal/Task 对接**
   - V2 新增 Goal/Task 层后，跨 session 的 Goal 如何合并？
   - 暂定: Goal 按 title + project 合并，Task 按 name + project 合并，其他沿 V1 entity_resolver

6. **agent 复述的 propose 归属**
   - agent 在 explain 中重申之前的 propose，不应产生重复 unit
   - Tier 2 prompt 加 "不重复抽取已出现的 propose" 规则

---

## 13. 与 V1 差异

| 组件 | V1 | V2 |
|---|---|---|
| Session 解析 | 过滤 trivial、截断 agent_context 200 字 | 完整保留，仅字段级过滤 |
| 意图分类 | 6 类 mixed 意图 | 7-act dialogue + 状态机 |
| 抽取粒度 | 扁平消息级 | 原子对话单元 |
| 任务结构 | 扁平 tasks | **Goal / Task / Subtask 三层** |
| affirm/reject | 无概念 | 有 target_ref 精确指向 |
| 模型使用 | 全 Opus | Flash 预处理 + GPT-5 推理 |
| 幻觉防护 | 无 | Reflexion 自审 |
| Bi-temporal | 2 字段 | 4 字段 |
| Confidence | 无 | 0-1 浮点 |
| 实体类型 | decision/topic/problem/solution | constraint/context/lesson/term |
| 成本 | ~$3/100turn | ~$0.4/100turn |

---

## 14. 验证用测试集

准备不同场景的 session 做回归测试:

| 类型 | 特征 | 重点验证 |
|---|---|---|
| 长方案讨论 | 多 affirm/reject 循环 | target_ref 准确率、scope 分类 |
| 代码密集 | agent 贴大量代码 | Tier 1 压缩质量 |
| 大粘贴块 | 用户贴日志/错误 | Tier 1 skip 判断 |
| 快速迭代 | 大量短 turn / "好的" 确认 | affirm 解析 |
| 多任务切换 | 中途换 topic | scope=new_goal 判断 |
| 调试型 | 诊断→假设→修复 | 任务树分支结构 |
| 纯 Q&A | 无明确任务 | 容忍空 goals |

每次 Tier 1/2/3 prompt 或代码改动，至少覆盖 3 个规模 × 3 种类型.

---

## 附: 数据流总览

```
.jsonl (Claude Code)
  │
  ▼ claude_adapter.parse_turns()                 [字段级过滤，输出 raw]
list[DialogueTurn]
  │
  ▼ preprocessor.apply_tier1() [×N turns]         [Flash, per-turn]
list[DialogueTurn] with Tier 1 fields
  │
  ▼ atomizer.atomize_session()                    [GPT-5.4, one-shot]
list[DialogueTurn] with AtomicUnit[] + scope/parent/for_task
  │
  ▼ state_machine.build_tree()                    [纯代码]
Session with goals[] / tasks[] / subtasks[]
  │
  ▼ (optional) reflexion.review()                 [GPT-5.4, self-audit]
Session with hallucinations removed, missing added
  │
  ▼ tree_to_entities.convert()                    [纯代码]
list[Entity] (constraint/context/lesson/term)
  │
  ▼ entity_resolver.resolve()                     [cheap + embedding]
list[Entity] (merged to global graph)
  │
  ▼ store.upsert() + rag.query()                  [SQLite + vector search]
Knowledge graph / Retrieval
```
