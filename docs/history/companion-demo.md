> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Vibecoding Companion

> 让 AI coding agent 像一个**持续合作的同事**,而不是每次会话都从零开始的陌生人。

---

## 你为什么需要它

每次开新 Claude Code session,agent 都不知道:

- 我说"研发记录文档",到底指仓库里哪份文件
- 这个文件之前改过哪些事、每次改是为了什么
- 给新 agent / 新协作者讲项目背景,得手工捏一段综述
- 我现在的提议是不是和最近确立的方向冲突
- 某个 feature 横跨多个 session 演化,各 session 各做了什么
- 同一个工具函数 / idiom 在哪几个 project 都用过
- 过去一周做了哪些事(指定时间窗内的真实工作清单)

你只能再贴一遍 CLAUDE.md、再粘对话历史、再口头解释。或者眼睁睁看 agent 重蹈覆辙。

**Companion 让 agent 自动拥有跨会话的工作记忆**——你一开口,过去的相关脉络就在它眼前。

---

## 7 个场景:实测对照(2026-04-22)

> 下方所有 **Companion 实测** 段为真实运行结果,query 直接跑当天约 **5000 turns / 2.6M 字符**对话数据库,展示用户/agent 实际看到的输出。

### 场景 1 · "继续维护 Companion 的研发记录文档"


#### 痛点
用户用描述性概念指代某份文档(如"研发记录"),但仓库中文档众多。agent 需要根据上下文反推具体文件路径,关键词搜索做不到。

#### Companion 实测 (✓ 2026-04-22)

> 当前的文档维护工作集中在项目知识沉淀与 R&D 记录上(包括 Spec、日志与论文大纲维护)。你可以继续编辑 `docs/ac/companion-v2-research-log.md` 和设计文档。请注意相关约束:**分析思考与决策的动态演化过程需要同步更新至 Spec 附录**,并且在设计文档中需增加 Reflexion 等机制的学术来源说明。

#### 点评
query 完全没提任何文件名,只说"研发记录文档"这个概念。答案**准确反推到 `docs/ac/companion-v2-research-log.md`** 并明确引用路径,顺带说出该文档当前的内容范围与下一步要写什么。这种"从描述到具体文件"的反向锚定,需要从过去任务里 agent 实际改过哪些文件去推断,关键词搜索做不到。

---

### 场景 2 · "framing_pass.py 改过哪些事"


#### 痛点
已知文件名查变更,版本控制系统只能给出 commit message,无法呈现每次改动背后的任务上下文与意图。

#### Companion 实测 (✓ 2026-04-22)

> 在当前 Session 中,`framing_pass.py` 主要经历了以下几个方面的修改:
> 1. **路径规范化**:在 `companion-py-b/framing_pass.py` 中处理了跨设备文件路径规范化与关联设计。
> 2. **性能与调优**:在 `companion-py-c/framing_pass.py` 中,进行了动态分批与 Token/字符换算优化、流水线参数压测与 AB 方案调优,并调整了内存相关的学术调研逻辑。
> 3. **消歧逻辑**:在跨 session 消歧任务中,引用了该文件以支持跳过部分类型消歧(SKIP_DISAMBIG)的逻辑。

#### 点评
看到文件名 → 命中两个版本(`-b` / `-c`),把所有相关任务**分类成 3 个变更轴**(路径规范化 / 性能调优 / 消歧逻辑)。git log 不会告诉你"它**也参与了**跨 session 消歧",这种"副作用涉及别的工作"的关联,需要文件 ↔ 任务双向链接才看得到。

---

### 场景 3 · "总结一下 companion 项目"


#### 痛点
项目演化跨数十 session,每次给新 agent 注入背景、向协作者介绍、或阶段性复盘时,都得重新捏一段综述。手工写既费时,又难保覆盖完整、措辞统一。

#### Companion 实测 (✓ 2026-04-22)

