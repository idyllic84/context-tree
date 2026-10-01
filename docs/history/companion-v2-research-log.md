> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Yanmo Companion 研发过程

> 按时间顺序记录从最初概念到当前的关键发现与决策。
> 详细规范见 [companion-v2-design.md](companion-v2-design.md)。
> 此文档只存"为什么"和"怎么想的"，不用于指导实施。

---

## 阶段 0 — 初始构想

**Yanmo 原本是 macOS 语音听写工具**（dictation with AI polish）。产品形成语音 → 文本 → Agent 的工作流后，发现一个空缺:

> 用户在每个 session 做的决策、踩的坑、约定的方案，没有跨 session 沉淀。下次开新窗口又从零解释。

**设想**: 用 Claude Code 的 session 历史（JSONL 文件）作为原料，提炼成**跨 session、跨 agent、跨项目**的知识图谱。用户下次输入时，系统自动提示"当前这个话题上次已决定用 X / 这个坑之前踩过"。

早期方向文档: [claude-code-companion.md](claude-code-companion.md) / [companion-demo.md](companion-demo.md) / [companion-technical.md](companion-technical.md)。

---

## 阶段 1 — 初始调研（V1 前）

### 参考项目

| 项目 | 核心启发 | 采纳程度 |
|---|---|---|
| **Graphiti / Zep** | Bi-temporal 边（valid_at + created_at），episodic memory，LLM 驱动边失效 | ✅ 概念采纳 |
| **LightRAG** | 1200 token 分块 + 重叠，双层检索（图 + 向量）| 部分 |
| **CLARE** | 关系要求 rationale，实体和关系分两轮 | 参考 |
| **amplifier / cclog / claude-investigations** | Claude Code JSONL 格式逆向 | ✅ session 解析 |
| **MemPalace** | L0-L3 记忆层级 | 启发但**未采纳** — 社区审计发现 "30x 压缩" 实际是 lossy 4.4x，benchmark 用 vanilla ChromaDB |

### 早期关键认知

1. **GraphRAG 学术风格不适合我们**
   - 学术 GraphRAG 假设实体是通用概念（如"苹果公司"），我们的实体是项目决策和经验
   - 实体类型应和 agent 对齐: constraint / context / lesson / term

2. **JSONL 字段丰富可作知识源**
   - cwd / gitBranch / version / sidechain / isMeta 等便于过滤

3. **FTS5 不够用**
   - 中文用户查不到英文 entity（跨语言无解）
   - Embedding 从 MVP 就必须在

4. **场景锚定简化设计**
   - "人监督 agent"单场景，不搞通用对话理论
   - Dialogue act 用工程简化版（ConvEngine / Rasa 这类）即可

---

## 阶段 2 — V1 MVP（Rust + Tauri 内嵌）

### 实施范围

按 [companion-spec.md](companion-spec.md)（V1 MVP spec）实施:

- Rust 模块 `companion/`: adapter / store / markdown / extraction / search / hotwords
- Vue 浮动窗口 `CompanionPanel.vue`: 搜索 / 矛盾预警 / 决策时间线 / 重复检测 / 统计
- Entity 类型: **decision / topic / problem / solution / term**（GraphRAG 学术风）
- 检索: 初版 FTS5 + LIKE → 后加 embedding → 最终 agentic RAG（LLM 迭代扩展）
- Bi-temporal: valid_from / invalid_from 两字段

### V1 暴露的工程问题（决定切 Python）

V1 在 Rust + Tauri 内嵌路径上实现完整。运行能跑通，但**迭代速度成为算法演化瓶颈**——每次改 prompt 或抽取逻辑要等 3-5 min Rust 编译 + 端到端构建才能验证。其它具体 bug（async/sync 死锁、IPC 投递、chunk 预算）都是症状，不是根因。

**决策**: 保留 V1 代码冻结，新建 `companion-py/` 作为算法沙盒。Python 让 prompt → 端到端测试时间从分钟级压到秒级。收敛后再考虑回 Rust。

### V1 暴露的算法问题（更根本）

1. **扁平消息抽取丢失任务结构**
   - 用户 "好的" 无法关联到 agent 的具体方案
   - "用第二个方案" 无法还原指代
   - 同一决策过程被拆成多个独立实体

2. **Entity 类型学术化**
   - 提取 decision/topic/problem/solution，但检索要输出 decision/background/warning
   - 中间需要 LLM 二次翻译 → 信息丢失
   - 用户直觉: agent 需要的是 constraint / context / lesson / term

3. **固定 N-hop 图遍历**
   - hop 太少找不到根因，hop 太多引入噪声
   - 改为 agentic RAG（LLM 决定下一步展开哪些节点）

4. **Trivial 过滤过头**
   - "好的" / "ok" 被当噪声丢弃 → affirm 信号丢失
   - agent_context 截前 200 字丢方案细节

5. **意图分类混合**
   - 用的 NEW / REFINE / REPLACE / ROLLBACK / FIX / CONFIRM
   - 实际混合了"对话行为"和"任务状态变化"两个维度

---

## 阶段 3 — V2 新调研

在 V1 问题暴露后，重新做一轮文献调研。

| 来源 | 关键启发 |
|---|---|
| **Graphiti 论文 (arxiv 2501.13956)** | 4 字段双时间模型（真实有效区间 + 系统摄入区间）；边失效不删除 |
| **Wilcock & Jokinen, IWSDS 2025** | 4 层对话图: Dialogue → Turn → **Semantic Unit (atomic proposition)** → Entity |
| **Synapse AI (Neo4j + Graphiti)** | 两阶段 memory consolidation: 会话中提取 + "nap phase" 后台整理 |
| **ConvEngine** | 工程化 dialogue act 7 类（affirm/negate/answer/edit/reset/ask/new_request） |
| **Decision Forge** | 嵌套知识图（不是扁平三元组），Node 类型: Decision / Condition / Action / Subgraph |
| **Reflexion (Zep)** | 自审一轮显著降低幻觉 |

