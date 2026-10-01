> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Yanmo Companion V2-B Design — Decision-Centric, Purpose-Framed

> 与 [companion-v2-design.md](companion-v2-design.md)（V2-A，eager extraction）并行的 fork 实验。
> 共享 V2-A 的对话场景锚定 / 7-act 词汇 / Goal-Task 层次 / bi-temporal schema / entity resolver / agentic RAG。
> 差异集中在 **Tier 1 / Tier 2 / 新增 Tier 3.5 framing pass / tree_to_entities** 四处。
> 历史推理见 [companion-v2-research-log.md](companion-v2-research-log.md) 阶段 11。

## 0. 立场

V2-A 假设: **agent 也输出可独立检索的知识**，所以每条 propose / explain 细抽 → atomize → 落 entity。entity title/embedding 反映 agent 内容罗列。

V2-B 假设: **检索 query 是 user 语言（"为什么不用 SwiftData"）**，匹配应基于 user 视角。Agent 内容仍然成 entity（不做钻取、不要二次取原文），但 entity 的 **title / content / embedding 都按"用户的用途"框定**，而不是按 agent 自述内容罗列。

研究支撑（[Contextual Retriever, EMNLP 2025](https://aclanthology.org/2025.emnlp-main.602.pdf)）：intent-guided embedding 检索准确率 91.9% vs 内容 embedding 64.2%。

V2-B 不否定 V2-A，是另一种取舍。两个变体并存 → 跑同 query benchmark → 决定主干方向。

---

## 1. 范围与不变量

### 共享 V2-A（不修改）

| 模块 | 复用方式 |
|---|---|
| `claude_adapter.py` | 软链：tool_use path 提取、recent_paths_context、device_id |
| `copilot_api.py` | 软链 |
| `entity_resolver.py` | 软链（A 已修 type-gate、None-safe，B 直接受益） |
| `reflexion.py` | 软链（审查面会扩展，见 §6） |
| `models.py` 中 Goal/Session 主结构 | 复用；字段集是超集，新字段在 §2 |
| `state_machine.py` (Tier 3) | 复用核心逻辑；唯一改动是 task 上不再写压扁字符串，改写 unit_id 引用 |
| `store.py` schema | 复用 nodes/edges 主表；不加新表 |
| `rag.py` (agentic RAG) | 复用；不加 drill-down 工具 |

### B 自有模块

- `preprocessor.py` — Tier 1 改写：head+tail 保留 + activity tag
- `atomizer.py` — Tier 2 改写：人侧密、机侧粗（但允许 N propose）
- `framing_pass.py` — **新增** Tier 3.5：把 agent unit 按 user purpose 框定
- `tree_to_entities.py` — emit 矩阵改写
- `companion.py` — pipeline 串联

### 不做的事（明确排除）

- 不做检索时钻取 / 不存原文回链 / 不加 evidence 表
- 不做 UI / 不写 markdown 报告生成
- 不引入新模型或新 API

---

## 2. 数据模型差异

### 2.1 DialogueTurn 字段补充

```python
@dataclass
class DialogueTurn:
    # ...V2-A 字段全保留，但 agent_key_points 字段 B 不写不读...
    agent_segments: list[dict] = []
    # 每条 = {
    #   "activity": "propose" | "explain" | "clarify" | "report",
    #   "head": str,            # 前 N 字（见 §3.2）
    #   "tail": str,            # 后 N 字
    #   "mid_summary": str | None,  # 中间段 LLM 摘要（仅在原文 > 600 字时生成）
    # }
```

### 2.2 AtomicUnit 字段补充

```python
@dataclass
class AtomicUnit:
    # ...V2-A 字段全保留...
    acceptance: str | None = None    # "hard" | "soft" | "rejected" | "unclaimed"
    purpose_title: str | None = None # framing pass 输出（见 §4）
    purpose_body: str | None = None
    framing_failed: bool = False     # 兜底标记
```

### 2.3 Task 字段重构

V2-A 的 task 把决策结果压扁为字符串：
```python
outcome: str | None
lessons: list[str]
abandoned_alternatives: list[{approach, reason, corrected_to?}]
```

V2-B 改为 unit_id 引用，原文不折叠：
```python
@dataclass
class Task:
    # ...其他字段不变...
    outcome_unit_id: str | None = None
    lesson_unit_ids: list[str] = []           # 含 hard 与 soft，由 unit.acceptance 区分
    abandoned_unit_ids: list[dict] = []       # [{unit_id, correction_unit_id?}]
```

state_machine 的逻辑不变，只是把"取 target.text 写进 outcome"改为"记 target.id 进 outcome_unit_id"。

### 2.4 store schema

不变。不加新表。agent_content entity 用现有 `nodes` 表，type='agent_content'，subtype 走 metadata。

---

## 3. Tier 1 — head/tail 保留预处理

### 3.1 输出契约

```json
{
  "turn_id": 42,
  "skip": false,
  "human_normalized": "use GRDB instead of SwiftData because of NULL crash",
  "agent_segments": [
    {"activity": "propose", "head": "...", "tail": "...", "mid_summary": null},
    {"activity": "explain", "head": "...", "tail": "...", "mid_summary": "<150 字>"}
  ]
}
```

### 3.2 head/tail 长度规则

依据 [Lost in the Middle (Liu 2023)](https://arxiv.org/abs/2307.03172) 的 U 曲线：信息在头尾命中率最高，中间衰减。

- 单 segment 长度 L:
  - L ≤ 200 字：full = head（不切）
  - 200 < L ≤ 600 字：head = 前 max(100, 0.2L)，tail = 后 max(100, 0.2L)，无 mid_summary
  - L > 600 字：head = 前 max(100, 0.2L)，tail = 后 max(100, 0.2L)，mid_summary = LLM 对中间段产 ≤150 字摘要
- head/tail 总长上限 600（含 mid_summary 后整段 ≤ 750）

**绝不直接截断单字/单句**：head/tail 切到下一个句号边界（`。.！!？?\n`）。

### 3.3 skip 规则

与 V2-A 同。但 B 中 agent 侧"有动作"门槛更高:
- 仅 propose / explain / clarify / report 之一才算（report 也算，因为可能承载关键事实如"测试通过"）
- 纯堆栈 / 复述 / 寒暄 不算 → 仅靠 human 侧判断 skip

### 3.4 单 turn 极端长度

实测有 1 turn = 41K 字（用户粘贴堆栈）。这种 turn:
- 输入端：Tier 1 batching 已让其独占一批
- agent_segments 端：head+tail 策略**特别有价值**——长粘贴中间多为日志/堆栈，head+tail 才是决策信号

### 3.5 Batching

与 V2-A 同（30k chars / 50 turns）。输出体积约比 V2-A 小 20%（agent_segments 比 agent_key_points 略紧凑）。

### 3.6 目标

- coverage（human normalized 完整性）≥ 92%
- skip precision ≤ 5%
- head/tail 不切断单字（自动测试断言）
- mid_summary 准确率（不引入新事实）≥ 90%（reflexion 抽审）

---

## 4. Tier 2 — 不对称原子化

### 4.1 原则

- **Human 侧密**：每个 proposition 一个 unit（与 V2-A 同）
- **Agent 侧粗**：每 turn 的 agent 侧产生 ≤ N propose + ≤ 1 explain + ≤ 1 clarify + ≤ 1 report
  - N 不固定：当 agent 实际给互斥备选（"用 A，但其实 B 更好"）时允许多 propose，**为了让后续 user "用第二个"有 target 可指**
  - explain / clarify / report **每 turn 至多 1 条**：这些天然汇总
- 每个 agent unit 的 `text` 字段 = 该 segment 的 `head + "\n[...]\n" + (mid_summary or "") + "\n[...]\n" + tail`，**不再 LLM 改写为 proposition**
- target / scope / for_task_id 标法不变

### 4.2 短回复处理（防 V2-A 痛点）

V2-A 实测出现 user "1" / "好的" 被独立原子化 → 进 entity 池污染。B 强制规则：

> 当 human 侧文本 ≤ 4 字符（去空白后）且语义上是数字/选项/确认词时，**必须** 把该 unit 标为 `act=affirm` + `target=最近 unclaimed propose`，**禁止**单独成 instruct/constrain unit。

加双语示例进 prompt。

### 4.3 Batching

与 V2-A 同结构。prior_units registry 不变。

### 4.4 目标

- act accuracy ≥ 90%
- target accuracy ≥ 85%
- scope accuracy ≥ 85%
- **agent unit 数 / turn ≤ 2.5**（A 实测 3.0，目标降）
- 短回复独立化率 ≤ 5%

---

## 5. Tier 3 — 状态机（沿用，字段引用化）

### 5.1 逻辑

完全沿用 V2-A，但写回 task 的方式从字符串改为 unit_id：

```
affirm(target.act=propose)     → task.outcome_unit_id = target.id
                                  target.acceptance = "hard"
                                  task.status = completed
affirm(target.act=explain)     → task.lesson_unit_ids.append(target.id)
                                  target.acceptance = "hard"
reject(target.act=propose)     → task.abandoned_unit_ids.append({unit_id: target.id, correction_unit_id: ?})
                                  target.acceptance = "rejected"
                                  若 correction → 仍 emit user constraint
soft completion (pivot 触发)   → 同 V2-A，标 acceptance="soft"
unclaimed (turn 结束未触发)    → acceptance="unclaimed"，confidence ↓
```

### 5.2 corrected_to 关系

V2-A 在 reject + correction 时直接 emit edge：avoid-X --corrected_to--> use-Y（按 title 字符串）。
B 改为按 unit_id：`abandoned_unit_id --corrected_to--> correction_target_unit_id`。emit 在 tree_to_entities 阶段做，确保两端 entity 都已生成。

---

## 6. Tier 3.5 — 用途框定 Pass（B 新增）

### 6.1 输入（按 task 收集）

```
task.name (= triggering instruct text, ≤120 字)
goal.intent
agent units linked to this task: [{
  unit_id, act, head, tail, mid_summary, acceptance, target_unit_text?
}]
adjacent user units (constrain/affirm/reject text，截 80 字)
```

### 6.2 LLM 调用（batched 5-8 task / call）

研究依据：[Batch Prompting (arXiv 2301.08721)](https://arxiv.org/abs/2301.08721) 显示 6 sample/batch 节省 ~5× 成本。

- 每 batch ≤ 8K 字符输入
- 单 task 输入超 4K 字符 → 独占一批
- 失败 → 整批 retry 一次 → 再失败走 per-task fallback（§6.4）

### 6.3 输出契约

```json
{
  "framings": [
    {
      "unit_id": "u47",
      "purpose_title": "数据库选型方案: SwiftData vs GRDB",
      "purpose_body": "<150-300 字 user 视角概括，可引用原文片段，不引入新事实>",
      "subtype": "decision_taken"
    }
  ]
}
```

`subtype` 取值（决定 entity emit 时的 confidence）:

| subtype | 触发 | confidence |
|---|---|---|
| `decision_taken` | act=propose, acceptance=hard | 0.95 |
| `decision_soft` | act=propose, acceptance=soft | 0.65 |
| `decision_rejected` | act=propose, acceptance=rejected | 0.85 |
| `unclaimed_proposal` | act=propose, acceptance=unclaimed | **0.40** |
| `rationale_accepted` | act=explain, acceptance=hard | 0.85 |
| `rationale_soft` | act=explain, acceptance=soft | 0.55 |
| `clarify_open` | act=clarify, acceptance=unclaimed（user 始终未答）| 0.40 |
| `report_observed` | act=report, 后续被 affirm/作为 constraint 引用 | 0.70 |

unclaimed/clarify_open 的 0.40 阈值依据 [PLATO-LTM](https://arxiv.org/abs/2203.05797) 和现有 search_by_embedding 的 `score × (0.5 + 0.5 × confidence)` 混合公式：低 conf 自动深排但不丢弃。

### 6.4 失败兜底

- 单 task framing 失败：构造 fallback `purpose_title = head[:80]` + `purpose_body = head + " ... " + tail`，标 `framing_failed=true`，subtype 仍按 acceptance 推断。**不丢弃 entity**。
- 标 framing_failed 的 entity 在 reflexion 阶段优先复审。

### 6.5 框定原则（写进 prompt）

1. title 必须用 user 视角的"用途"语言，不是 agent 内容罗列。例：
   - ✅ "数据库选型方案: SwiftData vs GRDB"
   - ❌ "GRDB 是基于 Rust 的 wrapper，对 macOS 15 兼容性更好"
2. body 引用原文片段时**保留原文措辞**，但叙述视角是 user
3. 不引入对话中没出现过的事实
4. body 长度 150-300 字，不强制凑数

### 6.6 成本估算

695-turn 大档实测产生 ~300 task。按 6 task/batch = 50 batches × ~20s = ~17 min, < $0.5。

可与 reflexion 同时跑（独立输入），节省墙钟时间。

---

## 7. Tier 4 — Reflexion（沿用，扩审查面）

### 7.1 新增审查项

- purpose_title 是否忠实于 head+tail（防止 framing pass 过度泛化）
- purpose_body 是否引入新事实
- framing_failed=true 的 entity 是否值得保留

### 7.2 沿用项

- hallucination / missing user-derived constraint / target misassignment

### 7.3 阈值

confidence ≥ 0.7 才删 / ≥ 0.5 才补 / ≥ 0.7 才移动。同 V2-A。

---

## 8. tree_to_entities — emit 矩阵

### 8.1 完整矩阵

| 来源 | type | title 来源 | confidence |
|---|---|---|---|
| Goal.intent | context | user 语言（不变）| 0.80 |
| Goal.constraints | constraint | user 语言（不变）| 0.90 |
| Task.outcome_unit_id → agent unit | **agent_content** subtype=decision_taken/_soft | purpose_title | 见 §6.3 表 |
| Task.lesson_unit_ids → agent units | **agent_content** subtype=rationale_accepted/_soft | purpose_title | 见 §6.3 表 |
| Task.abandoned_unit_ids → agent units | **agent_content** subtype=decision_rejected | purpose_title | 0.85 |
| 同上配套 | constraint("Avoid: <purpose_title>") | 派生 | 0.90 |
| Task.constraints | constraint | user 语言 | 0.90 |
| Task.soft_constraints | constraint | user 语言 | 0.55 |
| Task.terms | term | user 语言 | 0.85 |
| Unclaimed agent units | agent_content subtype=unclaimed_proposal/clarify_open | purpose_title | 0.40 |
| 文件 + 4 边 | file + edges | 不变 | 0.95 |
| corrected_to 边 | abandoned 与 correction unit_id 间 | — | — |

### 8.2 entity content 字段

- agent_content type entity: `content = purpose_body`（来自 framing pass）
- 其他 type entity: 同 V2-A

### 8.3 embedding 文本

`embedding_text = purpose_title + ": " + purpose_body`（用 user 视角文本嵌入，符合检索 query 语言）

### 8.4 junk filter（继承 A 修复）

A 已加的 junk-title 过滤继续生效。purpose_title 由 LLM 生成，几乎不会触发 junk 规则；fallback path 走 head[:80] 也基本安全（head ≥ 100 字符）。

### 8.5 metadata_extra

每个 agent_content entity 携带:
```json
{"subtype": "decision_taken", "framing_failed": false, "source_task_id": "..."}
```

---

## 9. 检索流程（不钻取）

agentic RAG 不变。entity 命中后**不需要任何额外取原文**——purpose_body 已含足量上下文（head + mid + tail）。

预期收益 vs A:
- 检索 query 与 agent_content entity title 同为 user 视角语言 → embedding 相似度更对称
- entity 池数量级相近，但 title 更聚焦（每 task 1-2 条 agent_content vs A 的 3-5 条 lesson/proposal）
- 无新工具调用 / 无延迟增加

---

## 10. 模块文件结构 (`companion-py-b/`)

```
companion-py-b/
├── README.md                        # B vs A 差异速览
├── claude_adapter.py    → ../companion-py/claude_adapter.py    (软链)
├── copilot_api.py       → ../companion-py/copilot_api.py       (软链)
├── entity_resolver.py   → ../companion-py/entity_resolver.py   (软链)
├── reflexion.py         → ../companion-py/reflexion.py         (软链, prompt 通过参数注入)
├── models.py            → 复制 + Task 字段重构 + DialogueTurn/AtomicUnit 字段补充
├── store.py             → 复制（无 schema 改动，只是为后续可能的小调整保留独立性）
├── state_machine.py     → 复制 + 改写回 task 字段方式（字符串→unit_id）
├── rag.py               → 复制（不加 drill-down，但 query 端可调 prompt）
├── preprocessor.py      → 重写：head/tail Tier 1
├── atomizer.py          → 重写：不对称 + 短回复规则
├── framing_pass.py      → 新建：Tier 3.5
├── tree_to_entities.py  → 重写：emit 矩阵 + agent_content type
├── companion.py         → 重写：插入 framing_pass 步骤
└── eval_*.py            → 新建：与 A 共用 golden set，新增 framing 质量评估
```

---

## 11. 评估对比 (A vs B)

### 11.1 共用指标（同 golden set）

- Tier 1: coverage / skip-precision
- Tier 2: act / target / scope accuracy
- Layer 2: Goal/Task 树结构正确率
- Layer 3: hallucination / missing entity rate

### 11.2 B 独有指标

- agent unit 数 / turn（目标 ≤ 2.5）
- framing pass 成功率（目标 ≥ 95%）
- purpose_title 忠实度（reflexion 抽审，目标 ≥ 90%）
- agent_content entity 占总 entity 池比例（目标 30-50%）

### 11.3 端到端检索对比

构造 30 条 user-style query，跑两套 pipeline，人工打分前 5 命中相关性。

预期 B 在以下 query 类型胜出:
- "为什么放弃 X" / "上次 Y 的结论" / "Z 文件的修改原因"
- 跨 session 的同类决策回忆

预期 A 可能在以下 query 类型胜出:
- "agent 给的具体 API 用法 / 代码片段"
- 需要 agent 解释细节的技术性 query

### 11.4 成本对比

| 阶段 | A | B (估) |
|---|---|---|
| Tier 1 | ~$0.20 | ~$0.20 |
| Tier 2 | ~$0.40 | ~$0.30 |
| Tier 3 | ~$0 | ~$0 |
| **Tier 3.5 framing** | — | ~$0.50 |
| Tier 4 reflexion | ~$0.20 | ~$0.25 |
| **Total / 695-turn** | **~$0.80** | **~$1.25** |

B 多 $0.45（framing pass）。如果 B 检索质量胜出 → 值。如果不胜出 → 不值。靠 §11.3 决定。

---

## 12. 阶段切换决策

跑完 A vs B 对比后据数据决定:

- 若 B 检索质量持平且不显著贵 → B 升主干，A 归档
- 若 A 在某类 query 显著胜出 → 保留 A 模式作为可选 deep-extract 路径，按 query 类型分流
- 若两者各有所长 → 探索混合（user 决策走 B，特定项目/会话标记 deep_extract=true 走 A）
- 若 B 反而更差 → 沉淀 framing pass 思路到 V2-A，仅用 framing 优化 lesson entity 的 title

---

## 13. 与 V2-A spec 的索引

| V2-A 章节 | B 对应 |
|---|---|
| §3 数据模型 | 本文 §2 |
| §4.2 Tier 1 | 本文 §3 |
| §4.3 Tier 2 | 本文 §4 |
| §4.4 Tier 3 | 本文 §5 |
| §4.5 Tier 4 | 本文 §7 |
| §4.6 Tier 5 / 检索 | 本文 §9 |
| §11 文件 entity / 边 | 不变 |
| **新增** | 本文 §6 (Tier 3.5 framing pass) |

未列出的 V2-A 内容 B 完全继承。

---

## 14. 研究依据（开放项决策溯源）

| 决策 | 依据 |
|---|---|
| head + tail 保留 + 中间 summary | [Lost in the Middle (Liu 2023)](https://arxiv.org/abs/2307.03172) U 曲线 |
| user-purpose framing 替代 content embedding | [Contextual Retriever EMNLP 2025](https://aclanthology.org/2025.emnlp-main.602.pdf) (91.9% vs 64.2%) |
| framing pass batched 5-8 task / call | [Batch Prompting arXiv 2301.08721](https://arxiv.org/abs/2301.08721) (~5× 成本节省) |
| unclaimed/clarify confidence 0.40 | [PLATO-LTM](https://arxiv.org/abs/2203.05797) 阈值参考 + 现有 score×conf 混合 |
| 不做 drill-down | 用户明确 ("我没有打算在检索时拿到原文再处理") + [EMem](https://www.arxiv.org/pdf/2511.17208) event-centric 单元思路 |
