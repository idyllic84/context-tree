> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Vibecoding Companion — 技术实现设计

> 本文档包含 [Vibecoding Companion](claude-code-companion.md) 的详细技术实现，包括存储 schema、提取管线、prompt 设计、检索算法等。
>
> **Scope**：所有知识提取仅基于**用户输入内容**（用户对 agent 说的话）+ **agent 文件操作记录**（仅文件名）。不读取代码内容、项目文档或其他 context。

---

## 一、技术选型：本地 GraphRAG

### 为什么是 GraphRAG 而不是纯语义搜索

| 查询类型 | GraphRAG 准确率 | 纯语义搜索准确率 | 来源 |
|---------|----------------|-----------------|------|
| 复杂关联查询 | **80%** | 50.8% | [Lettria/AWS 2025](https://www.lettria.com/blogpost/graphrag-benchmark-2025) |
| 技术规范查询 | **90.6%** | 46.9% | Lettria（航空领域） |
| 多跳推理（5+ 实体） | 稳定 | **≈ 0%** | [FalkorDB 2025](https://www.falkordb.com/blog/graphrag-vs-rag/) |
| 多事实跨文档聚合 | **47.6%** | 35.1% | [WildGraphBench 2026](https://arxiv.org/abs/2502.07186) |

我们的场景本质是**多跳关联检索**：用户说"缓存" → LRU 讨论 → Copilot 性能对比 → 512MB 上限决策。语义搜索只能找到第一跳。

### 存储设计：Markdown + SQLite 索引

**Markdown 文件是 source of truth**——人类可读、可编辑、可 git 追踪。SQLite 只是加速检索的索引层。

```
~/Library/Application Support/Yanmo/brain/
├── sessions/
│   ├── claude/
│   │   ├── 2026-04-10-otel-design.md
│   │   └── 2026-04-09-swiftdata-migration.md
│   ├── copilot/
│   │   └── 2026-04-07-websocket-reconnect.md
│   └── gemini/
├── decisions/
│   ├── no-swiftdata.md
│   ├── otel-three-signals.md
│   └── grdb-replacement.md
├── topics/
│   ├── caching.md
│   └── ui-freeze.md
├── problems/
│   ├── swiftdata-null-crash.md
│   └── observableobject-freeze.md
└── terms.md
```

#### Markdown 格式

```markdown
---
type: decision
date: 2026-04-09
agent: claude-code
project: AiDictation.Mac
tags: [database, swiftdata, sqlite]
---

# 不用 SwiftData，用 raw SQL

## 决策
数据库持久化用 raw SQL（通过 GRDB），不用 SwiftData ORM。

## 原因
SwiftData 在 macOS 15 上有 NULL 列映射崩溃问题。

## 关联
- [[swiftdata-null-crash]] — 触发此决策的问题
- [[2026-04-09-swiftdata-migration]] — 实施此决策的 session
- [[grdb-replacement]] — 后续考虑进一步替换 GRDB

## Agent 文件操作
- Edit: HistoryService.swift, DatabaseService.swift
```

#### Obsidian 兼容（可选，零集成成本）

知识库目录本身就是合法的 Obsidian vault（markdown + `[[wikilinks]]`）。Yanmo 不依赖 Obsidian，但兼容：

| | 不装 Obsidian | 装了 Obsidian |
|---|---|---|
| 知识提取 + 检索 | ✅ Yanmo 自动 | ✅ 同 |
| 面板展示 | ✅ Yanmo 侧边面板 | ✅ 同 |
| 图谱可视化 | ❌ | ✅ Graph View |
| 手动策展 | ⚠️ 任何文本编辑器 | ✅ 所见即所得 |

Settings 中提供知识库路径配置，用户可指向已有 Obsidian vault 子目录。

### SQLite 索引层

从 markdown 文件自动构建，可随时从 markdown 重建。Schema 融合了 [Graphiti](https://arxiv.org/abs/2501.13956) 双时间模型、[CLARE](https://doi.org/10.3390/info16100866) 关系解释、实体消解别名追踪等调研成果。

```sql
-- 节点表：每个 markdown 文件对应一个节点
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,              -- 文件名（去 .md）
    type TEXT NOT NULL,               -- session / decision / topic / term / problem / solution / file
    title TEXT NOT NULL,
    content TEXT,                     -- markdown 正文（用于 FTS 索引）
    file_path TEXT,                   -- 完整文件路径
    metadata TEXT,                    -- frontmatter JSON（agent, project, date, tags）

    -- 时序字段（借鉴 Graphiti 双时间模型）
    valid_from TEXT,                  -- 事实开始为真的时间（ISO 8601）
    invalid_from TEXT,                -- 事实不再为真的时间（NULL = 仍有效）

    -- 实体消解（借鉴 Graphiti 三阶段消解）
    canonical_id TEXT,                -- 合并后指向的规范节点 ID（NULL = 自身即规范）
    aliases TEXT,                     -- JSON 数组：被合并的其他表述 ["Swift Data", "SD"]

    -- 语义搜索（借鉴 CLARE + EmbedKit）
    embedding BLOB,                   -- 可选：语义向量

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 边表：关系，含双时间模型 + 解释
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    relation TEXT NOT NULL,           -- decided_in / related_to / caused_by / solved_by / ...
    direction TEXT DEFAULT 'forward', -- forward / reverse / none（借鉴 CLARE）
    explanation TEXT,                 -- 关系解释（借鉴 CLARE：解释提升质量）

    -- 双时间模型（借鉴 Graphiti）
    created_at TEXT DEFAULT (datetime('now')),  -- 系统记录时间
    expired_at TEXT,                            -- 系统标记失效时间（NULL = 仍有效）
    valid_from TEXT,                            -- 事实开始为真
    invalid_from TEXT,                          -- 事实不再为真（NULL = 仍为真）

    -- 来源追踪
    session_id TEXT,                  -- 产生此关系的 session 节点 ID

    UNIQUE(source_id, target_id, relation, valid_from)
);

-- 全文检索索引
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    title, content,
    content=nodes,
    tokenize='unicode61'
);

-- 查询加速索引
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_canonical ON nodes(canonical_id) WHERE canonical_id IS NOT NULL;
CREATE INDEX idx_nodes_valid ON nodes(valid_from, invalid_from);
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_valid ON edges(valid_from, invalid_from);
CREATE INDEX idx_edges_session ON edges(session_id);
```

**与初版 schema 的变化**：

| 新增字段 | 来源 | 解决什么问题 |
|---------|------|------------|
| `nodes.valid_from/invalid_from` | Graphiti 双时间模型 | 决策会过期——"最初用 SwiftData，后来改 raw SQL" |
| `nodes.canonical_id` | Graphiti 实体消解 | 合并后的节点指向规范节点，查询时自动跟随 |
| `nodes.aliases` | Graphiti 实体消解 | 记录被合并的表述，搜索"Swift Data"也能命中"SwiftData" |
| `edges.direction` | CLARE 方向性关系 | `caused_by` 有方向，`related_to` 无方向 |
| `edges.explanation` | CLARE 关系解释 | 解释为什么有关系，本身也是有价值的知识 |
| `edges.valid_from/invalid_from` | Graphiti 双时间模型 | 关系也会过期——旧边标记失效而非删除 |
| `edges.expired_at` | Graphiti 双时间模型 | 系统层面的失效（区别于事实层面的 invalid_from） |
| `edges.session_id` | 自研 | 追踪关系来自哪个 session，支持溯源 |

### 节点类型

| type | 说明 | 来源 | 时序特性 | 示例 |
|------|------|------|---------|------|
| `session` | 一次 agent 会话的摘要 | LLM 提取 | 只有 valid_from（创建时间） | "2026-04-10 OTel 遥测设计" |
| `decision` | 用户做的技术决策 | LLM 提取 | **valid_from + invalid_from**（决策会被推翻） | "不用 SwiftData，用 raw SQL" |
| `topic` | 跨 session 的话题聚合 | LLM 提取 | 只有 valid_from | "缓存策略"、"UI 冻结" |
| `term` | 项目术语 | LLM 提取 | **aliases**（多种表述合并） | "RecordingPipeline" |
| `problem` | 遇到的问题 | LLM 提取 | valid_from + **可能 invalid_from**（问题被解决） | "SwiftData NULL 列崩溃" |
| `solution` | 解决方案 | LLM 提取 | valid_from | "替换为 raw SQLite 读取" |
| `file` | Agent 操作过的文件 | 规则提取 | 只有 valid_from | "HistoryService.swift" |

### 关系类型

| relation | 语义 | 方向 | 时序性 | 示例 |
|----------|------|------|--------|------|
| `decided_in` | 决策在哪个 session 产生 | forward | 不过期 | decision → session |
| `related_to` | 话题关联 | none | 不过期 | topic ↔ topic |
| `caused_by` | 问题的原因 | forward | 不过期 | problem → problem |
| `solved_by` | 问题的解决方案 | forward | 不过期 | problem → solution |
| `mentioned_in` | 术语/话题在 session 中出现 | forward | 不过期 | term → session |
| `uses` | 项目使用某技术 | forward | **会过期** | project → term |
| `superseded_by` | 旧决策被新决策替代 | forward | 不过期 | old_decision → new_decision |
| `read_in` / `edited_in` / `created_in` | Agent 文件操作 | forward | 不过期 | file → session |

### 检索流程

```sql
-- 用户输入 "缓存" → 匹配节点 → 展开 1-2 跳关联
-- 只返回当前有效的节点和边（排除已过期的）
WITH matched AS (
    SELECT id FROM nodes_fts WHERE nodes_fts MATCH '缓存'
),
-- 合并别名：如果搜到的是被合并的节点，跟随 canonical_id
resolved AS (
    SELECT COALESCE(canonical_id, id) AS id FROM nodes
    WHERE id IN (SELECT id FROM matched)
),
-- 1 跳展开（只取有效边）
one_hop AS (
    SELECT target_id AS id FROM edges
    WHERE source_id IN (SELECT id FROM resolved)
      AND (invalid_from IS NULL OR invalid_from > datetime('now'))
    UNION
    SELECT source_id AS id FROM edges
    WHERE target_id IN (SELECT id FROM resolved)
      AND (invalid_from IS NULL OR invalid_from > datetime('now'))
)
SELECT n.*, e.relation, e.explanation, e.direction
FROM nodes n
LEFT JOIN edges e ON (n.id = e.source_id OR n.id = e.target_id)
WHERE n.id IN (SELECT id FROM resolved UNION SELECT id FROM one_hop)
  AND (n.invalid_from IS NULL OR n.invalid_from > datetime('now'))
  AND (n.canonical_id IS NULL)  -- 排除被合并的节点
ORDER BY n.type, n.valid_from DESC;
```

**检索增强**（相比初版）：
- **别名跟随**：搜到 "Swift Data" → 自动跟随 `canonical_id` 找到 "SwiftData"
- **时序过滤**：默认只返回当前有效的节点和边，排除已过期决策
- **历史查询**：去掉 `invalid_from` 过滤条件即可查看完整演化历史
### 知识提取设计：增量构建管线

综合 [CLARE](https://doi.org/10.3390/info16100866)（82.1% 准确率）、[Graphiti/Zep](https://arxiv.org/abs/2501.13956)（增量更新 + 双时间模型）、[KGGen](https://openreview.net/forum?id=YyhRJXxbpi)（实体聚类去重）的研究成果，构建 6 步增量管线。

#### 管线总览

```
Session 不活跃 ≥1 小时 / 用户手动触发
    │
    ▼
Step 1: 数据提取 + 增量去重 ──────────── 规则
    │
    ▼
Step 2: 实体 + 关系提取 ──────────────── 异步，LLM
    │
    ▼
Step 3: 实体消解（跨 session 去重）───── 异步，embedding + LLM
    │
    ▼
Step 4: 矛盾检测 + 时序管理 ──────────── 异步，LLM
    │
    ▼
Step 5: 写入 Markdown ────────────────── 同步
    │
    ▼
Step 6: 更新 SQLite 索引 ─────────────── 同步
    │
    ▼
Step 7: 社区检测（可选，定期）──────────── 图算法
```

图谱不是一次构建，而是**持续演化**——每次触发增量追加新内容，不重建已有部分。

**触发机制**：

| 方式 | 条件 | 说明 |
|------|------|------|
| 自动 | Session JSONL 不活跃 ≥1 小时 | 后台检测文件 mtime |
| 手动 | 用户点击"同步知识库" | Settings 或面板中的按钮 |

> Session 没有确定的结束时间——用户可能 `/resume` 多次回到同一个 session。因此同一个 session 可能被多次触发处理，Step 1 需要增量去重。

---

#### Step 1: 数据提取 + 增量去重（规则，无 LLM）

**提取**：解析 session JSONL，提取用户消息和文件操作。

**去重**：同一个 session 可能被多次处理（用户 resume 后继续工作，再次触发）。通过记录已处理的消息偏移量避免重复提取：

```
SessionProcessingState {
    session_id: "a3f2-xxxx"
    last_processed_offset: 1247      // JSONL 文件的字节偏移
    last_processed_uuid: "session-006"  // 最后处理的消息 uuid
    processed_at: "2026-04-10T18:30:00Z"
}
```

每次触发时：
```
1. 读取该 session 的 ProcessingState
2. 从 last_processed_offset 开始读 JSONL（跳过已处理部分）
3. 只提取新增的用户消息和文件操作
4. 更新 ProcessingState
```

**无新增消息**（offset 未变化）→ 跳过后续步骤。

**输出**：`SessionDelta { newUserMessages[], newFileOperations[], isFirstProcess: bool }`

- `isFirstProcess = true`：首次处理，Step 2 提取完整 session 摘要
- `isFirstProcess = false`：增量处理，Step 2 只提取新增部分的实体+关系

---

#### Step 2: 实体 + 关系提取（异步，LLM 一次调用）

将 Step 1 的 SessionDelta 发给 LLM。

- **首次处理**（`isFirstProcess = true`）：所有用户消息 + 文件操作一次提取
- **增量处理**（`isFirstProcess = false`）：只发新增消息，但附带已提取的 session_summary 作为上下文

**输入量极小**：用户消息 1000-2000 token/session。Haiku 级别模型即可，成本 < $0.001/session。[LightKGG](https://arxiv.org/) 证明小模型可达 GPT-4o 96% 的效果。

**Prompt**：

```
你是一个知识提取助手。从用户与 AI coding agent 的对话中提取结构化知识。

## 输入

用户消息（时间顺序）：
{user_messages}

Agent 操作的文件：
{file_operations}

## 提取要求

### 实体类型

1. **decision** — 用户明确的决定或约束
   格式：("decision", <标题>, <内容含原因>)

2. **topic** — 讨论的技术话题
   格式：("topic", <标题>, <摘要>)

3. **term** — 代码标识符、框架名、API 名
   格式：("term", <术语>)

4. **problem** — 遇到或讨论的问题
   格式：("problem", <标题>, <描述>)

5. **solution** — 解决方案
   格式：("solution", <标题>, <描述>)

### 关系

格式：("relation", <源>, <目标>, <类型>, <方向>, <解释>)
方向：forward / reverse / none
类型：decided_in, related_to, caused_by, solved_by, mentioned_in

**要求对每个关系解释推理过程**（借鉴 CLARE：解释提升关系质量）。

### 输出 JSON

{
  "entities": [...],
  "relations": [...],
  "session_summary": "一句话概括"
}
```

**只从用户输入提取**：用户消息短、密度高、是意图直接表达。Agent 回复长、冗余，token 成本高。

---

#### Step 3: 实体消解——跨 session 去重（异步，embedding + LLM）

> 借鉴 [Graphiti 三阶段实体消解](https://arxiv.org/abs/2501.13956) + [CLARE 全局消歧](https://doi.org/10.3390/info16100866)

跨 session 积累后，同一概念出现多种表述（"SwiftData" / "Swift Data" / "Apple 的数据持久化"）。不消解则图谱出现重复节点，搜索时遗漏关联。

**三阶段消解**：

```
Stage A: 向量候选搜索
    新实体 embedding → 与已有节点 cosine similarity > 0.80 → 候选集

Stage B: 关键词候选搜索
    新实体 → FTS5 全文搜索已有节点 title + content → 候选集

Stage C: LLM 消歧决策
    候选集为空 → 创建新节点
    候选集非空 → LLM 判断（新实体 + 候选 + 各自上下文）
        → merge（合并到已有节点）/ create（创建新节点）
```

**Coding session 特有挑战**：

| 场景 | 处理方式 |
|------|---------|
| 缩写："HS" = "HistoryService" | Stage B 关键词 + Stage C LLM 理解 |
| 中英混用："历史服务" = "HistoryService" | Stage A embedding 语义匹配 |
| 同名不同义：DatabaseService v1 vs v2 | Stage C LLM 根据上下文区分 + Step 4 双时间模型 |

**成本**：每个新实体一次 embedding + 可能一次 Haiku 调用。一个 session 5-15 个实体，可忽略。

---

#### Step 4: 矛盾检测 + 时序管理（异步，LLM）

> 借鉴 [Graphiti 双时间模型](https://arxiv.org/abs/2501.13956)

**双时间模型**——每条边追踪 4 个时间戳：

| 时间线 | 字段 | 含义 |
|--------|------|------|
| 系统时间 | `created_at` | 系统记录时间 |
| 系统时间 | `expired_at` | 系统标记失效时间 |
| 事实时间 | `valid_from` | 事实开始为真 |
| 事实时间 | `invalid_from` | 事实不再为真 |

**矛盾检测流程**：

```
新关系进入 → 查找同 source + target 的已有关系
    ├─ 无已有 → 直接写入
    └─ 有已有 → LLM 判断是否矛盾
        ├─ 不矛盾（补充）→ 新关系直接写入
        └─ 矛盾 → 旧边 invalid_from=now，新边 valid_from=now
```

**示例**：

```
4月9日: "用 SwiftData"
  → edge: (项目, uses, SwiftData), valid_from=4/9

4月10日: "不用 SwiftData，改 raw SQL"
  → 矛盾检测 → 旧边 invalid_from=4/10，新边 valid_from=4/10

查询 "现在用什么？" → raw SQL ✅
查询 "最初用什么？" → SwiftData ✅（历史保留）
```

**为什么不删除旧边**：决策演化的完整历史是有价值的知识。

---

#### Step 5: 写入 Markdown（同步）

每个新实体/session → markdown 文件。矛盾的旧决策更新 `invalid_from` 和 `superseded_by`。

**命名规则**：
- `sessions/{agent}/{date}-{slug}.md`
- `decisions/{slug}.md`
- `topics/{slug}.md`
- `problems/{slug}.md`
- `terms.md`（汇总，追加）

**Markdown 格式**（含双时间字段）：

```markdown
---
type: decision
date: 2026-04-10
agent: claude-code
valid_from: 2026-04-10
invalid_from:              ← 空 = 仍有效
supersedes: [[use-swiftdata]]
tags: [database, sqlite]
---

# 不用 SwiftData，用 raw SQL

## 决策
数据库持久化用 raw SQL，不用 SwiftData ORM。

## 原因
SwiftData 在 macOS 15 上有 NULL 列映射崩溃。

## 关联
- [[swiftdata-null-crash]] — 触发此决策的问题
- [[2026-04-09-swiftdata-migration]] — 实施的 session
```

---

#### Step 6: 更新 SQLite 索引（同步）

从 Step 5 的 markdown 解析构建索引：

```
1. 解析 frontmatter → nodes 表
2. 扫描 [[wikilinks]] → edges 表
3. 正文 → FTS5 全文索引
4. Step 1 的文件操作 → file 节点 + read_in/edited_in/created_in 边
5. 可选：embedding → nodes.embedding 列
```

**索引可随时从 markdown 重建**——SQLite 不是 source of truth。

**Markdown 编辑同步**：用户用编辑器/Obsidian 修改 `brain/` 下的 .md 文件时，文件变化监听触发重新解析该文件，仅更新 SQLite 索引（不触发 LLM）。

---

#### Step 7: 社区检测（可选，定期）

> 借鉴 [Graphiti 社区子图](https://arxiv.org/abs/2501.13956)（Label Propagation）

当图谱节点积累到一定规模后，用社区检测算法将紧密关联的实体分组，生成高层摘要。

**触发条件**：每 20 个 session 处理后，或用户手动触发。

**算法**：Label Propagation（轻量，不需要预设社区数量，适合增量更新）。

**流程**：

```
1. 在 edges 表上运行 Label Propagation → 每个节点分配 community_id
2. 每个 community 的节点 title + content → LLM 生成摘要
3. 写入 communities 表 + 对应 markdown 文件
```

```sql
CREATE TABLE communities (
    id INTEGER PRIMARY KEY,
    label TEXT,                -- 社区标签（LLM 生成）
    summary TEXT,              -- 社区摘要（LLM 生成）
    node_ids TEXT,             -- JSON 数组：属于该社区的节点 ID
    updated_at TEXT
);
```

**用途**：

| 场景 | 示例 |
|------|------|
| 全局概览 | "这个项目有哪些主要话题？" → 返回社区列表 |
| 长期不碰后恢复 | "OTel 相关的都有什么？" → 返回 OTel 社区摘要 |
| 新人 onboarding | 浏览社区列表 = 项目知识地图 |
| Obsidian 图谱着色 | 按 community 给节点染色，视觉分组 |

**成本**：社区数量通常 5-20 个，每个摘要一次 Haiku 调用。总计 < $0.01/次，几分钟一次。

---

#### 跨 Session 关联（Fallback 机制）

> 借鉴 [CLARE 非共现实体 Fallback](https://doi.org/10.3390/info16100866)

两个实体分别出现在不同 session，从未共现，但可能有关系。

**定期触发**（每 N 个 session 或每天）：

```
1. 找语义相近但无直接边的节点对（cosine > 0.7）
2. 收集各自上下文
3. LLM 判断是否有关系 → 有则创建边
```

**成本控制**：每次最多评估 30 对。

---

#### 方法来源与有效性

| 设计 | 来源 | 效果 |
|------|------|------|
| 领域专用实体类型 | 自研 | — |
| 关系要求解释 | [CLARE](https://doi.org/10.3390/info16100866) | 82.1% 准确率（vs GraphRAG 48.3%） |
| 三阶段实体消解 | [Graphiti](https://arxiv.org/abs/2501.13956) | LongMemEval +18.5%，token 115K→1.6K |
| 双时间模型 + 矛盾检测 | [Graphiti](https://arxiv.org/abs/2501.13956) | 同上 |
| 非共现 Fallback | [CLARE](https://doi.org/10.3390/info16100866) | 同上 |
| 小模型可行性 | [LightKGG](https://arxiv.org/) | 小模型达 GPT-4o 96% |
| 图谱 vs 线性历史 | [CMG](https://www.researchgate.net/publication/396444634) | 准确率 +42%，token -51.6% |
| 交互修正 | CLARE | 15 分钟提升 22.7%（Obsidian 兼容 = 天然修正界面） |

---


## 二、数据基础：Agent Session 格式

### 跨 Agent Session 存储

所有主流 coding agent 的会话数据都存储在本地磁盘，格式均为 JSON/JSONL，全部可读取：

| Agent | 存储路径 | 格式 |
|-------|---------|------|
| Claude Code | `~/.claude/projects/{path}/{session}.jsonl` | JSONL |
| VS Code Copilot | `~/Library/.../workspaceStorage/{hash}/chat sessions/{session}.json` | JSON |
| Gemini CLI | `~/.gemini/tmp/{hash}/chats/session-*.json` | JSON |
| Codex CLI | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | JSONL |

Windows 路径：Claude/Gemini/Codex 为 `%USERPROFILE%\.{agent}\...`，Copilot 为 `%APPDATA%\Code\...`。

### Claude Code Session 格式

```json
// ~/.claude/sessions/{pid}.json — 活跃 session 元数据
{
  "pid": 68370,
  "sessionId": "session-005-...",
  "cwd": "/home/example/Repos/MyProject",
  "startedAt": 1775704632983,
  "kind": "interactive"
}

// ~/.claude/projects/{path}/{session}.jsonl — 对话记录，每行一条
{
  "uuid": "session-006-...",
  "parentUuid": null,
  "type": "human | assistant | tool_result",
  "content": "消息内容",
  "timestamp": "2026-04-09T07:38:36.717Z",
  "sessionId": "session-005-..."
}
```

### 活跃 Session 检测

```
1. 遍历 ~/.claude/sessions/*.json
2. 检查 PID 存活：macOS kill(pid,0) / Windows OpenProcess()
3. 找到对应 JSONL → 按 mtime 排序 → 最新的即为活跃 session
```

实时监听：macOS `FSEvents` / Windows `FileSystemWatcher`，监听 JSONL 写入事件。

### 适配架构

```
AiDictation App
    ├── ClaudeAdapter    → ~/.claude/projects/*.jsonl
    ├── CopilotAdapter   → ~/Library/.../chat sessions/*.json
    ├── GeminiAdapter    → ~/.gemini/tmp/*/chats/session-*.json
    ├── CodexAdapter     → ~/.codex/sessions/**/*.jsonl
    │
    ├── 统一 SessionRecord 模型
    │   { agent, sessionId, timestamp, userInputs[], toolCalls[] }
    │
    └── KnowledgeStore → 知识图谱
```

每个 adapter 只需实现一个接口：解析该 agent 的文件格式 → 输出统一的 `SessionRecord`。

---

## 三、实施计划

### 工程量评估

| 模块 | 时间 | 说明 |
|------|------|------|
| KnowledgeStore（nodes + edges + FTS5） | 2-3 天 | SQLite + GRDB FTS5 |
| SessionWatcher + 文件操作提取 | 2-3 天 | FSEvents + JSONL 解析 + tool_result 规则提取 |
| **LLM 知识提取 prompt** | **1-2 周** | **核心工作量**：prompt 设计 + JSON 解析 + 异步调度 |
| 图遍历检索 | 1-2 天 | CTE 递归查询 |
| 相关信息面板 UI | 3-5 天 | SwiftUI 侧边面板 |
| 上下文拼接 + 注入 | 1-2 天 | 文本拼接 + 键盘模拟 |
| EmbedKit 语义搜索（可选） | 2-3 天 | 混合检索增强，非 MVP 必需 |
| **总计 MVP** | **~3-4 周** | |

### 阶段规划

**第一阶段（MVP，3-4 周）**：GraphRAG + 语音
- KnowledgeStore（Markdown + SQLite 索引）
- SessionWatcher（Claude adapter 先行）
- LLM 知识提取 prompt
- 相关信息面板 UI
- 语音热词注入

**第二阶段（5-8 周）**：跨域能力
- Copilot / Gemini / Codex adapter
- 重复沟通检测
- Agent 质量趋势
- 输入历史搜索 UI
- MCP 工具

**第三阶段（8+ 周）**：生态集成 + 多平台
- Hook/Skill/Plugin 打包
- Windows 版复用核心逻辑 + 平台适配
- 跨设备知识同步

### 多平台复用

| 模块 | 复用方式 |
|------|---------|
| Agent Session Adapter | 路径不同，解析逻辑相同 |
| KnowledgeStore (SQLite) | schema 一致 |
| LLM 知识提取 | 同一套 prompt |
| 面板 UI | SwiftUI / WPF 各自实现，共享交互设计 |
| 文字注入 | macOS CGEvent / Windows SendKeys |
| 文件监听 | macOS FSEvents / Windows FileSystemWatcher |

---

## 四、核心叙事

> **"Yanmo 是 vibecoding 的跨域记忆层。**
> **你随便说两句，它帮你补上 agent 看不到的上下文——**
> **被 compact 压缩掉的决策、其他 agent 的讨论、别的项目的方案。**
> **每个 agent 都是信息孤岛，我们是连接它们的桥梁。**
> **语音是入口，GraphRAG 是核心，跨 agent 统一是壁垒。"**

---

## 参考

### 跨 Session 记忆 / 对话知识图谱
- [Zep/Graphiti: Temporal KG for Agent Memory](https://arxiv.org/abs/2501.13956) — 时序感知跨 session 记忆，双时间模型，token 压缩 115K→1.6K，LongMemEval +18.5%
- [PersonalAI: KG Storage for Personalized LLM Agents](https://arxiv.org/pdf/2506.17001v4) — LLM 自动构建个人知识图谱，超边（thesis + episodic）
- [Contextual Memory Graphs](https://www.researchgate.net/publication/396444634) — 对话→图节点，上下文准确率 +42%，token -51.6%
- [Dialogue History Graphs (IWSDS 2025)](https://preview.aclanthology.org/master-new-author-system-ui/2025.iwsds-1.31.pdf) — 四层 schema：对话→轮次→语义单元→实体

### GraphRAG 研究
- [CLARE: Context-Aware KG Construction from Transcripts](https://doi.org/10.3390/info16100866) — 82.1% 准确率（vs GraphRAG 48.3%），实体消歧 + 关系解释 + Fallback 非共现实体
- [KGGen (NeurIPS 2025)](https://openreview.net/forum?id=YyhRJXxbpi) — S-BERT + K-means 实体聚类去重，引入 MINE benchmark（68.5%）
- [CoDE-KG (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.598/) — 句子复杂度建模，复杂句→简单句→再提取，65.8% F1
- [LightKGG](https://arxiv.org/) — 小模型（Phi-3.5）达到 GPT-4o 96% 效果，证明 Haiku 级别可行
- [LightRAG (EMNLP 2025)](https://github.com/HKUDS/LightRAG) — 双层检索（图谱 + 向量），21K+ stars
- [Lettria GraphRAG Benchmark](https://www.lettria.com/blogpost/graphrag-benchmark-2025) — GraphRAG 80% vs Vector RAG 50.8%
- [Microsoft BenchmarkQED](https://www.microsoft.com/en-us/research/blog/benchmarkqed-automating-benchmarks-for-large-scale-rag-evaluation/)
- [FalkorDB GraphRAG Study](https://www.falkordb.com/blog/graphrag-vs-rag/) — 多跳查询 vector RAG ≈ 0%
- [WildGraphBench 2026](https://arxiv.org/abs/2502.07186)
- [Lightweight GraphRAG with SQLite](https://dev.to/stephenc222/how-to-build-lightweight-graphrag-with-sqlite-53le)

### 工具 / SDK
- [EmbedKit](https://github.com/klu-ai/EmbedKit) — Swift 本地 embedding（Apple MLX）
- [GRDB FTS5](https://github.com/groue/GRDB.swift/blob/master/Documentation/FullTextSearch.md)
- [Obsidian Mind](https://github.com/breferrari/obsidian-mind) — Vault 作为 agent 持久记忆

### 社区痛点
- [GitHub #23751](https://github.com/anthropics/claude-code/issues/23751) — Compact 失败/遗忘
- [Codex CLI #14593](https://github.com/openai/codex/issues/14593) — Token 消耗不透明（307+ 评论）
- [Gemini CLI #23858](https://github.com/google-gemini/gemini-cli/issues/23858) — Plan mode 被绕过
- [Context Mode 博客](https://mejba.me/) — "Claude isn't getting dumber. It's getting amnesia."