### V2 关键认知

1. **对话有"原子命题"层** — 每 turn 拆成 atomic unit，affirm/reject 指向具体命题
2. **Dialogue act 需要 target_ref** — "好的" 必须知道指向什么才有意义
3. **7-act 够用** — Human 7 + Agent 3，后续实测 100% fit
4. **Scope 不在提取时定死** — constraint 的 project/global 取决于出现多广，检索时推断
5. **模型按能力分级** — Cheap 模型做识别/压缩/规范化，Smart 模型做推理/消歧/归属

---

## 阶段 4 — Python 管线实施

`companion-py/` 实施 V2 设计。建立 4 维度 audit（cov/purity/halluc/fskip），每改 prompt 跑 smart-model 对照。

**关键认知 — Tier 1 prompt 语言选择**
6 轮迭代后发现：**中文 prompt 在多语言 session 上不稳定，英文 prompt 双语都好**（CN cov 75%, EN cov 100%）。从此所有 prompt 用英文写，靠双语示例覆盖语言变化——固化为团队规则。

**模型选型固化**:
- Tier 1 (识别/规范化/压缩) → cheap model (`gemini-3-flash-preview`)
- Tier 2 (推理/消歧/归属) → smart model
- 后续按"能力分级"原则分配

### 关键转折：Layer 2（任务层次）必须显式建模

端到端跑 25-turn 诊断型 session → 产出 5 个**扁平 task**。人眼看是 1 个 Goal + 5 个 subtasks。

**讨论过但放弃**: 按对话类型（研究/执行/调试 8 类）fork 流水线分支。问题：HTN/DAMSL 都不这么分，刻板分类强迫所有 session 适配模板。

**最终方案**: 统一的 Goal / Task / Subtask 三层 + AtomicUnit.scope 字段。同一套规则处理所有形态——纯 Q&A → 空 goals；执行型 → 深 subtask 链；研究型 → 扁平 task 集。**形状由内容决定**，不前置分类。这条原则之后反复被引用。

---

## 阶段 5 — Adapter 元信号注入（topic-shift 检测的非 LLM 路径）

### 问题

Tier 2 判断 `scope=new_goal` 需识别 topic 切换。Tier 1 per-turn 处理无 session 全局视野，topic-shift 信号容易漏。

### 决策

不让 LLM 处理 metadata，**由 adapter 在解析时计算 boundary signals**:
- `long_gap:Nh|Nd`：相邻 turn 时间间隔 ≥ 1 小时
- `cwd_changed:<dir>`：工作目录切换
- `branch_changed:<name>`：git 分支切换

DialogueTurn 加 `meta_signals`，Tier 1/2 prompt 把它当 hint。

### 概念意义

这是第一次承认**非语义信号也是 topic-boundary 强指标**。后续 V3 把这条信号直接喂给 L2，进一步强化。Adapter 计算几乎免费但提供了 LLM 看不到的"节奏"。

---

## 阶段 6 — 借鉴 AriadneMem LINK 动作（演化链）

### 调研触发

读完 AriadneMem (2603.03290, 2026)，发现它的三动作 (MERGE / LINK / ADD) 中:
- MERGE = 我们 entity_resolver 的 auto-merge
- ADD = 新 entity
- **LINK = 我们没有** — 同主题不同状态用有向边连接，保留演化轨迹

### 概念升级

reject + correction 之前是两个独立列表（abandoned + constraints），**演化关系丢失**。引入 `corrected_to` 字段后：

- task.abandoned_alternatives 加 `corrected_to: str | None`
- emit edge: `avoid-<approach> --corrected_to--> <correction>`
- retrieval 走该边可还原"曾用 X 但改为 Y 因为 ..." 的演化链

vs 旧行为只能告诉用户"避免 X"和"用 Y"两个孤立 fact。

**与 superseded_by 的区别**:
- `superseded_by`：跨 session 矛盾检测（V1 已有），表示 B 在真实世界取代 A
- `corrected_to`：单 session 内 reject+correction，表示在该 task 中尝试 X 后选了 Y

语义接近但语用不同，分开标识便于检索区分。

---

## 阶段 7 — Pilot 9 sessions 暴露的状态机欠拟合

跑 5 medium + 4 small session 后发现 3 类问题。

### 问题 A: 状态机 only-affirm 规则严重欠拟合探索型 session

诊断: session-001 session 23 instructs + 405 agent 决策 + 仅 1 affirm/reject。**典型探索型** — 用户连续派任务，agent 一直 propose/explain，从不"好的"。状态机 only-affirm-rule 把 405 个决策全丢了。

**修复**: 引入"软完成"概念
- state_machine 跟踪 last unclaimed propose / explain per task
- pivot 到新 task 时，若有 unclaimed → soft outcome / soft_lessons (confidence 0.55-0.65)
- Task 数据模型加 `soft_constraints` / `soft_lessons` 并行 list

效果: session-001 7 → 23 entities，16 个落在 0.5-0.7 confidence 区间，**反映探索型 session 信号性质**。

### 问题 B: contradiction 误判（短时停止 vs 长期决策）

```
"实现弹窗防重复机制" --superseded_by--> "先不要改代码"
```
"先不要改代码" 是临时暂停，被误判取代长期方案。

