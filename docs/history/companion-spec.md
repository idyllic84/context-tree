> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Yanmo Companion MVP - Implementation Spec

> Based on [claude-code-companion.md](claude-code-companion.md), [companion-demo.md](companion-demo.md), [companion-technical.md](companion-technical.md).
> This spec covers the MVP scope: simplified 3-step pipeline, 5 scenarios (skip cross-agent), Claude adapter only.

---

## 1. Scope

### MVP 场景

| # | 场景 | 核心能力 |
|---|------|---------|
| 1 | 主动矛盾预警 | 用户输入含关键词 → 匹配 decision 节点 → 面板展示冲突 |
| 3 | 决策演化时间线 | decision 节点按 valid_from 排序 + superseded_by 边 |
| 4 | 跨 Session 话题汇总 | FTS5 搜索 + related_to 1-hop 展开 |
| 5 | 重复沟通检测 | decision title 去重匹配，统计出现次数 |
| 6 | 语音热词 | term 节点 title 注入 phrase list |

### 不做

- 场景 2（跨 Agent 桥接）：需要 Copilot adapter，MVP 后
- 实体消解（Step 3）：接受少量重复
- 完整矛盾检测（Step 4）：用关键词匹配简化
- 社区检测（Step 7）：非 MVP 必需
- embedding / 向量搜索：FTS5 关键词搜索够用
- 自动 sync（auto_sync）：MVP 仅手动触发

---

## 2. 存储设计

### 2.1 目录结构

```
{config_dir}/brain/
├── companion.db              # SQLite 索引（nodes + edges + FTS5 + processing_state）
├── sessions/
│   └── claude/
│       ├── 2026-04-10-otel-design.md
│       └── 2026-04-09-swiftdata-migration.md
├── decisions/
│   ├── no-swiftdata.md
│   └── otel-three-signals.md
├── topics/
│   └── caching.md
├── problems/
│   └── swiftdata-null-crash.md
└── terms.md                  # 所有 term 汇总文件
```

其中 `{config_dir}` = `settings::config_dir()`（macOS: `~/Library/Application Support/com.microsoft.aidictation.mac/`, Windows: `%APPDATA%\com.microsoft.aidictation.tauri\`）。

### 2.2 SQLite Schema（MVP 精简版）

相比 companion-technical.md 的完整 schema，MVP 去掉了 `embedding`、`canonical_id`、`aliases`、`edges.direction`、`edges.expired_at`、`communities` 表。

```sql
-- 节点表
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,          -- session | decision | topic | term | problem | solution | file
    title TEXT NOT NULL,
    content TEXT,
    file_path TEXT,
    metadata TEXT,               -- frontmatter JSON
    valid_from TEXT,
    invalid_from TEXT,           -- NULL = 仍有效
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 边表
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    relation TEXT NOT NULL,
    explanation TEXT,
    valid_from TEXT,
    invalid_from TEXT,
    session_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, relation)
);

-- FTS5 全文检索
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    title, content,
    content=nodes,
    content_rowid=rowid,
    tokenize='unicode61'
);

-- FTS5 同步触发器
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, title, content) VALUES('delete', old.rowid, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, title, content) VALUES('delete', old.rowid, old.title, old.content);
    INSERT INTO nodes_fts(rowid, title, content) VALUES (new.rowid, new.title, new.content);
END;

