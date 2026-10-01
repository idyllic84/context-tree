> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Vibecoding Companion — 调研与设计

> 作为用户输入层，跨 session、跨 agent、跨项目，为 vibecoding 提供上下文增强。
> 多平台：macOS (AiDictation.Mac) + Windows (AiDictation.Desktop)
> 技术实现详见 [companion-technical.md](companion-technical.md)
>
> **Scope**：仅从**用户输入内容**中理解用户的习惯、决策和历史。不分析代码、文档或项目结构——那些需要额外 context，不在本产品范围内。知识图谱的全部数据来源是用户说过的话和 agent 的文件操作记录（仅文件名，不含内容）。

## 一、Executive Summary

AI coding agent（Claude Code、Copilot、Gemini CLI、Codex CLI）正在成为开发者的核心工具，但每个 agent 都是信息孤岛：**compact 后遗忘决策、跨 agent 上下文不共享、跨 session 知识不可检索**。

Yanmo 利用其作为**用户输入层**的独特数据位置，构建本地 GraphRAG 知识图谱，实现跨 session、跨 agent、跨项目的上下文增强。语音输入是入口，知识图谱是核心，跨 agent 统一是壁垒。

**三个独占差异化**（所有竞品均不具备）：

| 差异 | 为什么竞品做不到 |
|------|----------------|
| **跨 Agent 统一图谱** | Yanmo 作为输入层天然经手所有 agent 的用户输入，数据位置优势不可复制 |
| **语音 + 知识图谱热词** | 没有竞品把语音输入和知识图谱结合 |
| **用户可控注入** | 竞品通过 hook/MCP 自动注入，用户无法看到和选择 |

---

## 二、市场机会

### 社区痛点（2026 年 3-4 月调研）

> 来自 GitHub Issues、Reddit、Hacker News 近一个月的真实反馈。

**Agent 质量退化**：AMD AI 团队分析 6,852 session，思考深度下降 75%（2,200→560 字符），"懒行为"从 0 激增到 173 次/17 天。用户纠错频率 ↑68%。

**Token / 费用危机**：Codex CLI #14593（307+ 评论）是社区最热 issue。AMD 团队缓存 bug 导致费用从 $345→$42,121/月（122 倍）。用户跨 session 重复解释同一约束，agent 每次当新信息处理。

**Context 遗忘**：compact 压缩比 22,000:1,400，决策理由和被否方案完全消失。用户描述为 *"Claude isn't getting dumber. It's getting amnesia."*

**跨工具孤岛**：开发者在 Cursor/Claude/Copilot/Windsurf 间频繁切换，上下文全丢。在 Copilot 讨论的方案到 Claude 要重新说一遍。

**Vibecoding 深层问题**：3-4K 行 AI 代码后开发者失去对代码库的理解。AI 完成 60%，剩余 40% 最难。

---

## 三、竞品分析

### 已有解决方案（不做）

文件 diff、检查点回滚、session 管理 — VS Code 扩展完整覆盖。

### 知识图谱 / 持久记忆竞品

