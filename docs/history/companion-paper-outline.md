> Historical development document. Preserved for provenance; not the current specification. Personal paths/session identifiers are anonymized. See [archive index](README.md) and [current architecture](../architecture.md).

# Companion 论文写作 outline

draft 版,供后续选 venue / 选实验 / 切分 contribution 时复看。

---

## Core thesis (中心论点)

> AI coding agent 之间的 dialogue memory 是与 chat memory 根本不同的 retrieval problem。
> 它的目标是 **work-continuation** (让下一个 agent 接着前一个干) 而非 factoid recall;
> extraction 与 retrieval 必须围绕 **speech-act + 时间漂移 + 树拓扑** 三个被现有 KG-RAG 文献忽视的维度重新设计。

## Tier 1 — 论文核心 contribution (必须重点展开)

### A. Coding agent dialogue memory 是未定义的 retrieval task

- 现有 memory benchmark (LoCoMo, MemoryGPT) 假设 "用户日常 chat,要回忆个人事实"
- 真正问题:**下一个 agent 怎么知道这件事已经决定 / 已经放弃 / 曾经卡住**
- 我们形式化 work-continuation 这个 retrieval intent
- **Negative result 实证**:LoCoMo 范式 mismatch (我们实测过,可写成 ablation 反例)
- 配 dataset characterization:Claude Code session JSONL 的统计属性 (turn 数分布、agent text 长度、tool_use 频次、session 间引用结构)

### B. Tree topology > embedding cluster for branch detection

- **反直觉发现**:RAG 默认 cosine cluster 把跨 context 同名概念错合并
- 实测案例:不同 session 都讨论 "auth refactor" 但完全不同的方案,embedding 把它们 merge 成一个 branch → 检索时混淆
- 改用 extraction-time 的 tree 结构邻域 (lit nodes 共享 parent / 互为父子) → 每个 branch 在 single session 内,语义干净
- **核心 claim**:*extraction-time 的结构 > retrieval-time 的语义*
- Ablation:embedding cosine cluster vs tree branch,看召回精度 / context 干净度

### C. Per-turn 是 dialogue extraction 的"自然原子单位"

- 统一 unit / agent_content entity / file edge anchor 三层
- 用户给的 turn boundary 比 LLM 在 agent text 里找 activity 切点稳定得多
- **Cross-layer unifying principle**
- Ablation:per-segment vs per-turn vs per-task 的检索召回对比 (我们已观察到 per-segment 让相近节点抢 top-K)
- 量化数据:per-segment ~0.7 ac/turn,per-turn ~0.5 ac/turn,~30% 实体收敛

## Tier 2 — 强支撑性 contribution

### D. Decision-centric speech-act 建模

- 7-act vocabulary:Human (instruct/constrain/ask/affirm/reject/answer/report) + Agent (propose/explain/clarify/report)
- Acceptance lifecycle:hard / soft / rejected / unclaimed
- "好的" 两字承载 propose → long-term decision 的升格语义
- 主流 dialogue act 工作没有 supervision dimension (DDA / Wilcock & Jokinen 都偏 generic)
- 这是为 human↔AI-coding-agent 这个 specific dialogue type 定制的 taxonomy

### E. Adapter-deterministic vs LLM-judgment separation

- **设计原则**:程序可推的事 (head/tail 截断、file path 抽取、时间 gap、cwd change) 全交给 adapter,LLM 只判"判断题"
- 量化收益:
  - 减少 ~30% LLM token (head/tail 不用 LLM 切)
  - 减少 hallucination surface (file path 不会被 LLM 编造)
  - 截断公式可调可解释 (≤400 全留 / >400 head 200 + tail 按总长 +100/1000 max 800)
- Generalizable 到其他 LLM 抽取系统

### F. Iterative review until convergence

- 借自 H²R (arxiv 2509.12810),但他们只做 single pass
- 我们观察:1 pass 留 catch-all "杂物 goal",2-4 pass 自然收敛
- 终止条件:0 mutation 或 max_iterations=4
- **Convergence-based extraction** 是个可推广的 pattern
- 实测:Tauri 大 session 4 轮 review 把 1 个胀的 g1 自动拆成 3 goal / 60 task,0 warning

### G. N candidate over synthesis

- 退一步,不让 LLM 综合"答案",而是返回 N 个独立 context
- 同主题跨 session → MERGED;独立主题 → 分开
- 匹配下游 agent 自己挑的消费模型 (它有自己的 reasoning,不需要被替它做决定)
- 反对"标准 QA pipeline 必须输出 single answer"的隐含假设

## Tier 3 — 工程胶水 (paper 内 1-2 句带过)

| Item | 说明 |
|---|---|
| Bi-temporal `corrected_to` LINK | 借自 AriadneMem,anchor 换成 unit_id |
| Time-aware retrieval | 每节点 `@last_at`,LLM 自判 stale |
| Path folding | ≥3 同 dir 文件 → directory entity (减边数) |
| Split-on-missing recovery | LLM 漏 task → 半批重试递归 (L1 + framing 都用) |
| Per-type bypass | file/directory bypass embedding (slug dedup) |

## Paper 结构建议