> Companion(也被称为 Yanmo)是一个基于知识图谱和 RAG 架构的 AI 辅助项目,目前已在多个 session 中进行了从概念调研到独立版本重构的完整开发。架构方面,它采用独立的 Python 后端(`companion-py-c`)与 Tauri 结合,实现了基于任务树(Task Tree)的增量同步、双时态 KG 建模以及层次化的约束系统(Hierarchical Constraints)。核心功能深度整合了 Agentic RAG 流程,不仅支持多策略的语义检索和 Bundle 工具展开,还提供了智能路径关联与总结双模式(Brief/Summarize)输出。目前 MVP 阶段已进入大规模数据集验证与性能调优环节。

#### 点评
一段精炼综述涵盖**别称(Yanmo)、架构(Python+Tauri)、核心特性(任务树/双时态 KG/Agentic RAG/Bundle 展开/双模式总结)和当前阶段(MVP 大规模验证)**。一段话能直接复制粘贴给新 agent / 协作者用,免手工综述。值得注意的是它把 **Yanmo 老代号 → 当前实现** 串成一个项目演化叙事,而不是当成两个独立项目展示。

---

### 场景 4 · "把 L1 batch 调大到 200 turns 怎么样"


#### 痛点
用户的新提议可能与项目近期已确立的方向冲突,但 agent 通常会照办,缺乏基于历史决策的预警能力。

#### Companion 实测 (✓ 2026-04-22)

> ❌ 不太建议直接将 L1 batch 调大到 200 turns。在之前的超大 Session 处理优化中明确确立了约束:**"因同步复杂度提升,需减小 Batch 大小"**。此外,目前的测试和验证流程倾向于"先跑通小档(99-turn)验证质量后再启动全量大档"。如果单次 batch 过大,不仅会增加同步与拆分的复杂度,还可能更容易触发处理卡死或 fail-fast 失败丢弃逻辑。

#### 点评
**直接说"❌ 不太建议"** —— 不是中立列上下文让用户自己判,而是基于**历史约束主动给立场**。同时给出 3 条理由:已确立约束(需减小 batch)/ 验证流程(先小档后大档)/ 风险机制(同步复杂度 + fail-fast)。这种**关联推理 + 主动反对**是简单关键词召回拿不出的。

---

### 场景 5 · "OpenTelemetry 集成在哪些 session 做过"


#### 痛点
某 feature 横跨多个 session 演化,需要分别列出每个 session 各自承担的工作角度,而非一锅煮。

#### Companion 实测 (✓ 2026-04-22)

> 记录中**没有直接提及"OpenTelemetry"的集成**。不过,关于 Telemetry(遥测与可观测性)的跨平台对齐和优化在 session session-004 中进行过(如 Mac 端的 Telemetry 事件埋点对齐),并且在 session session-002 中对 `TelemetryService.swift` 进行了解耦和流水线依赖拆分。

#### 点评
**主动诚实降级**:query 里的 "OpenTelemetry" 字面**不在知识库**,但 agent 没编造,而是**降级到语义最近的"Telemetry"工作**——给出两个具体 session(session-004 跨平台对齐 / session-002 TelemetryService 解耦)和文件路径(`TelemetryService.swift`)。这种**"找不到字面词时,主动降到语义近义"**的能力,关键词检索完全做不到。

---

### 场景 6 · "lock_or_poison 在哪些项目里用了"


#### 痛点
同一代码 idiom (如某个工具函数) 可能跨多个 project 出现,人工需要 grep 多 repo 并逐处看上下文,才能拼出完整使用图景。

#### Companion 实测 (✓ 2026-04-22, ⚠ 部分命中)

> **虽然知识库中没有直接以 lock_or_poison 命名的具体记录**,但在 AiDictation 项目的多个并发重构任务中提及了相关的锁机制与状态中毒(Poisoning)预防逻辑。主要涉及:
> - (1) 在 **Action 引擎重构**中,通过 Repolish 单例化与状态机重置来防止逻辑中毒
> - (2) 在**音频采集模块**,使用非阻塞的停止流程(No-wait Stop)和超时机制来规避死锁
> - (3) 在 **API 同步**中引入细粒度重试和流式调用,以解决在高频请求下的并发死锁问题