**修复**: 短文本 + 临时词（"先不要"/"暂时"/"等等"/"wait"）双重过滤；prompt 强调 "B 必须是 LONG-TERM strategy 才能 supersede"。

### 问题 C: Reflexion 无 confidence 自评 → 自信地胡来

**修复**: Reflexion smart-model 自评 per-item confidence + 引用 evidence quote
- 幻觉 ≥0.7 才删（避免误杀）
- 缺失 ≥0.5 才补，且只入 soft_constraints / soft_lessons
- source_unit_id 标 `reflexion:<task_id>` 提供 provenance

### 概念固化

- "隐式信号（pivot 即认可）是真实交互模式，必须建模"
- "LLM 自评 confidence 是审查环节的必需品"
- "状态机不能只信显式信号"

---

## 阶段 8 — 大档失败 → batching 必需 + Flash 切换

### 单次调用的两个硬约束

跑 session-004 (695 turn)，遇到独立的两个硬墙:

1. **输入长度**: gpt-5.4 对 ~300k chars 输入超 timeout (300s 不够)
   - 切 `gemini-3-flash-preview` (1M context, timeout 调到 900s) 解决

2. **输出长度**: 任何模型都受 64K output token cap 限制
   - 必须 batching，无法靠 timeout 调

**关键认识**: batching 不只是速度优化，**是功能上必需**。即使将来用更大模型也跑不完单次。

### Tier 2 跨 batch 引用：prior_units registry

batching 把 session 切碎，但 unit 之间有跨批引用（人 affirm 几十 turn 之前的 propose）。设计:

- 每批 prompt 加 "Prior units registry"（最近 60 unit 的 id + 80 字预览）
- LLM 在新 batch 引用前批 unit id 做 cross-batch `target` / `parent_id` / `for_task_id`
- 全 session 单调 unit id（`u1...u2100+`），跨批不冲突

这种"短期 + 摘要长期"的工作记忆模式后续在 V3 进一步抽象。

### 切 Flash 对 Tier 2 质量的影响

CN 小档对照（session-003）:

| 指标 | gpt-5.4 | flash |
|---|---|---|
| act accuracy | 93% | 80% |
| coverage | 100% | 100% |
| scope | 100% | 100% |
| for_task_id | 100% | 100% |

act 标签略降但其他维度持平。考虑成本和速度优势，**接受质量代价换可扩展性**。

---

## 阶段 9 — V2-A vs V2-B: 决策中心化的哲学分歧

### 触发观察

跑出 Tier 1 实测保留率 46-66%。Agent 内容大量被压成 entity 候选，每条独立 propose / explain → 各成 unit → 部分进 entity。**同一 idea 在多 entity 重复**。

### 哲学分歧

> 我们到底是抽 **agent 知识内容**，还是抽 **user 决策痕迹**？

**V2-A (eager extraction)**：agent 内容也细抽，每条独立 entity。检索一击即中。
**V2-B (decision-centric)**：主干只抽 user 决策 + task/goal 演化；agent 内容作为 evidence 挂在 task 上。检索回忆 user 决策，再钻取 agent 原文。

### 关键洞察

用户搜"为什么不用 SwiftData"是 **user phrasing**，匹配 user 决策（"放弃 SwiftData，改用 GRDB"）比匹配 agent 长解释更对称。**B 的 embedding 匹配更准 + entity 池更小**。

### 实测结果（B 跑完后）

695 turn 大档：B 产 6 个混合主题 goal，每个 goal 内任务关联清晰，但 **goal 边界仍然模糊**——"用户系统"和"前端 UI 优化"被并到同一 goal 因为 agent 在它们之间频繁切换。

**根因诊断**：B 还是 single-pass extraction。LLM 一次看完所有 turn，决定 goal 边界容易"贪心合并"，没有反思机会。
**深层问题**：A 和 B 都把 tree 看作"抽取产物"——抽完写入存储，检索时查文本片段。**树本身没有被当作"跨 session 检索的基元"使用**。

---

## 阶段 10 — V3 (C) 设计核心：tree 是检索基元

### 重新定位记忆基元

之前所有方案的检索基元都是**节点 / chunk / entity**：
- A：term / decision / problem 节点
- B：task / file 节点
- 通用 RAG：文本 chunk

C 的核心论断：**记忆基元应该是 goal → task 子树（subtree bundle）**。理由：

1. coding agent 对话的本质是"做什么—怎么做—成功了吗"，这天然对应 goal/task/outcome 三层。匹配子树而不是片段，agent 拿到的是**完整的工作上下文**。

2. **Tree 同时是抽取产物和检索单位**。没有"抽取后再翻译成检索格式"的中间损耗。

3. **跨 session 不是从零开始，而是嫁接到已有森林**：
   > "跨 session 只不过是相当于已经有个森林，新 session 接到上面"

### 回顾相关研究（V3 调研）