### 1. Introduction
- AI coding agent 普及 (Cursor / Claude Code / Codex / Cline)
- Cross-session memory 缺失 → 用户每次重复 context
- 现有 chat memory 解决不了 (LoCoMo style 范式 mismatch,要做 motivating example)
- Contribution 列表

### 2. Problem formulation
- Work-continuation retrieval task 定义
- Input: new query + 历史 sessions
- Output: N candidate contexts,each sufficient for next agent to continue
- Metric:reasoning continuity / not-duplicating-rejected / file-ownership awareness / etc.
- 与 factoid QA 的 metric 区分

### 3. Method
- 3.1 Speech-act extraction (Tier 2-D)
- 3.2 Tree extraction with iterative review (Tier 2-F)
- 3.3 Per-turn granularity (Tier 1-C)
- 3.4 Adapter-LLM responsibility split (Tier 2-E)
- 3.5 Tree-branch retrieval (Tier 1-B)
- 3.6 N-candidate output (Tier 2-G)

### 4. Experiments
- 自建 benchmark:从 Claude Code session 提 N 个 query → expected continuation context
- Baseline:
  - LoCoMo style memory pipeline (negative)
  - GraphRAG (entity-centric)
  - Flat dense retrieval (cosine over all nodes)
  - BM25 + dense hybrid (negative — 我们已实测)
  - Embedding cluster branch (negative — 已实测)
- Main result:tree-branch + per-turn 在 work-continuation metric 上显著好
- Ablation:per-segment / per-turn / per-task / embedding-cluster / tree-branch
- Cost:LLM token 量 / sync 时长 / retrieval 时长

### 5. Discussion / Limitations
- Dataset domain:dev workflow,可能不直接泛化到非编程 agent supervision (法律 / 医疗 / 设计)
- LLM-judged retrieval 的成本 vs 收益
- 单 device assumption (per-device file id)
- 没有评估 "人确认" agent 接续是否真的更顺 (主观评估缺)

### 6. Related work
- Memory: LoCoMo / mem0 / Letta / MemGPT / Graphiti / Zep
- Dialogue acts: SWBD-DAMSL / DDA / Wilcock & Jokinen / ConvEngine
- KG-RAG: GraphRAG / A-MEM / GraphRunner / AriadneMem / H²R / Reflexion / Self-Refine
- Coding agent benchmarks: SWE-bench (任务执行,不是 memory) / CodeReasoner

### 7. Conclusion
- AI agent memory 不是单一问题,要按 supervision pattern 重新切
- Coding-agent memory 的关键约束是 work-continuation,而不是 factoid recall
- 我们的架构是这个约束的一组 design choice,可推广

## 关键提醒

### 不要写成 system paper
"我们做了一个 sync pipeline,跑 ~10min" 不是论文卖点。
论文卖的是:
1. **Problem 重新定义** (Tier 1-A) — coding agent memory 是新问题
2. **Tree > embedding 的 empirical claim** (Tier 1-B) — 反直觉,有数
3. **Per-turn unifying principle** (Tier 1-C) — cross-layer 设计选择

### Negative result 是最值钱的 asset
- LoCoMo paradigm mismatch (Stage 14)
- BM25 + dense hybrid 失败 (Stage 15)
- Embedding cluster branch 失败 (Stage 16 触发)
**三个 negative result 帮你画出 problem 的边界,比 100 个 positive result 更有论文相。**

### Venue 候选
| Venue | 切入角度 |
|---|---|
| **EMNLP / NAACL Findings** | 偏 NLP,聚焦 dialogue extraction + memory |
| **EMNLP / NAACL Main** | 如果实验扎实,有 negative results,有 ablation |
| **NeurIPS Datasets and Benchmarks** | 如果愿意 publish 数据集 (注意隐私) |
| **ICLR** | 偏 ML,如果想强调 retrieval-augmented agent 的 inference loop |
| **OSDI / ATC** | 如果包装成 system paper (但需要更多 throughput / latency 数据) |
| **CHI** | 如果做用户实验 ("用了我们 memory 的 agent 让用户少重复说 X 次") |

**首选**:EMNLP findings + 配套 dataset paper / artifact track。

### 必须先做的两件事
1. **真做一个 benchmark**:从已有 Claude Code session 抽 30-50 个 query,人工标注 expected continuation context。否则没有量化的 main result。
2. **跑 baseline 对比**:至少 LoCoMo 风格 + GraphRAG + flat cosine 三个,各做 ablation。

## 工作量估算

- Benchmark 制作:~2 周 (人工标注最累)
- Baseline 实现:~2 周 (复用 LoCoMo / GraphRAG 开源实现)
- 主实验 + ablation:~1 周
- Writing:~3 周
- Total:~2 月专注 (按 50% 精力 ~4 月)

## 备注:写之前要 reality check 的事

1. 数据来源是否能 release? 用户隐私 / Anthropic API 服务条款 / 项目 IP
2. claim "tree > embedding" 要够强 — embedding cluster 的失败案例要 reproducible
3. "work-continuation metric" 要严格定义,不能是主观打分
4. 跟最新 (2025-2026) coding agent memory 工作对齐 (mem0 在加 coding 支持,要看一下)