-- 处理状态追踪
CREATE TABLE IF NOT EXISTS processing_state (
    session_id TEXT PRIMARY KEY,
    session_path TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    processed_at TEXT DEFAULT (datetime('now'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_valid ON nodes(valid_from, invalid_from);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
CREATE INDEX IF NOT EXISTS idx_edges_session ON edges(session_id);
```

### 2.3 Markdown 格式

每个节点一个 .md 文件，带 YAML frontmatter：

```markdown
---
type: decision
date: 2026-04-09
agent: claude-code
project: AiDictation.Mac
valid_from: 2026-04-09
invalid_from:
tags: [database, swiftdata, sqlite]
---

# 不用 SwiftData，用 raw SQL

## 决策
数据库持久化用 raw SQL（通过 GRDB），不用 SwiftData ORM。

## 原因
SwiftData 在 macOS 15 上有 NULL 列映射崩溃问题。

## 关联
- [[swiftdata-null-crash]]
- [[2026-04-09-swiftdata-migration]]
```

命名规则：
- sessions: `sessions/claude/{date}-{slug}.md`
- decisions: `decisions/{slug}.md`
- topics: `topics/{slug}.md`
- problems: `problems/{slug}.md`
- terms: `terms.md`（追加，所有 term 在一个文件）

---

## 3. Claude Adapter

> 参考开源实现：[S2thend/claude-code-history](https://github.com/S2thend/claude-code-history)（数据结构文档）、
> [microsoft/amplifier](https://github.com/microsoft/amplifier)（DAG 规范 + 解析实现，含 compact 链追踪、sidechain 映射、两遍加载）、
> [choplin/cclog](https://github.com/choplin/cclog)（JSONL 规范）、
> [shcv/claude-investigations](https://github.com/shcv/claude-investigations)（深度格式分析）、
> [DevOpsBenjamin/rs-claude-bar](https://github.com/DevOpsBenjamin/rs-claude-bar)（Rust struct 定义）。
>
> **Amplifier 架构要点**（`tools/` 目录 5 个核心文件）：
> - `dag_loader.py`（496 行）：两遍加载 JSONL，第一遍过滤 compact artifacts，第二遍加载消息，UUID 去重
> - `dag_navigator.py`（243 行）：DAG 遍历，分支检测（多 children），构建 ConversationTree
> - `subagent_mapper.py`（337 行）：v2 用 `isSidechain`，v1 用 SHA256(prompt) 匹配子 agent 文件
> - `compact_tracer.py`（180 行）：沿 `compact_boundary` 的 `sessionId` 反向追踪 session 链
> - `transcript_formatter.py`（498 行）：Markdown 转录输出

### 3.1 文件结构

```
~/.claude/
├── sessions/                           # 活跃 session 元数据（按 PID）
│   └── {pid}.json                      # { pid, sessionId, cwd, startedAt, kind }
├── projects/                           # 对话记录（按项目路径）
│   └── {project-slug}/                 # 路径 slug：/home/example/bar → -Users-foo-bar
│       ├── {sessionId}.jsonl           # 主 session 对话记录
│       └── {sessionId}/               # session 附属目录
│           ├── subagents/             # 子 agent 对话记录
│           │   ├── agent-{agentId}.jsonl
│           │   └── agent-{agentId}.meta.json  # { agentType, description }
│           └── tool-results/          # 超大 tool 结果（>50K chars）
│               └── {hash}.txt
└── .claude.json                        # 每项目状态（projects key）
```

### 3.2 JSONL 消息类型（完整枚举）

> 基于 203,552 行、1,837 文件的实际统计。

| `type` | 数量 | 说明 | 知识提取是否需要 |
|--------|------|------|:---:|
| `progress` | 69,537 | 子 agent 进度流 | ❌ 过滤 |
| `assistant` | 67,768 | Claude 回复（text / tool_use / thinking） | ❌ 不提取（太长太贵） |
| `user` | 47,293 | **用户消息 + tool_result** | ✅ 核心数据源 |
| `file-history-snapshot` | 10,718 | 文件备份快照（undo 用） | ❌ 过滤 |
| `queue-operation` | 5,057 | 消息队列（enqueue/dequeue） | ❌ 过滤 |
| `system` | 3,057 | 系统事件（turn 计时、compact、错误） | ❌ 过滤 |
| `last-prompt` | 48 | 最后一条 prompt 记录 | ❌ 过滤 |
| `custom-title` | 36 | 用户自定义 session 标题 | ✅ 用于 session 显示名 |
| `agent-name` | 36 | 命名 agent session | ✅ 用于 session 显示名 |
| `summary` | 2 | 对话摘要 + leafUuid | ⚠️ 可选（已有摘要） |

**⚠️ 重要**：老版本用 `type: "human"`，当前版本（v2.x）用 `type: "user"`。解析器应兼容两者。

### 3.3 `type: "user"` 消息的子类型

`type: "user"` 包含了用户输入和 tool result 两种，需要区分：

| 判断条件 | 含义 | 处理方式 |
|---------|------|---------|
| `message.content` 是 string | 纯文本用户输入 | ✅ 提取 |
| `message.content` 是 array 且含 `type: "text"` block | 多模态用户输入 | ✅ 提取 text 部分 |
| `message.content` 是 array 且含 `type: "tool_result"` block | Tool 执行结果 | ⚠️ 仅提取文件名（从 `toolUseResult.filenames`） |
| `isCompactSummary == true` | Compact 压缩摘要 | ❌ 过滤（不是用户原话） |
| `isSidechain == true` | 子 agent 消息 | ❌ 过滤 |

### 3.4 关键字段速查

| 字段 | 说明 | 使用场景 |
|------|------|---------|
| `type` | 消息类型（见 3.2） | 过滤 |
| `uuid` | 消息唯一 ID | DAG 构建 |
| `parentUuid` | 父消息 ID（null = DAG 根） | DAG 构建 |
| `sessionId` | Session UUID | 分组 |
| `timestamp` | ISO 8601 时间戳 | 排序、日期提取 |
| `isSidechain` | 是否为子 agent 消息 | **必须过滤 = true** |
| `isCompactSummary` | 是否为 compact 摘要 | **必须过滤 = true** |
| `agentId` | 子 agent ID | 过滤子 agent |
| `slug` | Session 可读名（如 `"cuddly-imagining-barto"` ） | 显示名 |
| `cwd` | 消息时的工作目录 | 项目路径 |
| `gitBranch` | 当前 git 分支 | 上下文 |
| `version` | CLI 版本号 | 兼容性 |
| `entrypoint` | 入口（`"cli"`） | 过滤 |
| `message.content` | 消息内容（string 或 content block array） | 知识提取 |
| `toolUseResult` | 结构化 tool 结果元数据 | 文件操作提取 |
| `toolUseResult.filenames` | Tool 操作的文件列表 | **文件操作的正确来源** |
| `customTitle` | 用户自定义标题（`type: "custom-title"`） | Session 显示名 |
| `agentName` | Agent 名称（`type: "agent-name"`） | Session 显示名 |

### 3.5 子 Agent（Subagent）关系

子 agent **不是**独立 session，而是主 session 的一部分：

```
主 session assistant 消息
  → tool_use: { name: "Agent", id: "toolu_vrtx_01DBG..." }
      → 创建 subagents/agent-{agentId}.jsonl（共享同一 sessionId）
      → 所有消息带 isSidechain: true + agentId
      → 进度通过 type: "progress" 流回主 session
      → 最终结果作为 type: "user" + toolUseResult 返回主 session
```

**过滤规则**：
1. 排除 `subagents/` 目录下的 `.jsonl` 文件
2. 排除主 session JSONL 中 `isSidechain == true` 的消息
3. 排除 `type == "progress"` 的消息

### 3.6 Compact 机制

Session 过长时 Claude Code 会自动 compact：

- **Full compact**：`type: "system"` + `subtype: "compact_boundary"` + `compactMetadata`
  - 之后紧跟 `isCompactSummary: true` 的摘要消息（9 节结构化摘要）
  - `parentUuid: null`（新 DAG 根），`logicalParentUuid` 保留原链
- **Micro compact**：`type: "system"` + `subtype: "microcompact_boundary"`
  - 清除指定 tool result 的内容，节省 token

**对知识提取的影响**：compact 摘要不是用户原话，不应作为知识提取的输入。

### 3.7 Session 间父子关系（跨文件 DAG）

> 参考：[Piebald Blog: Messages as Commits](https://piebald.ai/blog/messages-as-commits-claude-codes-git-like-dag-of-conversations)、
> [AlexZan/claude-chats FINDINGS.md](https://github.com/AlexZan/claude-chats/blob/master/docs/FINDINGS.md)、
> [watch-claude-think ADR](https://github.com/bporterfield/watch-claude-think/blob/main/docs/adr/006-sessions-vs-conversations.md)

Claude Code 的 session 文件之间通过 `summary` 条目 + `parentUuid` 跨文件引用形成**树形关系**：

```
Session A（原始对话）
  └─ messages... → 最后一条消息 uuid = "abc123"

Session B（通过 /resume 继续 Session A）
  ├─ { "type": "summary", "leafUuid": "abc123", "summary": "..." }   ← 引用 A 的叶子节点
  └─ 新消息 parentUuid = "abc123"                                     ← 跨文件指向 A

Session C（通过 --fork-session 从 Session A 某点分叉）
  ├─ { "type": "summary", "leafUuid": "xyz789", "summary": "..." }   ← 引用 A 的某个中间节点
  └─ 新消息 parentUuid = "xyz789"
```

**关联机制**：

| 操作 | 如何关联 | 新 session 中的痕迹 |
|------|---------|-------------------|
| `/resume` 或 `claude -c` | 新 session 的首条消息 `parentUuid` 指向旧 session 的叶子节点 | `type: "summary"` + `leafUuid` 指向旧 session |
| `--fork-session` | 新 session 从旧 session 的某个点分叉 | `type: "summary"` + `leafUuid` 指向分叉点 |
| `--resume <id>` | 选择特定 session 继续 | 同上 |

**构建 session 树的算法**：
```
1. 扫描同一 project 下所有 session 文件
2. 为每个 session 构建 uuid → sessionId 的映射表（扫描所有消息的 uuid 字段）
3. 提取每个 session 中 type: "summary" 条目的 leafUuid
4. 通过 leafUuid 在映射表中查找 → 该 UUID 属于哪个 session = 父 session
5. 没有 summary 条目的 session = 根 session
6. 按此关系构建树
```

**MVP 状态**：暂未实现。当前 session 列表为扁平展示。跨 session 的知识关联通过**同名 entity slug 自动合并**实现，不依赖 session 父子链。决策时序通过 `valid_from` 时间戳排序，也不依赖 session 层级。

**后续可做**：
- UI session 列表按 project 分组 + 树形缩进展示
- 跨 session 的 entity 合并时参考 session 父子关系来判断"同一个对话上下文"
- resume 链上的 decision 自动建立 `superseded_by` 关系

### 3.8 Session 发现与过滤

```
1. 扫描 ~/.claude/projects/ 下所有 .jsonl 文件
2. **排除 subagents/ 目录下的文件**
3. 按 mtime 排序（最新在前）
4. 对每个文件，检查 processing_state 表：
   - 未处理 → 需要 sync
   - 已处理但 message_count 变化 → 需要重新 sync
   - 已处理且 message_count 不变 → 跳过
5. 提取 session 元信息：
   - slug（从消息的 slug 字段）
   - customTitle（从 type: "custom-title" 消息）
   - cwd / gitBranch / version（从首条消息）
```

### 3.8 解析逻辑（修正版）

遍历每个 session JSONL：

1. **提取用户消息**：
   - 筛选 `type == "user"` 或 `type == "human"`（兼容老版本）
   - 排除 `isSidechain == true`
   - 排除 `isCompactSummary == true`
   - 排除 `message.content` 包含 `tool_result` block 的行（这是 tool 结果，不是用户输入）
   - 取 `message.content`（string → 直接用；array → 拼接所有 `type: "text"` block）

2. **提取文件操作**：
   - 筛选 `type == "user"` 且 `toolUseResult` 存在的行
   - 从 `toolUseResult.filenames` 数组直接获取文件路径列表（**不要从文本中正则匹配**）

3. **提取 session 元信息**：
   - `slug`：从任意消息的 `slug` 字段
   - `customTitle`：从 `type == "custom-title"` 消息的 `customTitle` 字段
   - `cwd`：从首条消息的 `cwd` 字段
   - `gitBranch`：从首条消息的 `gitBranch` 字段

4. **构建 SessionRecord**：

```
SessionRecord {
    agent: "claude-code",
    session_id: String,
    project_path: String,         // cwd
    slug: Option<String>,         // 可读 slug（如 "cuddly-imagining-barto"）
    custom_title: Option<String>, // 用户自定义标题
    git_branch: Option<String>,   // git 分支
    start_time: Option<String>,   // 首条消息时间戳
    user_messages: Vec<UserMessage>,
    file_operations: Vec<FileOp>,
}
```

### 3.9 UI Session 列表展示

Session 列表应展示：
- **显示名**：优先 customTitle → 其次 slug → 最后 sessionId 前 8 位
- **项目路径**：cwd 的最后两段（如 `crossOS/AiDictation.Tauri`）
- **分支**：gitBranch
- **消息数**：用户消息条数（不含 tool_result / system / progress）
- **时间**：start_time 的相对时间（如 "2 hours ago"）
- **状态**：已同步 ✅ / 未同步 ⏳
- **不显示**：subagent 文件（它们不是独立 session）

---

## 4. LLM 提取管线

> 参考实现：
> - [Graphiti/Zep](https://github.com/getzep/graphiti)：**每条消息单独处理**（episode 模型），分步 prompt（实体提取 → 去重 → 关系提取 → 时序处理），双时间模型
> - [LightRAG](https://github.com/HKUDS/LightRAG)：**1200 token 分块** + 100 token 重叠，分隔符格式输出，gleaning（追问遗漏）
> - [CLARE](https://github.com/ryanwaynehenry/clare)：**关系要求 rationale**，实体和关系分两轮提取，非共现实体 fallback

### 4.1 设计决策：增量式任务树构建

> 参考 [context-tree-design.md](context-tree-design.md) 的 6 维意图分类体系。
>
> 原方案（分块独立提取 → 合并）的根本问题：
> - 每个 chunk 独立提取，不知道前面的任务上下文
> - "好的继续"无法理解为"对当前任务的确认"
> - "用第二个方案"无法理解为"REPLACE 当前方案"
> - 合并时只能按 title 去重，无法理解任务演化

**新方案：增量式任务树构建**

每个 session 不是独立提取碎片再合并，而是逐块累积构建一棵**任务树**。
LLM 每次看到的是"已有的树 + 新对话内容"，能理解每条消息在任务中的角色。

### 4.2 Pipeline 流程

```
手动触发 "Sync Now"
  → Step A: Claude Adapter 读取 JSONL → SessionRecord（对话流 + 文件操作）
  → Step B: 按 8000 字符切块（纯字符切分，不需要时间分段）
  → Step C: 增量式任务树构建（核心）
       task_tree = {}
       for chunk in chunks:
           task_tree = LLM(task_tree 摘要 + 新 chunk)
           // LLM 根据意图分类更新树：
           //   NEW → 加新任务节点
           //   REFINE → 更新已有节点约束/内容
           //   REPLACE → 标记旧节点 abandoned，加新节点 + 记录 constraint
           //   ROLLBACK → 标记当前节点 abandoned，激活旧节点 + 记录 lesson
           //   FIX → 更新节点状态 + 记录 lesson
  → Step D: 从任务树提取知识
       completed 的任务 → context（项目事实）
       abandoned + replaced → constraint（为什么不用旧方案）+ lesson（踩坑）
       累积的约束 → constraint
       代码标识符 → term
  → Step E: 实体消解（与全局知识森林合并）
  → Step F: 写入 Markdown + SQLite + Embedding
  → Step G: 注入热词
```

### 4.3 任务树数据结构

```json
{
  "tasks": [
    {
      "id": "task-1",
      "goal": "将历史记录存储迁移到 SQLite",
      "status": "completed",
      "constraints": [
        "不用 SwiftData（macOS 15 NULL 崩溃）",
        "统计数据不受删除影响"
      ],
      "outcome": "使用 GRDB + raw SQL 实现，改动在 DatabaseService.swift",
      "abandoned_alternatives": [
        {"approach": "SwiftData", "reason": "macOS 15 NULL 列映射崩溃"}
      ],
      "subtasks": [
        {
          "id": "task-1-1",
          "goal": "修复迁移后旧数据丢失",
          "status": "completed",
          "outcome": "迁移时跳过无 data 列的早期数据行"
        }
      ],
      "terms": ["DatabaseService", "GRDB", "history.db"]
    }
  ]
}
```

### 4.3.1 增量构建 Prompt

每次 LLM 调用的输入：

```
## 当前任务树状态

{task_tree_json 的紧凑摘要，只保留 goal/status/constraints，不含完整 content}

## 新对话内容（chunk N/M）

[Agent] 我建议用 SwiftData 来实现...
[User] 不要用 SwiftData，macOS 15 有崩溃问题
[Agent] 好的，改用 GRDB...
[User] 好的

## 指令

分析新对话中每条用户消息的意图：
- NEW: 提出新任务 → 在树上添加新任务节点
- REFINE: 细化当前任务 → 更新节点约束/目标
- REPLACE: 换方案 → 标记旧方案 abandoned，记录原因
- ROLLBACK: 回退 → 标记当前方案 abandoned
- FIX: 修复问题 → 更新节点，记录 lesson
- CONFIRM: "好的/继续" → 不改变树结构

输出更新后的任务树 JSON。
```

### 4.3.2 从任务树提取知识

任务树处理完整个 session 后，转化为知识图谱节点：

| 树节点状态 | 提取为 | 示例 |
|-----------|--------|------|
| completed task | **context** | "数据库用 GRDB + raw SQL" |
| abandoned_alternatives | **constraint** | "不用 SwiftData（macOS 15 崩溃）" |
| constraints 列表 | **constraint** | "统计数据不受删除影响" |
| FIX/ROLLBACK 记录 | **lesson** | "SwiftData isDeleted 列与系统冲突" |
| terms 列表 | **term** | DatabaseService, GRDB |

### 4.3.3 跨 Session 合并（知识森林）

每个 session 产出一棵任务树，跨 session 通过实体消解合并为全局**知识森林**：

```
Session A 的树: task "数据库迁移" (completed, GRDB)
Session B 的树: task "数据库优化" (completed, raw SQL)
  → 实体消解发现两者相关
  → 合并为一个 context 节点 + superseded_by 关系
```

### 4.4 LLM 端点

复用 `services/polish.rs` 的 `build_openai_request()` 模式：
- 优先使用 GitHub Copilot API（`api.githubcopilot.com/chat/completions`）
- model: `gpt-5.2`（从 `settings.copilot_model` 读取）
- timeout: 60s
- 每块一次 LLM 调用，块之间串行（避免 rate limit）

将 polish.rs 中的 `build_openai_request()` 改为 `pub(crate)` 以复用。

### 4.5 任务树 Response 解析

LLM 返回更新后的任务树 JSON → 解析后与之前的树合并。

容错处理：
- JSON 解析失败 → 尝试从 ```json``` code fence 中提取
- 找到 `{` 到最后一个 `}` 之间的内容尝试解析
- 字段缺失 → 用默认值
- relation 引用不存在的 entity → 跳过该 relation（不中断）

---

## 5. 检索逻辑

> **设计变更**：原 spec（companion-technical.md）将 embedding 标为"可选、非 MVP 必需"，
> 但实测发现用户用中文输入时无法匹配英文 entity title（FTS5/LIKE 均为纯文本匹配，不支持跨语言）。
> 因此 embedding 语义检索从"第二阶段"提前到 MVP。
>
> 参考：[LightRAG](https://github.com/HKUDS/LightRAG) 的双层检索（图谱 + 向量），
> [Graphiti](https://github.com/getzep/graphiti) 的 hybrid search（semantic + BM25）。

### 5.0 Embedding 语义检索

**端点**：GitHub Copilot API — `POST https://api.githubcopilot.com/embeddings`
- model: `text-embedding-3-small`（Copilot API 可用）
- 输出维度：1536（默认），可选降维到 256/512 减少存储
- 支持批量输入

**流程**：

```
提取时（写入）：
  每个 entity 提取后 → 生成 embedding（title + content 拼接）→ 存入 nodes.embedding

检索时（读取）：
  用户输入文本 → 生成 embedding → cosine similarity 与所有 node.embedding 比较
  → 取 top-K（K=20）→ 1-2 hop 图遍历展开关联节点
```

**Schema 变更**：
```sql
-- nodes 表新增 embedding 列
ALTER TABLE nodes ADD COLUMN embedding BLOB;
```

**Cosine Similarity 计算**：
SQLite 没有内置向量运算，在 Rust 端计算：
```
1. 加载所有 node 的 embedding（几百个节点，内存可承受）
2. 计算 query_embedding 与每个 node_embedding 的 cosine similarity
3. 按 similarity 降序排列，取 top-K
4. 对 top-K 节点做 1-hop 图遍历展开
```

**成本**：
- embedding 调用：~$0.00002 / 1K tokens（text-embedding-3-small）
- 每个 entity 约 20-50 tokens → 每 session ~50 entities → ~$0.0001/session
- 检索时每次查询 1 次 embedding 调用

**Fallback**：若 Copilot embedding 端点不可用，降级到 FTS5 + LIKE 关键词搜索。

### 5.1 LLM 驱动的迭代检索（Agentic RAG）

> 原方案用固定 N-hop 图遍历，问题是：hop 太少找不到根因，hop 太多引入噪声。
> 改为 LLM 驱动的迭代检索——LLM 决定是否需要更多上下文，而不是硬编码 hop 数。

**流程**：

```
用户输入: "为什么不用SwiftData"
  │
  ├─ Step 1: 实体提取（复用 extraction prompt）
  │    → LLM 从用户输入中提取 entities + intent
  │    → entities: ["SwiftData"], intent: "查询关于 SwiftData 的决策"
  │
  ├─ Step 2: Embedding 语义召回
  │    → 对每个提取的 entity title 生成 embedding
  │    → cosine similarity 找 top-K 最相关 nodes（decision/topic/problem/solution/term）
  │    → 同时 FTS5 关键词补充
  │
  ├─ Step 3: LLM 首轮总结 + 判断
  │    → 把召回的 nodes 作为上下文 + 用户问题 → LLM
  │    → LLM 输出:
  │       {
  │         "answer": "初步回答...",
  │         "needs_more_context": true,
  │         "expand_nodes": ["swiftdata-null-crash", "observable-级联追踪问题"],
  │         "reason": "需要了解具体的崩溃原因和替代方案"
  │       }
  │
  ├─ Step 4: 图遍历展开（仅当 needs_more_context = true）
  │    → 对 expand_nodes 中的每个 node，沿 edge 展开 1-hop 邻居
  │    → 新增的 nodes 加入上下文
  │
  ├─ Step 5: LLM 再次总结 + 判断
  │    → 重复 Step 3，直到 needs_more_context = false 或达到最大轮数（3 轮）
  │
  └─ 最终输出: answer + 引用的 nodes 列表
```

**优势**：
- LLM 理解语义，知道什么时候上下文够了
- 不需要调阈值或固定 hop 数
- 每次展开都是有目的的（LLM 指定要展开哪些 node）
- 减少无关节点的引入

**成本**：
- 每次查询 1 次实体提取 + 1 次 embedding + 1-3 次 LLM 总结
- 约 2-8 秒 / 查询（gemini-3-flash-preview）

**Step 1 实体提取 prompt**：

```
Extract key entities and the user's intent from this input.
Output JSON only:
{
  "entities": ["entity1", "entity2"],
  "intent": "what the user wants to know"
}
```

**Step 3 总结 + 判断 prompt**：

```
Based on the retrieved knowledge, answer the user's question.
If you need more context from specific nodes, specify which ones to expand.

Retrieved nodes:
{nodes_context}

User question: {query}

Output JSON:
{
  "answer": "your answer based on current context",
  "needs_more_context": true/false,
  "expand_nodes": ["node-id-1", "node-id-2"],
  "reason": "why more context is needed"
}
```

### 5.2 矛盾检测

对用户当前输入文本：
1. 用 embedding 语义搜索 type='decision' 的节点（top-10）
2. 检查匹配到的 decision 是否含否定关键词（"不用"、"不要"、"禁止"、"not"、"don't"、"avoid"）
3. 如果用户输入的意图与 decision 内容方向相反 → 报告矛盾

### 5.3 决策时间线

```sql
SELECT n.*, e.relation, e2.source_id AS supersedes
FROM nodes n
LEFT JOIN edges e ON n.id = e.source_id AND e.relation = 'superseded_by'
LEFT JOIN edges e2 ON n.id = e2.target_id AND e2.relation = 'superseded_by'
WHERE n.type = 'decision'
  AND (n.title LIKE ? OR n.content LIKE ?)
ORDER BY n.valid_from ASC;
```

### 5.4 重复检测

```sql
-- 查找 title 相同（忽略大小写）的 decision 节点，来自不同 session
SELECT n.title, COUNT(DISTINCT e.session_id) as session_count,
       GROUP_CONCAT(DISTINCT e.session_id) as sessions
FROM nodes n
JOIN edges e ON n.id = e.source_id AND e.relation = 'decided_in'
WHERE n.type = 'decision' AND n.invalid_from IS NULL
GROUP BY LOWER(n.title)
HAVING COUNT(DISTINCT e.session_id) >= 2;
```

### 5.5 热词提取

```sql
SELECT DISTINCT title FROM nodes WHERE type = 'term';
```

结果注入 `phrases::save_server_phrases()`。

---

## 6. Rust 模块结构

### 6.1 新增模块

```
src-tauri/src/
├── companion/
│   ├── mod.rs              # 模块入口，pipeline 编排，init()
│   ├── adapter.rs          # Claude JSONL 解析 → SessionRecord
│   ├── store.rs            # SQLite CRUD + FTS5 + 图遍历（同 history.rs 的 with_db 模式）
│   ├── markdown.rs         # Markdown 文件读写（frontmatter + wikilinks）
│   ├── extraction.rs       # LLM prompt 构建 + response 解析
│   ├── search.rs           # 高级检索：矛盾检测、时间线、话题汇总、重复检测
│   └── hotwords.rs         # term 节点 → phrases 注入
├── commands/
│   └── companion.rs        # Tauri 命令薄壳
└── services/
    └── companion_llm.rs    # Copilot API 调用（知识提取专用）
```

### 6.2 mod.rs 职责

- 声明子模块（pub mod adapter/store/markdown/extraction/search/hotwords）
- 定义 `CompanionState`（供 Tauri manage）
- `init(app: &AppHandle)` — 创建 brain 目录、初始化 SQLite
- `sync(app: &AppHandle) -> Result<SyncResult, String>` — 编排完整 pipeline：
  1. adapter::discover_sessions() → 找到需要 sync 的 session
  2. 对每个 session：adapter::parse_session() → SessionRecord
  3. extraction::extract(session_record) → ExtractionResult
  4. markdown::write(extraction_result) → 写文件
  5. store::upsert(extraction_result) → 更新 SQLite
  6. store::update_processing_state() → 标记已处理
  7. hotwords::inject() → 更新 phrase list

### 6.3 Commands 薄壳

```
companion_sync(app) -> SyncResult            # 手动触发 sync
companion_search(query) -> Vec<SearchResult>  # FTS5 搜索
companion_get_timeline(topic) -> Vec<TimelineEntry>
companion_check_contradictions(text) -> Vec<Contradiction>
companion_find_repetitions() -> Vec<Repetition>
companion_get_stats() -> CompanionStats       # 节点/边数量
companion_get_sessions() -> Vec<SessionInfo>  # 可用 Claude session 列表
companion_open_window(app) -> ()              # 打开 Companion 窗口
```

### 6.4 已有文件修改

| 文件 | 修改内容 |
|------|---------|
| `lib.rs` | 加 `mod companion;`，manage CompanionState，注册 commands，companion window close→hide |
| `settings.rs` | Settings 加 `companion_enabled: bool`（default false） |
| `commands/mod.rs` | 加 `pub mod companion;` |
| `services/mod.rs` | 加 `pub mod companion_llm;` |
| `services/polish.rs` | `build_openai_request()` 改 `pub(crate)` |
| `tray.rs` | 加 "Companion" 菜单项 + handler，TrayState 加 `companion_item` |
| `tauri.conf.json` | app.windows 加 companion 窗口定义 |
| `Cargo.toml` | 不需要新依赖（rusqlite/reqwest/chrono/serde_json 都已有） |

---

## 7. 前端设计

### 7.1 独立浮动窗口

新增入口：`companion.html` + `src/companion-main.ts` + `src/companion/CompanionPanel.vue`

窗口配置（tauri.conf.json）：

```json
{
    "label": "companion",
    "title": "Companion",
    "url": "companion.html",
    "width": 420,
    "height": 600,
    "visible": false,
    "decorations": true,
    "resizable": true,
    "center": true,
    "minWidth": 360,
    "minHeight": 400
}
```

与 overlay 的区别：有标题栏、可拖拽、可缩放、不 always-on-top、不跳过 taskbar。关闭时 hide（不退出）。

### 7.2 组件结构

```
src/companion/
├── CompanionPanel.vue        # 根组件：搜索栏 + tab 切换 + footer
├── SearchView.vue            # 搜索结果（FTS5 匹配 + 1-hop 关联）
├── ContradictionAlert.vue    # 矛盾预警卡片
├── DecisionTimeline.vue      # 决策演化时间线
├── RepetitionWarning.vue     # 重复沟通检测卡片
└── StatsView.vue             # 知识图谱统计 + sync 状态
```

### 7.3 CompanionPanel 布局

```
┌─ Companion ──────────────────────────┐
│ ┌────────────────────────────────┐   │
│ │ 🔍 Search knowledge...         │   │
│ └────────────────────────────────┘   │
│                                      │
│ [Search] [Warnings] [Timeline] [Status] │
│                                      │
│ ┌────────────────────────────────┐   │
│ │                                │   │
│ │     (Active tab content)       │   │
│ │                                │   │
│ │                                │   │
│ └────────────────────────────────┘   │
│                                      │
│ ─────────────────────────────────    │
│ [Sync Now]  Last sync: 5 min ago     │
│ 42 nodes · 67 edges · 8 sessions     │
└──────────────────────────────────────┘
```

### 7.4 打开方式

1. **Tray 菜单**：新增 "Companion" / "知识图谱" 项
2. **主窗口**：Settings 页面加 "Open Companion" 按钮（不新增 sidebar tab）

### 7.5 i18n

在 `en-US.json` 和 `zh-CN.json` 中各加一个 `"companion"` section。

### 7.6 constants.ts 新增

```typescript
// Events
COMPANION_SYNC_START: 'companion-sync-start',
COMPANION_SYNC_COMPLETE: 'companion-sync-complete',
COMPANION_SYNC_ERROR: 'companion-sync-error',

// Commands
COMPANION_SYNC: 'companion_sync',
COMPANION_SEARCH: 'companion_search',
COMPANION_TIMELINE: 'companion_get_timeline',
COMPANION_CONTRADICTIONS: 'companion_check_contradictions',
COMPANION_REPETITIONS: 'companion_find_repetitions',
COMPANION_STATS: 'companion_get_stats',
COMPANION_SESSIONS: 'companion_get_sessions',
COMPANION_OPEN: 'companion_open_window',
```

### 7.7 types.ts 新增

```typescript
interface CompanionNode {
    id: string;
    type: 'session' | 'decision' | 'topic' | 'term' | 'problem' | 'solution' | 'file';
    title: string;
    content: string | null;
    metadata: string | null;
    validFrom: string | null;
    invalidFrom: string | null;
}

interface CompanionEdge {
    sourceId: string;
    targetId: string;
    relation: string;
    explanation: string | null;
}

interface SearchResult {
    node: CompanionNode;
    relatedNodes: CompanionNode[];
    matchedField: 'title' | 'content';
    snippet: string;
}

interface Contradiction {
    inputKeyword: string;
    decision: CompanionNode;
    sessionDate: string;
    agent: string;
}

interface TimelineEntry {
    decision: CompanionNode;
    supersededBy: string | null;
    isActive: boolean;
}

interface Repetition {
    title: string;
    sessionCount: number;
    sessions: string[];
}

interface CompanionStats {
    nodeCount: number;
    edgeCount: number;
    sessionCount: number;
    decisionCount: number;
    termCount: number;
    lastSync: string | null;
}

interface SyncResult {
    sessionsProcessed: number;
    entitiesExtracted: number;
    relationsExtracted: number;
    errors: string[];
}

interface SessionInfo {
    sessionId: string;
    projectPath: string;
    messageCount: number;
    lastModified: string;
    isProcessed: boolean;
}
```

---

## 8. 实施顺序

### Phase 1: Rust 基础（store + adapter + markdown）

1. `companion/store.rs` — SQLite schema + CRUD + FTS5 搜索（跟 history.rs 同模式）
2. `companion/adapter.rs` — Claude JSONL 解析
3. `companion/markdown.rs` — Markdown 文件生成
4. `companion/mod.rs` — 模块入口 + init()
5. 修改 `lib.rs` — 加 `mod companion;`
6. 单元测试

### Phase 2: LLM 提取

7. `services/companion_llm.rs` — Copilot API 调用
8. `companion/extraction.rs` — prompt 构建 + response 解析
9. 修改 `services/mod.rs` + `services/polish.rs`（pub(crate)）
10. `companion/mod.rs` — pipeline 编排（sync 函数）

### Phase 3: 检索 + 热词 + 命令

11. `companion/search.rs` — 矛盾检测、时间线、话题汇总、重复检测
12. `companion/hotwords.rs` — term → phrases 注入
13. `commands/companion.rs` — 所有命令薄壳
14. 修改 `commands/mod.rs` + `lib.rs`（注册 commands）

### Phase 4: 前端浮动面板

15. `companion.html` + `src/companion-main.ts`
16. `src/companion/CompanionPanel.vue`
17. `src/companion/SearchView.vue`
18. `src/companion/DecisionTimeline.vue`
19. `src/companion/ContradictionAlert.vue`
20. `src/companion/RepetitionWarning.vue`
21. `src/companion/StatsView.vue`
22. 修改 `vite.config.ts`、`tauri.conf.json`、`constants.ts`、`types.ts`、locale 文件

### Phase 5: 集成

23. 修改 `tray.rs` — 加菜单项
24. 修改 `settings.rs` — 加 `companion_enabled`
25. `lib.rs` — companion window close→hide handler
26. 端到端测试

---

## 9. 数据流图

```
                    手动点击 "Sync Now"
                           │
                           ▼
              ┌─── companion::sync() ───┐
              │                         │
              │  adapter::discover()    │  ← ~/.claude/projects/**/*.jsonl
              │         │               │
              │         ▼               │
              │  adapter::parse()       │  → SessionRecord
              │         │               │
              │         ▼               │
              │  companion_llm::call()  │  → Copilot API
              │         │               │
              │         ▼               │
              │  extraction::parse()    │  → ExtractionResult
              │         │               │
              │    ┌────┴────┐          │
              │    │         │          │
              │    ▼         ▼          │
              │  markdown  store        │
              │  ::write() ::upsert()   │
              │              │          │
              │              ▼          │
              │        hotwords         │
              │        ::inject()       │  → phrases::save_server_phrases()
              │              │          │
              └──────────────┘          │
                                        │
              ┌─── 前端面板 ───┐         │
              │                │         │
              │  SearchView    │ ← companion_search()
              │  Timeline      │ ← companion_get_timeline()
              │  Contradiction │ ← companion_check_contradictions()
              │  Repetition    │ ← companion_find_repetitions()
              │  Stats         │ ← companion_get_stats()
              └────────────────┘
```

---

## 10. 构建验证

每个 Phase 完成后执行：

```bash
cargo test -p aidictation        # Rust 测试
npm run build:release            # 全量构建
```

最终验证：
1. 从 tray 打开 Companion 窗口
2. 点击 Sync Now → 处理 Claude session
3. 搜索关键词 → 返回结果 + 关联节点
4. 查看决策时间线
5. 查看重复检测结果
6. 验证 phrases 列表包含提取的 term

---

## 附录：实现过程中的分析与思考演化

> 记录从 MVP 实现到迭代优化过程中，对问题本质的逐步深入理解。

### A.1 实体类型的演化：从学术分类到 Agent 可用

**初始设计**：照搬 GraphRAG 的学术分类——`decision / topic / problem / solution / term`。

**问题发现**：
- `topic`（如"数据库迁移"）对 agent 无操作意义——agent 无法据此做任何事
- `decision` 里混入大量琐碎内容（"提交并推送更改"）
- `solution` 提取不充分，LLM 不知道什么算 solution

**分析**：提取的实体类型应该和检索的输出类型**对齐**。RAG 最终输出 decision/background/warning 给 agent，但源数据是 decision/topic/problem/solution——需要 LLM 二次翻译，翻译过程丢失信息。

**改进**：直接提取 agent 可用的类型：
- `constraint`（agent 必须遵守的规则）
- `context`（agent 需要知道的现状）
- `lesson`（agent 要避免的坑）
- `term`（语音热词，不参与 RAG）

**教训**：提取端和检索端的数据模型必须对齐，中间不应有翻译层。

### A.2 提取质量：从扁平消息到对话任务树

**初始做法**：把用户消息按字符切块，每块独立发给 LLM 提取 entity。

**问题 1 — 所有消息同等权重**：
- "好的"、"继续" 和 "不要用 SwiftData" 被同等对待
- LLM 从 "好的" 里硬提取出无意义的 entity

**问题 2 — 丢失任务上下文**：
- 用户说"用第二个方案"——不知道"第二个"是什么（需要看 agent 回复）
- 用户说"改成异步"——不知道改什么（需要看当前在做的任务）

**问题 3 — 碎片化**：
- 同一个决策过程（试 SwiftData → 遇到崩溃 → 改用 GRDB）被拆成 3 个独立 entity
- 合并时只能按 title 去重，无法理解因果关系

**演化路径**：
1. 扁平消息 → 加入 agent 回复摘要（200 字）作为上下文
2. 加入琐碎消息过滤（"好的"/"ok" 等直接跳过）
3. 引入 [context-tree-design.md](context-tree-design.md) 的意图分类框架
4. 最终：**增量式任务树构建**——LLM 每次看到"已有的树 + 新对话"，按意图（NEW/REFINE/REPLACE/ROLLBACK/FIX）更新树结构

**核心认知**：对话不是扁平的消息列表，而是**任务驱动的树**。提取的单位应该是"任务"而不是"消息"。

### A.3 检索：从关键词到 Agentic RAG

**演化路径**：

| 阶段 | 做法 | 问题 |
|------|------|------|
| v1 | FTS5 关键词搜索 | 中文搜不到英文 entity |
| v2 | FTS5 + LIKE fallback | CJK 分词问题 |
| v3 | Embedding 语义搜索 | 跨语言可以了，但相关性排序差 |
| v4 | Embedding + N-hop 图遍历 | 固定 hop 数：少了找不到根因，多了引入噪声 |
| v5 | Agentic RAG | LLM 驱动迭代展开，自己决定是否需要更多上下文 |

**关键认知**：
- FTS5/关键词搜索永远无法解决跨语言问题——embedding 是必需的，不是可选的
- 固定 N-hop 图遍历是错误方向——应该让 LLM 决定展开哪些节点
- 检索的目标不是"回答用户问题"，而是"为 agent 提供上下文"——这根本改变了 RAG prompt 的设计

### A.4 实体消解的复杂性：Scope × Time

**初始设计**：照搬 Graphiti 的三阶段消解（embedding → BM25 → LLM），假设实体有全局唯一性。

**问题发现**：我们的实体不是通用概念（如"苹果公司"），而是**项目决策和经验**：
- `constraint: 不用 SwiftData` — 只在 AiDictation.Mac 有效？还是所有项目？
- `lesson: macOS 15 NULL 崩溃` — 平台级 bug，所有项目都受影响
- `context: 数据库用 GRDB` — 只描述这个项目

**更深的复杂性 — Scope 的时间演化**：
```
4月: "不用 SwiftData"（项目 A 的决策）→ scope: 项目级
5月: 另一个项目也遇到同样问题 → scope 应提升为全局
6月: Apple 在 macOS 16 修复 → constraint 部分过期（仅 macOS 16+ 过期）
```

Scope 不是静态标签，而是**随证据积累动态变化的推断**。

**当前结论**：不在提取时确定 scope，而在**检索时推断**：
- 每个 entity 保留完整出处（project_path + session_id + date）
- 检索时 LLM 根据当前查询的项目上下文，综合判断哪些知识相关
- 同一 constraint 出现在多个项目 → 检索 LLM 自动识别为通用经验
- 参考 [Graphiti 的 group_id](https://help.getzep.com/graphiti/graphiti/graph-namespacing) 做项目级隔离，但允许跨项目搜索

**开放问题**：
- 如何检测一个项目级决策应该"提升"为全局经验？
- 过期的 constraint 是否应该保留？（原设计说保留历史，但搜索结果应标注 "已过期"）
- 平台版本条件（"macOS 15 有 bug 但 16 修了"）如何表达？

### A.5 性能与工程问题

**Copilot API 限制**：
- gpt-5.4-mini / gpt-5-mini 在 Copilot API 不可用（400 错误）
- 实测 gemini-3-flash-preview（3.8s）速度最优，gpt-5.2（11.8s）最慢
- 429 rate limit 需要按 Retry-After header 重试
- Copilot token 过期（401）需要在 sync 开始前检查

**Tokio deadlock**：
- Root cause：`companion_get_sessions`（同步命令）在 tokio runtime 上执行大量文件 I/O（读取所有 JSONL）
- 当 StatsView 的 refreshKey 触发 session 列表刷新时，阻塞了 sync 的 async LLM 调用所需的工作线程
- Fix：sync 期间不刷新 session 列表

**Chunk 大小计算错误**：
- `chunk_by_chars` 只按 `msg.content.len()` 算预算
- 实际 LLM prompt 还包含 `agent_context`（200 字/条）+ 格式前缀
- 40 条短消息 × 200 字 agent_context = 8000 字额外内容
- Fix：预算计算包含 `min(content, 500) + agent_context + 20`

**JSON 解析**：
- LLM 返回的 JSON 嵌套较深，`rfind('}')` 可能找到错误位置
- Fix：用大括号计数找到完整的最外层 JSON 对象

**事件送达**：
- `app.emit()` 在 Tauri 2 中对独立窗口（companion）的送达不可靠
- Fix：改用 Tauri 的 `Channel<T>` IPC 机制（invoke 参数传递，保证送达）

### A.6 产品定位的认知演化

**初始理解**：做一个"搜索引擎"——用户搜关键词，返回相关知识。

**修正 1 — 不是搜索，是输入增强**：
用户的输入是发给 agent 的。我们的角色是从知识图谱中找相关上下文，让用户勾选后附加到消息中。不是回答问题。

**修正 2 — 不是回答，是提供 context items**：
RAG 的输出不应是"answer"，而是可勾选的 context items（decision/background/warning）。agent 收到的是"用户的话 + 附加的上下文"。

**修正 3 — entity 拆分应基于用户意图**：
"对比 A 和 B" 是一个比较任务（不拆分），"修复 bug 然后优化 UI" 是两个并列任务（拆分）。机械分词/分实体会丢失语义。

**修正 4 — 提取和检索应使用相同方法**：
提取时把复合概念保持完整（"URLSession 回调中 @MainActor 失效" 是一个 lesson），检索时也应该用完整语义搜索（不拆成 URLSession + @MainActor 分别搜）。

### A.7 未解决的问题

1. **Agent 回复的知识**：当前只提取用户消息。但 agent 回复中包含大量技术方案（如 Vue vs React 对比），这些知识丢失了。需要纳入 agent 回复但要控制 token 成本。

2. **知识的时效性**：如何表达"这个 constraint 在 macOS 15 上有效，macOS 16 已修复"？当前只有 `valid_from` / `invalid_from`，没有条件表达式。

3. **跨 Agent 知识统一**：当前只解析 Claude Code session。Copilot/Gemini/Codex 的 session 格式不同，需要各自的 adapter。但知识图谱应该统一。

4. **社区检测**：原设计的 Step 7（Label Propagation 聚类）未实现。当知识节点累积到数百个后，自动分组生成话题摘要会很有价值。

5. **增量处理的精确性**：当前用 `message_count` 判断 session 是否有变化。但 /resume 后新消息和旧消息混在同一文件中，需要更精确的偏移追踪。

6. **实体消解的性能**：每个 entity 的 Stage C 调一次 LLM（~1-2 秒），大 session 提取 50+ entity 需要 1-2 分钟纯消歧。可以批量化或提高 embedding 阈值减少 LLM 调用。
