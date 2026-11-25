# Documentation

## Current Design

| Document | Content |
|---|---|
| [CTM Concept Model](ctm-concept-model.md) | Authoritative design: a context manager as an assistant—interface, memory (root node, Goal／Task, two types of constraints, decisions and documents), queries and tasks, execution and control layer, rules, scene walkthroughs |
| [Goals and Method](goals-and-method.md) | What to achieve, how to measure it, and how to proceed (reasoning before experiments; historical records are used to understand user habits, not directly as tests); Section 6 covers the underlying capabilities and their order of priority for the future direction (personal assistant) |
| [Evolution of Technology Choices and Processing Logic](evolution.md) | From Yanmo Companion (2026-04) to the present: the form of memory, processing flow, models and evaluation methods at each stage, why they changed, and what remained; written before cleaning up the historical archives to replace process materials in the archives |
| [CTM Implementation Plan](ctm-implementation-plan.md) | Complete implementation steps mapped to the concept model: mechanism chain, item-by-item comparison, evaluation of each step and its downstream impact |
| [Evaluation and Optimization Plan for Blocks 3–6](blocks-3-6-plan.md) | Self-evaluation and next steps for four blocks: memory write, execution context, executor interaction, and work status; first establish paired evaluations, then optimize block by block |
| [Boundaries and Interfaces of the Blocks](block-interfaces.md) | Triggers, data read and written, users, properties that must be guaranteed, reference inputs for independent evaluation, and code locations for each of the 9 blocks; where a single call produces results for multiple blocks |

## Supporting Research

| Document | Content |
|---|---|
| [User Behavior Patterns](user-behavior-patterns.md) | User habits summarized from historical collaboration; the initial content of CTM’s “understanding of the user” |
| [Agent Reply Analysis](agent-reply-analysis.md) | What executor replies contain and what is actually used; the basis for result processing and output conventions |
| [Related Work Research](related-work.md) | Comparisons with and lessons drawn from work on orchestrators, task tree memory, instruction files, memory blocks, context engineering, multi-agent interfaces, and more |

## Prototypes and Tools

| Document | Content |
|---|---|
| [CTM Implementation](ctm-implementation.md) | `src/context_tree/ctm2/` rewritten according to the concept model: modules and offline tests |
| [Authentication](authentication.md) | The project’s own GitHub／Copilot login tool |
| [Development](development.md) | Local environment, code layout, and checks |

## Archives

Earlier designs, direction corrections, research logs, and old pipelines were cleaned up on 2026-11-23 at the user’s request. See [Evolution](evolution.md) for the process and lessons learned.