#### 点评
**最值得点赞的是诚实**: 主动承认"知识库中没有直接命名的记录" —— 不编造、不强行扯关系。然后**降级**到相关近义工作 —— 都是锁机制 / 防中毒 / 死锁预防。这种"yes-but" + "降级到相关上下文"的模式,比强行编造一个不存在的用例好得多。

---

### 场景 7 · "总结过去 1 周做的 10 件事"


#### 痛点
周报、站会需要按时间窗口盘点近期工作,人工维护 TODO 文档既容易遗漏,又难判断哪些工作落在指定时间窗内。

#### Companion 实测 (✓ 2026-04-22)

> 过去一周的工作主要集中在语义检索迭代与 Companion MVP 的完善上:
> 1. 深入迭代了检索交互,设计了 Bundle 展开与 Tool-use Loop,并实现了当前 Session 最近任务的上下文注入。
> 2. 实现了基于 tree 特性的双模式总结(Brief/Summarize)与路径 context 输出。
> 3. 补全了 L1 路径定位功能并启动了 Adapter 对齐重构。
> 4. 提升了 UI 交互,实现了消息计数进度条与自动刷新逻辑。
> 5. 推进了项目知识沉淀,维护了 Spec、日志与论文大纲。
> 6. 进行了大规模数据集验证,尝试了全量数据的重同步测试。

#### 点评
两点亮点:

- **时间窗口被准确理解**:精确按"过去 1 周"过滤,跨度更早的工作不会混进来。
- **不为了凑数而虚构**:用户要 10 件,1 周窗内真实工作只到 6 件,就**老实给 6 件**,不编造、不重复拆分。"诚实降级"比强行凑满更可靠。

---

## 实测规模(28 sessions / ~5000 turns / 2.6M chars)

- **28 个 session** 全部纳入(自 2026-03 起约 30 天)
- **~4900 dialogue turns**, **~2.6M chars** 用户/agent 对话内容
- 实体数 **2836 个**(2362 nodes,1460 embedded,3098 edges)

| 操作 | 时长 | 吞吐 |
|---|---|---|
| 全量 sync (~5000 turns / 2.6M chars) | ~100 min,fallback 0.05% | ~50 turn/min,~26K char/min |
| 增量 sync (单 session,有 cache) | ~30s-2min | – |
| 检索 query | 平均 11s (5-7s 简单,13-18s 复杂) | – |

---

## 下一步工作

### 1. 优化性能与质量

当前规模 **~5000 turns / 2.6M 对话字符**,首次建图 ~100min,检索 query 平均 ~12s。后续优化方向:

- **精细化 L1 / L2 prompt**:控制每层 LLM 的输出 schema 与判定边界,减少 rule drift,提升提取准确率
- **代码 identifier 识别能力**:目前对纯文件名 (e.g. `framing_pass.py`) 已能命中,但函数名 / 类名 / 类型名等代码标识符召回较弱,后续加 identifier 索引

L1: unit- agent+user+agent -> unit + files + content
L2: goal/task align, current scope
retrive: lit+file_seach+identifier_search

### 2. 多 agent 支持
目前只支持 Claude Code 的 session。计划接入更多 coding agent:
- Cursor / Codex / Cline / Continue 等的对话日志格式适配
- 不同 agent 的工作合并到同一知识图谱,跨 agent 共享决策与约束

### 3. 多设备同步
目前知识库本地存储,单设备使用。计划:
- 多设备的 session 历史同步聚合 (笔记本 + 工作站 + 服务器)
- 同一项目在多机的工作上下文统一,无论换到哪台设备 agent 都能接续
- 数据同步通道 + 跨设备实体去重 / 合并

---

> **过去你跟 agent 的所有工作,agent 自己记得了。**