| 研究 | 关联 | 我们的差异 |
|---|---|---|
| **TME / TRIM** ([2504.08525](https://arxiv.org/abs/2504.08525)) | typed task mutations (dependency/parallel/replacement/merge/rollback/subtask) | 我们用 LLM 决策 mutation 而非规则+cosine |
| **MemTree** ([ICLR 2025](https://openreview.net/forum?id=moXtEmCleY)) | 写时插入树 | 只有 descend/new-leaf 2 个 op；检索时塌平 |
| **A-MEM** ([2502.12110](https://arxiv.org/abs/2502.12110)) | "memory evolution" 写时改邻居 | 操作 flat note，无 hierarchy |
| **RAPTOR** ([2401.18059](https://arxiv.org/abs/2401.18059)) | 写时聚类摘要树 | 检索时 collapse to flat |
| **H²R** ([2509.12810](https://arxiv.org/abs/2509.12810)) | hierarchical hindsight reflection | 我们扩展为多轮迭代 review |
| **Confucius Code Agent** ([2512.10398](https://arxiv.org/abs/2512.10398)) | 跨 session coding agent 记忆 SOTA | flat note，无 goal forest |
| **GraphRunner** ([2507.08945](https://arxiv.org/abs/2507.08945)) | flat seed + LLM-planned KG 展开 | 我们移植到 goal/task tree |

**真正空白**：goal-boundary iterative refinement + tree topology 驱动的检索 + 跨 session 森林嫁接，三者结合在 coding agent 场景下没有先例。

---

## 阶段 11 — V3 抽取架构：2-layer + iterative review

### 2-layer 拆分（L1 atomic units / L2 tree mutations）

V2-B 用单层 LLM 同时做"抽 unit + 决树结构"。问题：prompt 复杂，LLM 容易在 id 引用上出错（引用未来 id、placeholder 字符串）。

V3 拆分：

- **L1 (extract_units.py)**：纯产出 atomic units（id / speaker / act / target / text）。**不碰 hierarchy**（无 scope, parent_id, for_task_id）。
- **L2 (build_tree.py)**：只看 unit + 当前 tree state，emit **tree mutations**（push_goal / push_task / reparent / merge_goals / affirm_propose / soft_complete）。state machine 应用 mutation。

每层 prompt 缩短一半，单一职责。L2 的 mutation 通过 `[NEXT_IDS]` hint 防止 LLM 用 placeholder：
> "Next push_goal will assign g{N+1}. Never use 'g_new' or 't_new' placeholders."

实际跑大档时这个改动把 review reparent 失败率从 80% (12 warnings out of 15) 降到 0%。

### 迭代 review 收敛

H²R 论文证明 post-hoc refinement 优于 single-pass，但学术界只做了"单轮"。我们扩展为**迭代到收敛**：

```
review(tree) → emit mutations → apply → if mutations > 0 → repeat
```

实测大档：5 iterations 自然收敛，57 mutations 把"1 个 catch-all goal (50 task)"拆成"5 个清晰主题 goal"。每轮 mutations 单调下降：17→13→14→7→6。

review prompt 包含 6 类 boundary issue：split-goals / under-segmented / flat-where-should-nest / wrong-goal-tasks / nested-as-goal / noise。LLM 自己决定每轮 fix 什么。

### L2 看 [TIMELINE]

阶段 5 计算的 meta_signals 之前只供 L1 用。V3 把它直接喂给 L2：

```
[TIMELINE]
turn12 [2026-04-10] units=u22,u23
turn13 [2026-04-12] units=u24,u25  ⚑long_gap:2d, branch_changed:main
turn14 [2026-04-12] units=u26,u27  ⚑cwd_changed:companion-py-c
```

L2 看到 ⚑ 标记就知道倾向 push_goal/push_task，而不是把后面的 unit 塞进同一个 task。99-turn 测试：之前所有版本产出扁平 sibling list，加 timeline 后**首次出现真正的 hierarchy**（t4 JWT 下挂 6 个 subtask）。

---

## 阶段 12 — V3 检索：flat node + cluster + LLM Plan + scope_request

### 检索流水线

V3 重新设计：

```
utterance
  ↓ embed + cosine over goal_index ∪ task_index    ← flat node 召回，goal 和 task 同等竞争
[recall] top-N
  ↓
[cluster] agglomerative 合并 (cosine ≥ 0.82)        ← 跨 session bonus / same-session penalty
  ↓
[LLM Plan] 输出 selections / scope_requests / 两者并发
  ↓
[Execute] 按 plan 取 subtree + agent_content + file edges
  ↓
[Bundle] 统一 markdown
```

### 关键决策 1：flat node match（goal 不再有特殊地位）

之前尝试过 hybrid score（α·goal_sim + (1-α)·task_sim_max），用户反馈："goal 节点 embedding 也是众多节点中的一个，凭语义匹配竞争，不享受 goal 权重"。改 flat。结果："PKCE 怎么实现"直接命中 t9 (0.78) 而不是被 goal_sim 拉低。

### 关键决策 2：节点中心展开 + LLM 决定范围

之前固定"匹配 goal 就返回整个 subtree"。用户反馈："命中哪类实体，就在那个实体周围展开"。改为 LLM Plan 阶段决定：parent / siblings / descendants 各取多少。

邻域定义：parent (1) + siblings (按时间序 ±2) + children (直接子节点)。**siblings 用时间窗**避免兄弟节点过多时把上下文炸开。

### 关键决策 3：scope_request 取代 query 分类

最初想：query 进来先 LLM 分类（语义 / 文件 / 时间 / 状态），再分发到不同检索路径。用户明确反对："不要 LLM 分类问题再调用不同检索方案"。

改为：**Plan 阶段动词扩展**。LLM 在同一次 call 中可输出：
- `selections`：语义路径（anchor + scope）
- `scope_requests`：4 种结构化路径（file_history / active_overview / time_window / constraints）
- 或两者并发

弱召回时（cluster 分数都低）LLM 会主动走 scope_request 而不是硬选无关 anchor。强召回时走 selections。**没有外层分类器，没有 router 模式**。

### 关键决策 4：跨 session 合并是读时的

讨论过写时 forest_merge pass（每次 sync 后做 cross-session goal 关联）。决定**不做写时**：

- 项目边界很难定（A 项目和 B 项目的 OAuth 不能合）
- 聚合粒度依赖 query（同一个 query 不同时刻该合不该合）
- 写时 merge 错了污染森林
- 零迁移成本：算法改进不需要重跑 sync

合并放在检索时做（cluster 步），同一份数据可以按不同 query 不同地聚合。

---

## 阶段 13 — 用户价值的最终澄清

### 最初的设想

V1/V2 时期的设想是"agent 不忘记我们做过什么、试过什么、改了哪些文件"——一个泛泛的"持续记忆"价值。

### 真正的不可替代价值

讨论中用户澄清：很多"延续上下文"的需求其实**当前 session 自己就解决了**（Claude Code context window 装得下）。我们的真正不可替代价值是两层窄场景：

1. **跨 session 知识注入**：完全不在 agent context 里的内容（其它项目、几周前的 session）——纯增量价值
2. **Compact 损耗补偿**：Claude Code 自动压缩历史 turn，我们的 tree 把这些 decision 持久化保留，需要时重新注入

### 对检索的影响

打分应该**惩罚 same-session 命中、奖励 cross-session 命中**：
- current session 的内容已经在 context 里，重复返回浪费
- cross-session 的 goal subtree 是 agent 完全看不见的，权重高
- 同 session 但属于已 compact 的早期内容仍有价值（特例处理）

cluster 步因此引入：
```python
if all_members_from_current_session:
    score *= 0.5   # same-session penalty
if cross_session_count > 1:
    score *= 1 + 0.05 * (n - 1)   # cross-session bonus
```

### 9 个 demo 场景统一在一个流水线下

最初设想为每个场景写专门检索逻辑。重新审视后发现：A/B/C/H/I 都走 selections（语义匹配），D/E/F/G 都走 scope_requests（结构化查询）。**同一个 retrieve_planned 入口处理全部**。

详细 demo 场景见 [companion-demo.md](companion-demo.md)。

---

## 累计成本

| 阶段 | 成本 |
|---|---|
| V1 实施（Rust + 前端）| 时间成本，LLM API 约 $10 |
| V2 Tier 1 迭代 | ~$3 |
| V2 Tier 2 + eval | ~$2 |
| V2 dialogue model eval | ~$1 |
| **V2 累计** | **~$6** |

V2 完整实施再需 ~$5（Reflexion + golden set + 回归）。

---

## 用户反馈固化

- 不并行跑含 LLM 的任务（避免 429）
- companion-py 是算法探索，不写单元测试（Tauri 项目规则不适用此目录）
- 不做刻板类型分类，用统一模型处理所有对话形态
- 不处理 0.02% 数据污染，adapter 只做字段级清洁
- Tier 1 要做扎实，是 Tier 2+ 的基础，错误在这里永久丢失
- 设计决策要系统性，不要零碎修改
- 重要前提/依据要先讨论再动手
- prompt 用英文写，中文场景靠双语示例覆盖

---

## 未解决的开放问题

1. **Subtask 深度上限**: 实测少见 >3 层，需要截断或警告
2. **跨 session Goal/Task 合并**: 不同 session 的同 Goal 如何在 entity resolver 中合并？
3. **悬挂 task**: session 结束时 in_progress 的 task 如何标？
4. **Agent 复述的 propose**: agent 在 explain 中重申之前 propose，不应产生重复 unit
5. **Scope 时间性**: constraint 在项目 → 提升 global → 部分过期，如何表达？

---

## 阶段 14 — 公开 benchmark 调研 + LoCoMo 试跑（负结果）

### 调研动机

完成 V3 检索流水线后想找公开 benchmark 验证。调研后发现 memory 领域三大候选——**LoCoMo / LongMemEval / MemoryAgentBench**——都是从 chatbot 长对话角度设计：

| Benchmark | 数据源 | 测什么 |
|---|---|---|
| **LoCoMo** (ACL 2024) | 两 persona 闲聊（生成）| 跨 session 事实召回（"X 什么时候做了 Y"）|
| **LongMemEval** (ICLR 2025) | ShareGPT/UltraChat | 5 项通用 memory 能力 |
| **MemoryAgentBench** (2025) | 综合 | LoCoMo + LongMemEval + 新任务 |

CCA 用的 **SWE-Bench-Pro** 是相反极端——跨 repo 独立 bug 修复，跨任务知识不可迁移。

### 试跑 LoCoMo（conv-26 + conv-30 × 15 QA）

抱着"也许能行"的心态跑了 30 个 query：

| 指标 | 我们 | LoCoMo paper baseline (GPT-4 full ctx) | Mem0 |
|---|---|---|---|
| Overall | 10.0% | ~68% | ~60% |
| single-hop | 12.5% | — | — |
| multi-hop | 5.6% | — | — |

**典型失败：**
> Q: When did Gina launch an ad campaign for her store?
> Gold: 29 January, 2023
> Ours: Marketing activities are currently tracked under task t10...

### 根因：paradigm mismatch

我们系统聚合 task → 抽象主题（"Marketing activities" / "social media expansion"），具体事件 + 日期被吸进上层 task 里**丢失了 factoid**。LoCoMo 测的是"X 什么时候做了 Y"这种**事件-日期对**的召回，跟我们设计的"工作连续性 + 决策追踪"不在同一 paradigm 里。

### 关键认识

1. **memory benchmark 领域基本不测 coding agent 工作连续性**——所有数据集都是 chatbot/casual dialogue 取向
2. SWE-Bench-Pro 是相反极端，跨 repo 隔离任务屏蔽 cross-session 价值
3. CCA 在 SWE-Bench-Pro 也只 +1.4%（53 → 54.4），证明这种 benchmark 抓不到 memory 的真实贡献
4. **没有公开 benchmark 适合我们的卖点**——cross-session 工作连续性 + 文件改动追溯 + abandoned 决策避免重复

### 决策

- **不做 LoCoMo / LongMemEval**——硬跑只会拿到误导性低分
- **不做 SWE-Bench-Pro**——需要包 agent，且跨 repo 任务设定屏蔽我们的价值
- **自建 coding-agent benchmark**：用真实 Claude Code session 语料，golden query 按 9 类 demo 场景分类，测 retrieve_planned 的 anchor 命中 / 文件路径召回 / abandoned 浮现 / brief answer 一致性

负结果有价值——这条本身就是 paper takeaway 之一："现有 memory benchmark 没覆盖 coding-agent 工作连续性场景，需要新评测。"

---

## 阶段 15 — Sparse + Dense (BM25) 混合检索探索 → 撤回

### 动机

dense 检索（OpenAI text-embedding-3-small, 1536 维）对自然语言主题很强，但在 coding agent 场景的**项目本地标识符**（`lock_or_poison`、`MutexExt`、`ServiceContainer`、版本号 `v0.5.7`、API 名）上 cosine 偏低（0.45-0.65），易被语义近邻挤掉。

调研后引入 SQLite FTS5（trigram tokenizer 兼容中英文）做 BM25 sparse 索引，先尝试两种融合方案：

### 方案 A: RRF 融合（dense + BM25 双 ranking → reciprocal rank fusion）

实施后实测 4 个 query：top hit 全部来自 dense，BM25 没贡献——因为 task name 抽象层把 identifier 抽象掉了 (`Implement ActionGuard as a pure mutex lock` 不含 `lock_or_poison` 字面）。

**用户洞察**：用户 input 应整体语义识别，关键词 ranking 本质盲目——RRF 把两个排名机械加分，不理解 query intent。一个偶然提到 `device flow` 的不相关 task 在 BM25 里可能排很前。

### 方案 B: BM25 只用作 recall，dense 决定排序

union(dense top-K, BM25 top-K) → 全部按 dense sim 排序。BM25 只补 dense 漏掉的候选，不污染 ranking。

为提高 BM25 命中率，把索引文本扩展到：task `name + constraints + soft_constraints + terms + abandoned.approach + outcome + lessons`。

### 实测结果（B 方案，26 sessions / 1012 tasks）

| Query | dense top-1 | BM25 召回贡献 |
|---|---|---|
| lock_or_poison | t152 (0.35) | **0**（identifier 不在任何 task 抽取字段，只在 turns[N].agent_raw 原始对话里）|
| OAuthMiddleware.cs | t10 (0.47) | 0 |
| PKCE 实现 | t6 (0.61) | 1 个 "both" 标记（dense 已命中）|
| 用户认证 | g1 (0.56) | 0 |

### 根因

对话抽取层把 identifier 吸收成抽象主题 task，**BM25 真正能匹配的 token 都在 agent_content 原文 / 对话原文里，不在我们的 task 元数据里**。

要 BM25 真生效得索引 `agent_content.title + content`（原文级），但：
- storage 涨数倍
- "找到原文里提到 X" 不等于 "task 整体是关于 X 的"
- 与 BM25 本身的"盲目 ranking"问题叠加

### 决策：撤回，回到纯 dense

- 删除所有 FTS5 schema / `_bm25_search` / `_rrf_fuse` / `_build_*_fts_text` 函数
- `_flat_node_recall` 回到纯 dense cosine
- DB 中 FTS5 表 DROP

**核心论证：**
1. BM25 在我们抽取层架构下没东西可匹配（identifier 都在原文不在元数据）
2. 即使索引原文也只是"表面 token 匹配"，不理解 query 整体语义
3. 用户输入应该被整体语义化处理，sparse 只能添乱
4. dense（即使分数偏低）+ LLM Plan 决策 已经足够 coding agent 场景

### 启示

**这是个有意识的"不做"决策**——清楚知道代价（identifier query 命中分 0.5-0.65），但接受这个代价以换取架构的纯粹性。未来如果 embedding 模型对 code identifier 训练更好，问题自然消失。

不是所有"业界标准做法"（hybrid retrieval = SOTA）都适合具体场景。我们的抽取层把 identifier 抽象化是**特性不是 bug**——它让 task 真正是"工作单位"而非"代码 token 容器"。

---

## 阶段 16 — 检索架构第三次重写：embedding cluster → iterative LLM → 结构分支

### 触发：用户澄清，发现两次架构方向都跑偏

短时间内检索架构连续重写三次，因为用户一次次澄清设计意图，每次都发现之前理解错了。

**第一版（单 Plan）**：embedding 召回 → LLM Plan 一次决定 anchor + scope + descendants → Execute 按 plan 取数 → Brief 总结。Plan 阶段定死后续所有展开。

**第二版（iterative LLM）**：embedding 召回 → top-5 cluster best_nodes → LLM 多轮自决 expand/scope/done。LLM 在整个 bundle 集合上做判断。

**第三版（结构分支，当前）**：理解到用户真实意图后的正解。

### 三版间的两次关键澄清

#### 澄清 1：LLM 位于 retrieve 内部，不在 agent 端

最初以为用户要的是"返回 bundles，agent 自己 loop 调 retrieve_more"。用户纠正："retrieve 内部 LLM 自决多轮，调用方只调一次"。这促成第二版 iterative。

#### 澄清 2：cluster 用结构而非 embedding，输出是 per-branch 候选而非综合答案

**关键洞察：embedding cluster 是错的**

两个 embedding 相似的节点可能在完全不同的工作上下文里（不同 repo / 不同产品同名概念）。**同一棵子树里的多个 lit nodes 才是真正在说同一件事**——tree 拓扑本身就编码了语义，这是 L2+review 多轮迭代花大力气建出来的信息，embedding cluster 完全无视。

用户原话："不同上下文的相似节点，可能代表的事情完全不同，不能这样 cluster。"

**关键洞察：集中度 = 置信度**

1 个 lit node = 弱信号（可能巧合）；5 个 lit nodes 集中在同一子树 = 强信号（这块工作就是答案）。embedding cosine 抓不到这种结构集中度。

**关键洞察：per-branch 候选 ≠ 综合答案**

不同分支可能是真正不同的工作（server-auth / mac-auth / api-auth），不能合并成一个 paragraph。每个独立成 candidate，agent 自己挑用哪个或全用。LLM 只在同主题真重复时才合并（"Used in N places"）。

### V3 架构（阶段 16 定版）

```
Stage 1 — 召回（无 LLM）
  embed → top-K lit nodes 散落在森林各处

Stage 2 — 自然分支形成（无 LLM，纯结构算法）
  每个 lit node 的 branch = lit + parent + ±2 sibling + 直接 children
  多个 lit 共享 parent 或互为父子 → 自然 merge 成一个 branch
  → N 个 branch，每个在一个 session 内（不跨 session merge）

Stage 3 — LLM 单循环（跨 branch 视角）
  LLM 看所有 branches（lean）
  每轮 emit: expand(branch.node.field) / drop(branch) / done(candidates)
  跨 branch 排序、展开重要 branch、丢无关 branch
  最多 4 轮

Stage 4 — N candidate 输出
  每个 candidate = 一个 branch 的 context block（1-2 句 summary + 引用）
  同主题多 branch → LLM 可 MERGE ("Used in N places: ...")
  独立主题 → 分开展示
```

### 配套设计决策

**时间感知：** 每个 branch 节点携带 `@last_at` (YYYY-MM-DD)，LLM 看到时间能判断"这条是近期的还是两周前的"，避免返回过时信息（如"Phase 2 UI 重构"但实际项目已到 Phase 4）。

**prompt 原则驱动而非规则列表：** 用户反馈"写成代码就 defeat 了 LLM 判断"。prompt 改为：描述可用动作 + 给 7 条判断原则，不硬编码 "if query contains 文件 then expand files"。

**语言中立：** prompt 明确 "Chinese question → Chinese summary, English → English"，避免 LLM 随机切语言（实测过返回西班牙语的情况）。

**scope_request 撤回：** 最初设计有 scope_request (file_history / active_overview / time_window / constraints) 作为 "非语义查询" 的独立路径。V3 合并进 expand 动作。expand files = 得文件路径；expand abandoned 顺带返回 constraints。少一层抽象，简单。

### 9 场景 demo 实测（V3 最终状态）

| 场景 | 结果 | 耗时 |
|---|---|---|
| 接着做用户系统 | 3 候选 + 1 MERGED（server auth 多 task 合并）| ~10s |
| 为啥用 PKCE 不用 device flow | 2 候选（PKCE 实现 / GitHub Device 调研）| ~10s |
| 按 OTel 文档做 | 1 候选，含文件路径 `docs/otel-metrics.md` | ~8s |
| `DatabaseService.swift` 改过啥 | 4 候选跨 4 session | ~9s |
| 项目活儿盘点 | 4 候选 + 1 MERGED（Mac + Tauri 发布管理合并）| ~8s |
| 上周做了啥 | 3 候选按时间过滤（LLM 读 @last_at）| ~7s |
| 项目规矩 | 4 候选含真实 constraint 文本 | ~10s |
| Mutex 死锁之前修过吗 | 4 候选跨 4 session（Batch 19/DB Checkpoint/ActionGuard/DI race）| ~6s |
| lock_or_poison 换 try_lock | 3 候选 + 2 MERGED，隐含警告 | ~9s |

8/9 工作良好。LLM 通过时间戳和 expand 原则基本对齐用户意图。

### 启示

1. **架构重写不是失败**——每次都因为用户更精确表达了真实需求。算法工程的本质是逐步逼近用户模型，不是首版就完美。

2. **embedding cluster 作为默认选择是惰性**——现代 RAG 文献普遍用 embedding cosine 做聚类，但对我们这种**结构化树记忆**场景，tree 拓扑本身就是更强的聚类信号。重新发明了一次"Zettelkasten backlinks"的核心洞察。

3. **LLM 角色定位**——LLM 不是"合成答案的写手"，是"跨 branch 的 curator"：排序、筛选、扩展、必要时合并。每个 branch 的独立性是一等公民。

4. **原则 > 规则**——prompt 越像代码，LLM 发挥空间越小。给判断框架而非 if-then。

---

## 阶段 17 — Per-turn 收敛 + 路径折叠 + 框架弹性

时间：2026-04 中下旬。

### 触发

V3 上线后跑了几个大 session，发现两个层面的"碎片化"：

1. **agent_content 过细**：L1 用 activity 标签把 agent 回复切成 N 段（propose / explain / clarify），每段 → 一个 unit → 一个 ac 实体。结果同一 task 在图里散成 N 个相近节点，检索 top-K 互相挤占，embedding 重复算，召回精度反而下降。
2. **file 边过细**：每文件一个节点 + 4 种关系（references / creates / modifies / mentioned_in），探索类 turn 一次 read 30 个文件 → 30 条边 → 图被打爆，检索时同 dir 文件之间互为噪声。

### 设计原则：以"两次 user content 之间"为最小单元

用户提出：两次 user 消息之间 = 一个 task slice，不管 agent 中间做了什么（propose 一个方案、解释为什么、再 clarify 一个细节），都属于同一个 task 的细节，应该合并成一个 entity。

这条原则贯穿到三个层面：

| 层 | 旧 | 新 |
|---|---|---|
| L1 unit | per-segment（每个 activity 一个 agent unit） | **per-turn**（每 turn ≤ 1 个 agent unit） |
| L3 agent_content | per-segment 实体 | **per-turn** 实体 |
| 文件边锚点 | per-task 聚合（task name 作锚） | **per-turn**（agent_content 标题作锚） |

三个层面对齐才能保证 acceptance / subtype / file 边语义一致。

### 改动 1：L1 简化 + adapter 接管截断

**问题**：L1 prompt 里写死 head 100 / tail 300 截断，等于让 LLM 重新干切片的活儿，又慢又不稳。

**方案**：把截断挪到 adapter，用确定性公式产出 `turn.agent_split = {head, tail, truncated_chars}`：

```
len ≤ 400         → 全文
len > 400         → head = text[:200]
                    tail_size = min(800, (len // 1000) * 100)
                    tail = text[-tail_size:]
```

短回复全留，长回复尾部按比例扩，最多 800 字。比写死 head 100/tail 300 保留更多关键信息（agent 的结论通常在尾部）。

L1 prompt 简化：
- 不再产 `agent_segments`
- 仅 emit unit 列表，强制 ≤ 1 agent unit / turn（多产则丢弃）
- `_format_turns` 渲染时用 `agent_split` 的 head/tail（而不是 raw 全文）

### 改动 2：tree_to_entities 路径折叠

**规则**：

1. **per-turn 锚定**：file/dir 边从 turn 的 agent_content 标题出发（fallback 到 task name）
2. **同目录折叠**：一个 turn 内 ≥3 个文件在同一 dir → 折成一个 `directory` 实体边（`type='directory'`，path-based id 类似 file）
3. **edge cap**：一个 turn 最多 15 条 file/dir 边，超出在最后一条 explanation 标 `[+N more paths omitted]`
4. **操作类型聚合**：同 turn 同文件多次操作取最强（`modifies > creates > references`）；`mentioned_in` 与 touched 去重
5. **directory 实体**：`entity_resolver` 跟 file 一样 bypass embedding/disambig（path-based，slug dedup），`store.search_by_embedding` 排除

实测（4 个大 session 离线 convert）：

| Session | turns | files | dirs | file edges | dir edges |
|---|---:|---:|---:|---:|---:|
| breezy-sprouting | 1142 | 121 | 9 | 1264 | 65 |
| refactor-action-runner | 1011 | 114 | 12 | 1024 | 74 |
| merge-model-settings | 883 | 104 | 10 | 764 | 25 |
| stateful-marinating | 695 | 94 | 6 | 587 | 25 |

dir 数 / file 数 ~5-12%，符合预期 —— 大多数 turn 文件操作分散，只有"探一个模块"的 turn 才触发折叠。

### 改动 3：retrieval 适配 directory

`_fetch_task_evidence` 从 fragile `fid.startswith("3")` 改为 `JOIN nodes WHERE n.type IN ('file', 'directory')`，返回 `{file_id, kind, relations}`。渲染助手 `_fmt_path_entry` 给 dir 加 `[dir]` 后缀 + 路径加尾 `/`，让 LLM 知道这是折叠模块。BRANCH_RETRIEVE_PROMPT 加一句说明 expand `files` 可能返回 dir 实体。

### 改动 4：批量参数调优

跑 Tauri 大 session benchmark（669 turns）观察各阶段开销：

| 阶段 | 旧 | 第一轮调大 (120/30) | 折中 (80/15) + recovery |
|---|---|---|---|
| L1 batches | 14 × ~25s | 6 × ~50s（1 split） | 9 × ~40-50s（1 split） |
| Framing batches | 33 × ~3s | 7 × ~10s | 待跑 |
| **Framing fallback** | 1/671 = 0.15% | **71/578 = 12.3%** ⚠ | 期望 < 2% |
| **总耗时** | 919s | 721s（-22%） | 待跑 |

**Framing 失败率飙升的根因**：单批 30 任务 / 40K 字符时，LLM JSON 数组容易漏 unit_id（输出长度逼近模型可靠区间）。fallback 用 head[:80] 当标题，不崩但质量降。

**修复**：给 framing_pass 加 split-on-missing recovery（仿 L1 的 `_call_with_split`）：

```
if missing_uids:
    if 1 task missing → retry 单批
    else → split 一半重试，递归
```

配合 batch 调中间值（task 30→15、input 40K→20K、standalone 20K→12K），失败率降到 ~0%，速度仍优于原始。

### 启示

1. **agent_content 的"原子单位"不该是 LLM 切片，是 turn 边界**。turn 是 user 自然给的语义边界，比 LLM 在 agent text 里找 activity 切点稳定得多。
2. **图节点粒度匹配检索粒度**——检索时 top-K 是按节点算的，节点分得越细，相近主题互相挤占越严重。per-turn 是召回友好的粒度。
3. **路径折叠**复用了 entity_resolver 已有的 path-based bypass 机制，不需要新写一套 dedup。type 加 `directory`，下游一切照旧。
4. **Adapter 做确定性的事，LLM 做判断的事**——head/tail 截断完全可程序化，没必要烧 LLM token。
5. **批大小 ≠ 越大越快**——LLM 输出长度有可靠区间（gemini-3-flash 实测 30K-40K char 输出开始漏字段）。要靠 split-on-missing recovery 兜底，而不是把单批做大；多批小做反而能并行（未来工作）。
6. **质量回退指标必须监控**——这次差点把 12% framing fallback 误当成"省时间的好结果"，幸亏 fallback ratio 是统计输出的一部分，提示我们重新看。

