# Documentation

## Design and Method

| Document | Content |
|---|---|
| [CTM Concept Model](ctm-concept-model.md) | Authoritative design: a context manager as an assistant—interface, memory (root node, Goal／Task, two types of constraints, decisions and documents), queries and tasks, execution and control layer, rules, scene walkthroughs; section 10 covers future directions |
| [Goals and Method](goals-and-method.md) | What to achieve, how to measure it, and how to proceed (reasoning before experiments; historical records are used to understand user habits, not directly as tests); section 6 covers the underlying capabilities and their order of priority for the future direction (personal assistant) |
| [Evolution of Technology Choices and Processing Logic](evolution.md) | From Yanmo Companion (2026-04) to the present: the form of memory, processing flow, models and evaluation methods at each stage, why they changed, and what remained |

## Implementation and Evaluation

| Document | Content |
|---|---|
| [Implementation Status](implementation-status.md) | Current configuration (flow, models, prompt versions), the modules of `src/context_tree/ctm2/`, and for each concept item the user's requirements, the code in the running flow, how it was evaluated and its status |
| [Block Evaluations](block-evaluation.md) | The 9 blocks (judgments) with the data they read and write; evaluation rules; the evaluations behind the current version of each block, including rejected versions |

## Supporting Research

| Document | Content |
|---|---|
| [User Behavior Patterns](user-behavior-patterns.md) | User habits summarized from historical collaboration; the initial content of CTM’s “understanding of the user” |
| [Agent Reply Analysis](agent-reply-analysis.md) | What executor replies contain and what is actually used; the basis for result processing and output conventions |
| [Related Work Research](related-work.md) | Comparisons with and lessons drawn from work on orchestrators, task tree memory, instruction files, memory blocks, context engineering, multi-agent interfaces, persistent AI colleagues, and more |

## Development

| Document | Content |
|---|---|
| [Development](development.md) | Local environment, code layout, running the pilot, history import, usage report, and checks |
| [Authentication](authentication.md) | The project’s own GitHub／Copilot login tool |

## Earlier Material

Earlier designs, direction corrections, research logs and old pipelines were removed on 2026-11-23; the implementation plan with its
execution record and the plan for blocks 3–6 were replaced on 2026-11-25 by the two documents above. All of it is in the git history,
and [evolution](evolution.md) keeps the decisions and lessons.
