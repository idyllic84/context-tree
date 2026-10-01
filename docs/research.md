# Research context and citation corrections

The relevant comparison is **organization and selection of sufficient context**, not merely whether a product advertises persistent memory. This is a targeted research note based on material checked during development through 2026-10-01, not an exhaustive literature review or independent reproduction.

## Closest mechanisms

| Work | Relevant mechanism | Boundary relative to Context Tree |
|---|---|---|
| [Context-Agent](https://arxiv.org/abs/2604.05552) | Dynamic dialogue trees, current path plus summaries of other branches/topics | Direct organization/selection neighbor; published NTM data has 405 conversations and a maximum of 27 turns, not thousands of tool-rich turns. Inactive summaries still accumulate. |
| [xMemory](https://arxiv.org/abs/2602.02007) | Messages, segments, evidence components, semantic groups; progressive source expansion | A strong alternative to task-based organization. Reported dialogue-QA benefits do not prove task-tree superiority or coding execution benefit. |
| [MemTree](https://arxiv.org/abs/2410.14052) | Dynamic hierarchical memory with semantic insertion | Tree memory itself is established prior work, not a sufficient novelty claim. |
| [Task Memory Engine](https://arxiv.org/abs/2504.08525) | Task structure and active-path prompt synthesis | Close structural idea; early quantitative evidence is narrow. |
| [HiAgent](https://arxiv.org/abs/2408.09559) | Current subgoal details, summaries of old subgoals, explicit history recovery | Actually changes active working context; tested on bounded interactive environments rather than long coding dialogue history. |
| [HMT](https://arxiv.org/abs/2603.07024) | Intent → stage → action retrieval for web agents | Strong task-aware retrieval neighbor; several representations/planning changes differ in its flat comparison. |
| [ReAcTree](https://arxiv.org/abs/2511.02424) | Dynamic execution/delegation tree and goal-level episodic examples | Execution hierarchy is not the same as a preorganized historical index. Smaller local input need not mean lower total runtime. |
| [Confucius Code Agent](https://arxiv.org/abs/2512.10398) | Hierarchical file memory plus context compression in coding workflows | Relevant coding system; tree and compression contributions are not fully isolated. |
| [Recursive Language Models](https://arxiv.org/abs/2512.24601) | External source context with programmatic inspection and recursive calls | Avoids putting all source text in one model call, but selection is substantially query-time computation rather than a persistent task index. |
| [Context-Folding](https://arxiv.org/abs/2510.11967) | Branch subtask execution and fold intermediate history | Supports active-context management; do not equate reported active-context reduction with total cost or lossless retrieval. |

Additional counterpoints include [stale-observation masking](https://arxiv.org/abs/2606.00408) and [SWE-Pruner Pro](https://arxiv.org/abs/2607.18213). Simple masking or tool-output pruning can be competitive, and savings can disappear through extra calls. They are important baselines, not proof that task structure is unnecessary.

## Benchmark boundaries

[SWE Context Bench](https://arxiv.org/abs/2602.08316) evaluates reuse of coding experience with executable outcomes. [CAPA](https://arxiv.org/abs/2607.26611) studies cross-session personalization of ambiguous coding requests. [RoadmapBench](https://arxiv.org/abs/2605.15846) studies extended software development across versions.

The earlier statement that no coding-memory benchmark exists is too broad and must not be repeated. None of these sources alone establishes a complete benchmark for this prototype's exact combination of task-branch selection, necessary ancestor/dependency preservation, irrelevant-history exclusion and lifecycle cost.

## Corrections to archived citations

Some historical notes contain incorrect or overextended attributions. They are retained as historical records, not endorsed:

- arXiv `2403.13013` is an intrusion-detection classification paper, not evidence for “Semantic XPath” or “TaciTree.”
- arXiv `2511.02424` is ReAcTree, not “PersonaTree/Inside Out.”
- [H²R](https://arxiv.org/abs/2509.12810) studies hierarchical hindsight memories; it should not be described as a single-pass Goal/Task tree-review algorithm that this implementation directly extends.
- A named tree representation does not prove logarithmic retrieval. The current code still performs dense index scans.
- A failed small LoCoMo trial or hand-picked demo is not evidence of general superiority on a newly named task.

For a paper or public claim, recheck titles, versions, task domains, protocols and baselines against the primary work. Do not inherit a citation merely because an archived design document contains a link.

## Research hypothesis worth testing

With the same source evidence, model and total budget, can task-evolution structure improve relevant-context completeness while keeping active context small as unrelated history grows? Compare against full/cached context, simple compression, strong flat retrieval, evidence-group hierarchies and graph alternatives. Include branch switches, stale scope, semantically distant dependencies and queries requiring no history.