| 工具 | 跨 Agent | 用户可控 | 依赖 |
|------|---------|---------|------|
| [Lattice](https://jameslee.blog/) | ❌ 仅 Claude | ❌ | DuckDB |
| [Claude Graph Memory](https://mcp.market/) | ❌ 仅 Claude | ❌ | Neo4j |
| [Graph Sense](https://github.com/faraazahmad/) | ❌ 仅 Claude | ❌ | Neo4j |
| [Obsidian Mind](https://github.com/breferrari/obsidian-mind) | ⚠️ 各自独立 | ❌ | Obsidian |
| **我们** | **✅ 统一图谱** | **✅ 用户勾选** | **零依赖** |

**所有竞品共同局限**：只服务单个 agent、agent 自动注入用户不可控、需要额外基础设施。

---

## 四、核心定位

> **我们不监控 agent，不替代 agent，不分析代码。我们从用户说过的话中理解用户的习惯、决策和历史，增强跨域表达。**

知识图谱的数据来源**仅限**：
- 用户对 agent 说的话（`type: "human"` 消息）
- Agent 操作了哪些文件（仅文件名，不读内容）

**不在范围内**：代码分析、文档解析、项目结构理解、AST 分析——这些是 agent 自身的能力，不是输入层该做的。

Session 内的模糊表达（"把那个 bug 修了"），agent 自己能理解。我们的价值在于从用户历史输入中提取**agent 看不到的跨域上下文**：

| 场景 | 谁来处理 | 原因 |
|------|---------|------|
| "修那个 bug"（session 内） | agent 自己 | agent 有上下文 |
| "用上次 Copilot 的方案" | **我们** | agent 看不到其他 agent |
| "继续昨天的任务" | **我们** | agent 看不到其他 session |
| "跟 ProjectA 一样处理" | **我们** | agent 看不到其他项目 |

```
用户："用上次 Copilot 讨论的方案"
    │
    ▼
Yanmo（检索知识图谱 → 面板展示 → 用户勾选 → 拼接上下文）
    │
    ▼
发送给 Claude："采用 LRU + 512MB 上限的方案（之前在 Copilot 中讨论确定）"
```

---

## 五、产品方案

### 架构

```
┌───────────────────────────────────────────────────────────┐
│                     AiDictation App                        │
│                                                           │
│  输入（语音/键盘）                                          │
│       → 检索知识图谱（FTS5 + 图遍历）                       │
│       → 相关信息面板（用户勾选）                              │
│       → 拼接上下文 → 注入 agent                             │
│                                                           │
│  知识图谱（Markdown + SQLite 索引）                         │
│       ← Session 完成后自动/手动提取                          │
│       ← 用户可用 Obsidian 手动编辑（可选）                   │
└───────────────────────────────────────────────────────────┘
```

### 功能矩阵

| 优先级 | 功能 | 周期 | 竞品 |
|--------|------|------|------|
| **P0** | 跨域上下文意图增强（核心） | 2-3w | 无（跨 agent 统一） |
| **P0** | 语音输入（知识图谱热词 + 润色） | 1-2w | `/voice`（无热词） |
| **P0** | 跨 Session/Agent 知识图谱构建 | 2-3w | 无 |
| **P1** | 用户输入历史搜索 | 1-2w | 无 |
| **P1** | 重复沟通检测 → 建议固化到 CLAUDE.md | 1w | 无 |
| **P2** | Agent 质量趋势（纠错频率监控） | 1-2w | 无 |
| **P2** | MCP / Hook / Skill 集成 | 1-2w | 无 |

### 交互模式

用户输入时，实时检索知识图谱，展示在侧边面板中，**用户点选要附加的条目**再发送：

```
┌─ 相关信息面板 ──────────────────────────────────┐
│                                                │
│  📋 跨 Session                                  │
│  ☐ [昨天] SettingsService 缓存：LRU + 512MB     │
│                                                │
│  📋 跨 Agent                                    │
│  ☐ [Copilot 上周] 缓存策略对比：LRU 最适合       │
│                                                │
│  📋 跨项目                                      │
│  ☐ [ProjectA] 类似的缓存实现                     │
│                                                │
└────────────────────────────────────────────────┘
```

### 核心功能说明

**重复沟通检测**：用户在 3 个 session 中都说了"不要用 SwiftData"，提示固化到 CLAUDE.md。痛点来源：token 浪费是社区最热话题。

**Agent 质量趋势**：从知识图谱统计用户纠错频率（"不对"、"回滚"出现次数）和 agent 的 read-before-edit 比率，给出客观退化指标。痛点来源：AMD 分析 6,852 session 发现思考深度下降 75%。

---

## 六、效果展示（Demo 场景）

> 详细 demo 脚本和技术准备见 [companion-demo.md](companion-demo.md)

6 个场景，5 个 MVP（2 周）即可演示：

**场景一：主动矛盾预警** ✅ MVP
用户正在输入"用 SwiftData..."，系统在发送前主动提醒："你 4/9 决定过不用 SwiftData（原因：macOS 15 NULL 崩溃）"。不是事后找回，是事前拦截。

**场景二：跨 Agent 桥接** ⚠️ 需 Copilot adapter
用户说"用上周 Copilot 讨论的方案"，系统从 Copilot session 中找到决策（指数退避 + jitter），附加给 Claude。Claude 自己完全看不到 Copilot 的对话。

**场景三：决策演化时间线** ✅ MVP
用户问"数据库方案改过几次？"，系统返回完整演化链：JSON 文件(2月) → SwiftData(3月) → raw SQL(4月) → 考虑替换 GRDB(待定)，每步附带用户当时说的原因。双时间模型的独特能力。

**场景四：跨 Session 话题汇总** ✅ MVP
用户问"之前讨论过哪些性能问题？"，系统自动汇总分散在 3 个 session、2 个 agent 中的讨论——启动耗时、体积优化、缓存策略。用户自己都没意识到这些话题是相关的。

**场景五：重复沟通检测** ✅ MVP
用户第三次在不同 session 说"不要用 SwiftData"，系统提示"你已在 3 个 session 说过同一约束，建议一键写入 CLAUDE.md"。直击 token 浪费痛点。

**场景六：语音热词** ✅ MVP
从知识图谱 term 节点提取项目术语注入语音识别。"HistoryService" vs "history service"——精确的 PascalCase 让 agent 直接定位代码。

---

## 七、技术方案概述

> 详细实现见 [companion-technical.md](companion-technical.md)

### 为什么选 GraphRAG

我们的场景是**多跳关联检索**：用户说"缓存" → LRU 讨论 → Copilot 性能对比 → 512MB 上限决策。研究数据支持图谱在此场景大幅领先语义搜索：

| 查询类型 | GraphRAG | 语义搜索 | 来源 |
|---------|---------|---------|------|
| 复杂关联查询 | **80%** | 50.8% | Lettria/AWS 2025 |
| 多跳推理（5+ 实体） | 稳定 | ≈ 0% | FalkorDB 2025 |

### 存储：Markdown + SQLite 索引

**Markdown 是 source of truth**（人类可读、可编辑、可 git 追踪、兼容 Obsidian），SQLite 只是加速检索的索引层，可随时从 markdown 重建。

知识图谱存储为带 `[[wikilinks]]` 的 markdown 文件，用户可选择用 Obsidian 打开同一目录获得图谱可视化——零集成成本。

### 知识提取管线（7 步）

```
Session 不活跃 ≥1h / 手动触发
  → Step 1: 读取 JSONL，增量去重（规则）
  → Step 2: LLM 提取实体+关系（一次调用，~$0.001/session）
  → Step 3: 实体消解——跨 session 去重（embedding + LLM）
  → Step 4: 矛盾检测 + 双时间模型（决策会过期）
  → Step 5: 写 Markdown
  → Step 6: 更新 SQLite 索引
  → Step 7: 社区检测（定期，生成话题聚类摘要）
```

关键设计借鉴：
- **实体消解**（[Graphiti](https://arxiv.org/abs/2501.13956)）：三阶段消解，"SwiftData" = "Swift Data" 自动合并
- **关系解释**（[CLARE](https://doi.org/10.3390/info16100866)，82.1% 准确率）：要求 LLM 解释推理过程，提升关系质量
- **双时间模型**（Graphiti）：决策会被推翻，旧边标记失效而非删除，保留演化历史
- **小模型可行**（[LightKGG](https://arxiv.org/)）：Haiku 级别模型达 GPT-4o 96% 效果

### 成本

| 指标 | 数值 |
|------|------|
| 单 session 费用 | ~$0.003 |
| 单 session 处理时间 | ~10-15s（后台异步） |
| 月费用（中度使用） | < $1 |

### 跨 Agent Session 数据

所有主流 agent 的会话数据均存储在本地磁盘（JSON/JSONL），全部可读取：

| Agent | 格式 |
|-------|------|
| Claude Code | `~/.claude/projects/{path}/{session}.jsonl` |
| VS Code Copilot | `~/Library/.../workspaceStorage/{hash}/chat sessions/*.json` |
| Gemini CLI | `~/.gemini/tmp/{hash}/chats/session-*.json` |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |

每个 agent 只需一个 adapter 实现统一的 SessionRecord 接口。

### 多平台复用

| 模块 | 复用方式 |
|------|---------|
| Agent Adapter / KnowledgeStore / LLM 提取 | 共享逻辑 |
| 面板 UI | SwiftUI / WPF 各自实现 |
| 文字注入 | macOS CGEvent / Windows SendKeys |

---

## 七、实施计划

### MVP（2 周）

简化管线为 3 步（读 JSONL → LLM 提取 → 存储），跳过实体消解、矛盾检测、社区检测。

| 周 | 内容 | 产出 |
|----|------|------|
| **Week 1-2** | Claude adapter + LLM 提取 + SQLite + 面板 UI | 可演示场景一、三、四、五、六（5/6） |
| **Week 3** | Copilot adapter | 全部 6 个场景可演示 |
| **Week 4-6** | 完整管线（实体消解 + 矛盾检测 + 社区检测） | 生产质量 |

### 排除列表

| 功能 | 排除原因 |
|------|---------|
| 死循环检测 / 架构图谱 | agent 侧能力 |
| 文件 diff / 检查点 / Session 管理 | VS Code 完整覆盖 |

---

## 八、参考

### 学术研究
- [CLARE](https://doi.org/10.3390/info16100866) — KG 构建 82.1% 准确率（vs GraphRAG 48.3%）
- [Graphiti/Zep](https://arxiv.org/abs/2501.13956) — 时序 KG，token 115K→1.6K，LongMemEval +18.5%
- [Contextual Memory Graphs](https://www.researchgate.net/publication/396444634) — 上下文准确率 +42%，token -51.6%
- [KGGen (NeurIPS 2025)](https://openreview.net/forum?id=YyhRJXxbpi) — MINE benchmark
- [LightKGG](https://arxiv.org/) — 小模型达 GPT-4o 96% 效果
- [LightRAG (EMNLP 2025)](https://github.com/HKUDS/LightRAG) — 双层检索
- [Lettria](https://www.lettria.com/blogpost/graphrag-benchmark-2025) / [FalkorDB](https://www.falkordb.com/blog/graphrag-vs-rag/) — GraphRAG vs Vector RAG

### 社区痛点
- [GitHub #23751](https://github.com/anthropics/claude-code/issues/23751) — Compact 遗忘
- [Codex #14593](https://github.com/openai/codex/issues/14593) — Token 不透明（307+ 评论）
- [Gemini #23858](https://github.com/google-gemini/gemini-cli/issues/23858) — Plan mode 被绕过

### 工具
- [EmbedKit](https://github.com/klu-ai/EmbedKit) — Swift 本地 embedding
- [GRDB FTS5](https://github.com/groue/GRDB.swift/blob/master/Documentation/FullTextSearch.md)
- [Obsidian Mind](https://github.com/breferrari/obsidian-mind)
- [Lightweight GraphRAG with SQLite](https://dev.to/stephenc222/how-to-build-lightweight-graphrag-with-sqlite-53le)
