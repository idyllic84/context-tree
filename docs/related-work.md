# Related Work Research

> 2026-10-28 Searched via LangSearch and directly read public sources (documentation, paper abstracts, official blogs). Only records what was read; search coverage was limited, so it does not claim that “no one has done this.”
> The comparison is based on the goals and design of the [CTM concept model](ctm-concept-model.md), not on “adding something because others have it.” Source excerpts and search records are kept in the private directory `research/related-work-ctm2/`.

## 1. Overall Conclusions

No work was found that has all of the following: the user talks to only one assistant, multiple work items run in parallel without session boundaries; a Goal／Task work tree across time;
two kinds of constraints, inherited by work scope and effective by object; queries separate from tasks; executors driven through a control layer with contracts; and user correction on the tree.
But each block has similar approaches, distributed across different systems:

| CTM component | Closest work |
|---|---|
| An assistant coordinates multiple executors and maintains plans and progress | Magentic-One's orchestrator (task ledger, progress ledger); the lead agent in Anthropic's multi-agent research system |
| Task tree as working memory | HiAgent (subgoal working memory); Task Memory Engine (task memory tree) |
| Task lists, dependencies, planning | Task Master (generates tasks with dependencies from a PRD); Kiro specs (requirements／design／tasks) |
| Constraints and instruction files | AGENTS.md, CLAUDE.md, Kiro steering (conditional loading by file pattern), Copilot custom instructions |
| Persona and understanding of the user | Letta's persona and human memory blocks; Claude Code's auto memory; Devin's knowledge suggestions |
| Documents and externalized memory | Anthropic's artifact system; Manus “use the filesystem as context”; ACE's evolving playbook |
| Time | Zep／Graphiti's temporal knowledge graph |
| Multi-executor interfaces | Vibe Kanban (kanban board＋one workspace per agent); parallel session tools such as Claude Squad and Conductor |
| Topic trees within a session | Context-Agent, Conversation Tree Architecture (compared previously; the original text was removed during archive cleanup) |

The differences CTM can claim lie in the combination of these elements and several specific semantics: placing tasks according to service relationships, distinguishing two kinds of constraints, separating queries from tasks,
giving persona and understanding of the user only to CTM, and treating user corrections as authoritative events. This judgment is limited by the coverage of the search.

## 2. Item-by-Item Comparison

### 2.1 Orchestrators and Lead Agents

**Magentic-One** ([AutoGen documentation](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html)):
The orchestrator first makes a plan and maintains facts and conjectures in a “task ledger” (Task Ledger); at each step it creates a “progress ledger” (Progress Ledger),
reflects on progress and checks whether the task is complete. If not, it assigns a subtask to a specialized agent and updates progress after completion.
- Same: A coordinator maintains plans and progress, assigns executors, and checks for completion.
- Different: It is oriented toward a single run of a single task. It has no long-term memory across tasks, no user dialogue layer or interface, and no scope for constraints.
- Worth borrowing: The explicit self-check in the progress ledger for “whether progress is being made or work is stuck” corresponds to “stop and escalate when there is no progress” in CTM's control layer; when stuck, CTM decides whether to replan.

**Anthropic's multi-agent research system** ([engineering blog](https://www.anthropic.com/engineering/built-multi-agent-research-system)):
The lead agent saves the plan to memory to prevent it from being truncated when context exceeds the limit; when writing task descriptions for subagents, each subagent needs “an objective, an output format, guidance on which tools and sources to use, and clear task boundaries,”
otherwise work may be duplicated or gaps left; subagents write results to external artifacts such as the filesystem and return only lightweight references to the coordinator; when approaching the limit, a subagent with a fresh context is started and a handoff is performed.
- Same: This almost corresponds to CTM's execution contract (objective, output, boundaries), output conventions (long content goes into documents, replies give only brief results), and continuation by a new executor through a handoff.
- Worth borrowing: Explicitly state the output format and tool or source guidance in the contract; provide an effort budget based on task complexity (it determines the number of subagents and tool calls based on complexity).

### 2.2 Task Trees and Task Lists

**HiAgent** ([arXiv 2408.09559](https://arxiv.org/abs/2408.09559)): Organizes working memory for a single long task by subgoals and summarizes observations when a subgoal is completed.
- Same: Results are summarized and left for the upper level upon completion, similar to CTM's “fold upward on completion.”
- Different: It manages a single agent's context within one long task; CTM is an independently proposed design that manages memory and context across time and work between the user and multiple executors.

**Task Memory Engine** ([arXiv 2504.08525](https://arxiv.org/abs/2504.08525)): Tracks execution with a hierarchical task memory tree. Each node corresponds to a task step,
stores inputs, outputs, status, and subtask relationships, and dynamically generates prompts based on the “path of the currently active node”; it also notes future support for reusable substeps, converging paths, and shared dependencies (a directed acyclic graph).
- Same: Tree nodes have status, and context is composed according to the current node's path—consistent with CTM's “task constraints on the path enter the contract.”
- Different: Nodes are steps within a single task; there is no user, global layer, constraint types, or document knowledge.

**Task Master** ([README](https://github.com/eyaltoledano/claude-task-master)): Generates tasks from a PRD. Tasks have dependencies, subtasks, and status,
and it provides tools such as “next task,” “expand task,” “complexity analysis,” and “tags and workflows” for coding agents to call.
- Same: Planning, dependencies, executable order.
- Different: The task list is operated directly by the user or agent. There is no assistant that understands the dialogue, and it does not record constraints or decisions.
- Worth borrowing: Decide whether to split further based on complexity; this can serve as a basis for the CTM planner's splitting depth.

**Kiro specs** ([documentation](https://kiro.dev/docs/specs/)): Each spec contains requirements.md (user stories, acceptance criteria), design.md (architecture, implementation considerations),
and tasks.md (trackable discrete tasks), and proceeds through three stages: “requirements → design → implementation.”
- Same: Deliverables and plans are written as documents, and tasks are trackable.
- Different: Specs are organized by feature and initiated by the user, with no memory across work or assistant layer.

### 2.3 Constraints and Instruction Files

**AGENTS.md** ([agents.md](https://agents.md/)): Project instructions for coding agents; large repositories can place nested AGENTS.md files in subprojects,
and agents read the nearest one in the directory tree, with “nearest takes precedence.” **CLAUDE.md** ([Claude Code memory](https://docs.anthropic.com/en/docs/claude-code/memory)):
CLAUDE.md files in the working directory and its parent directories are loaded at startup, while those in subdirectories are loaded as needed; `.claude/rules/` can scope rules to specific file types; AGENTS.md can also be read directly.
**Kiro steering** ([documentation](https://kiro.dev/docs/steering/)): Project files such as product.md (product purpose, users, goals), tech.md, and structure.md;
they can be set to always load, load by file pattern (for example, only when working on `components/**/*.tsx`), or load manually; there is also user-level global steering.
GitHub Copilot also supports project custom instructions and AGENTS.md ([GitHub documentation](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-copilot-overview)).
- Similarities: They are equivalent to CTM's object constraints and global preferences—written in project files, carried with the project, scoped by directory or file pattern, with nearer and more specific ones taking precedence.
  Kiro's product.md is similar to the overall goal at CTM's root node, and user-level steering is similar to preferences at the root.
- Differences: They are all static instructions maintained by humans. They have no task constraints for “how to do this work,” nor constraints that expire when the work ends; no assistant writes or maintains them based on conversations.
- Evidence of risk: In practice, reports of agents not following rule files are common (for example, [Cursor rules ignored](https://dev.to/olivia_craft/why-cursor-agent-ignores-your-cursorrules-and-rewrites-the-wrong-files-5977)),
  supporting CTM's approach of stating requirements explicitly in the contract and having the execution control layer check the diff.
- Lessons to draw: Object constraints for multi-file modules can be expressed as “apply by path pattern” or “nested, nearest takes precedence,” rather than only in a project-level `ctm.md`.

### 2.4 Persona, Understanding of the User, and Knowledge

**Letta memory blocks** ([documentation](https://docs.letta.com/guides/agents/memory-blocks)): The persona block stores the agent's own role and way of behaving, and the human block stores key information about the user;
memory blocks are always in the context, editable, and shareable among multiple agents. Read-only policy blocks can also be shared with all agents.
- Similarities: persona and human correspond directly to CTM's persona and understanding of the user.
- Differences: Letta puts them in the agent's own context; CTM uses them only for itself and does not pass them to executors—executors need the concrete instructions written from them. Shared read-only policy blocks correspond to the global constraints CTM passes to executors.

**Devin knowledge** ([documentation](https://docs.devin.ai/product-guides/knowledge)): Each piece of knowledge has a “trigger description” and is retrieved when relevant to the current work;
Devin automatically suggests knowledge to remember based on the user's feedback in conversations, and the user edits and saves it or ignores it; knowledge can be enabled or disabled per user.
**Claude Code automatic memory**: It takes notes on its own based on the user's corrections and preferences, and loads them together with CLAUDE.md at the start of each conversation.
- Similarities: CTM's practice of treating “inferred preferences first as suggestions, which take effect after user approval” is consistent with Devin's knowledge suggestions.
- Lessons to draw: Write “when to use” descriptions for documents and constraints, for retrieval and to help executors decide whether to read them.

**ChatGPT project memory** ([TechRadar](https://www.techradar.com/ai-platforms-assistants/chatgpt/chatgpt-project-only-memory-is-live-and-it-might-change-how-you-work-with-ai)):
“Project-only memory” can be enabled, so memories outside the project have no effect within it.
- Comparison: It uses isolation to avoid interference; CTM uses global memory plus scope (task constraints follow the tree, object constraints follow the object) to avoid interference while retaining cross-work references.

### 2.5 Externalized Memory and Context Engineering

**Manus** ([blog](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)): It treats the file system as context, allowing content to be discarded while retaining recoverable references;
in complex tasks, the agent maintains and progressively checks off a todo.md, using “recitation” to keep the goal in attention; it retains error records so the model can see failures; it designs context around KV cache hits.
**Context engineering** ([Lance Martin](https://rlancemartin.github.io/2025/06/23/context_engineering)): It groups methods into four categories: writing out (storing outside the context), selection, compression, and isolation.
**ACE** ([arXiv 2510.04618](https://arxiv.org/abs/2510.04618)): It treats context as a continuously evolving playbook, using incremental updates to avoid information collapse during rewriting.
- Similarities: CTM's “knowledge is in documents, only paths and key points are in the context” and “executors read for themselves when needed” are writing out and selection; a new executor provides isolation.
- Lessons to draw: The executor can maintain a short checklist of deliverables against the contract during execution, which the execution control layer can use to check formal completion; knowledge documents can be updated incrementally by section rather than rewritten in full.

### 2.6 Time

**Zep／Graphiti**（[arXiv 2501.13956](https://arxiv.org/abs/2501.13956)）：A temporal knowledge graph for agents. Facts have validity intervals and can be updated over time.
- Similarity: CTM’s constraints and decisions have validity intervals; those that are replaced are retained as history.
- Difference: It uses entities and facts as its units; CTM uses work, constraints, decisions, and documents.

### 2.7 Multi-executor interfaces

**Vibe Kanban**（[README](https://github.com/BloopAI/vibe-kanban)）：Plans work using a kanban board. When work is ready, it creates a workspace for each item of work, where the agent has its own branch, terminal, and development server.
The work is reviewed when complete. Tools such as Claude Squad and Conductor manage multiple parallel agent sessions in one interface, commonly using git worktrees for isolation.
**Jules**（[Google blog](https://blog.google/technology/google-labs/jules/)）：Executes asynchronously and provides a plan, reasoning, and a diff of the changes upon completion.
- Similarity: CTM’s task tree and execution view; each executor works in an isolated working directory (an execution-level matter in CTM).
- Difference: In these tools, the user does the planning, assignment, and remembering; there is no assistant that understands the conversation and maintains memory and constraints across work.

### 2.8 Surveys and evaluations of memory research

[Memory for Autonomous LLM Agents（2603.07670）](https://arxiv.org/abs/2603.07670)、[Evaluating Memory Structure in LLM Agents（2602.11243）](https://arxiv.org/abs/2602.11243)、
[Agentic Memory（2601.01885）](https://arxiv.org/abs/2601.01885v2)：Respectively survey memory mechanisms, compare memory structures, and learn to manage long- and short-term memory in a unified way.
They focus on the memory of a single agent, and their evaluations mostly measure recall through question answering. This differs from CTM’s “user—assistant—multiple executors” structure and its goal of “whether the next step is done right.” They can serve as references for evaluation design.

### 2.9 Persistent AI colleagues: Grok Bot and OpenBot（2026-11-24）

**Grok Bot**（SpaceXAI, released in 2026-08, 1.0 in November）is closed-source. Available implementation materials include: source code reconstructed from `app.asar` in the public 0.18.0 installation package (a community reconstruction, not official, organized according to “reconstruct only behavior backed by concrete evidence”),
an item-by-item analysis of compiled code from a newer host program (distinguishing what the code proves, what is inferred, and what remains undetermined), and official documentation.
- The deeper problem it solves is **making the executor persist**: an LLM agent is one session, exists only while running, holds one window, does one thing at a time, and depends on a device.
  Its solution: one persistent cloud computer per user, with the agent loop running in a host program on it; “talking” and “working” are separate (each turn of the main conversation is very short, only replying, bookkeeping, and dispatching,
  with heavy work handed to invisible background executors, which start from scratch, receive briefs written by the main conversation’s model, and have no tool for speaking to the user); one long-term conversation per bot is sustained through summaries;
  learned memory consists of facts, preferences, and rules about the user (evidence is recorded each turn, synthesized in the background, required to cite evidence, and reviewed by a second model; entries written by the user are protected); schedules, events, and subtask completions wake it;
  automatic review distinguished by operation surface, and credentials used only by reference.
- Automatic session creation and reuse: the main conversation opens an executor for each independent workflow, sends additions and corrections to the one already running (`MessageSubagent`), and can resume completed ones by ID (`resume`);
  dispatch is decided by the main conversation’s model in the tool loop, based on its own conversation window and a todo list (“memory for multitasking,” cleared when done).
- Work itself is transient: an executor’s context is discarded when exhausted, todos are cleared when done, and there is no structured state for each item of work. It bets on repetitive matters that can be divided by function,
  and retains “how to work for this person” long term.

**OpenBot**（CopilotKit, MIT, one of the most prominent open-source alternatives）open-sources an application template (frontend, shared definitions, and adapters for various frameworks); the server is released as a compiled image,
and persistent conversations, memory, and automatic learning are in a separately licensed service. Unlike Grok Bot: it has enterprise multi-tenancy; which bot receives a message is decided by an intent router running in the deployment; each bot has many independent conversations;
handoffs between bots specify the task and boundaries in a set format, with addressing, destination, and depth determined by the deployment rather than the model; `delegate` in a conversation opens a task thread that the user can see and enter directly,
while `follow_up` sends a message to an existing task in that conversation; memories formed by bots require user confirmation. Its code comments record dispatch errors observed in testing: a new deliverable treated as an addition, the wrong task stopped,
and an answer to a task report not sent back to the task.

**Relationship to CTM**: Both place a “voice” between the user and executors that forget. Grok Bot makes the executor persistent and the work structure transient; CTM makes the work structure persistent (organized by work,
grounded in the user’s words, with replacement history, and execution context assembled by code), while executors can be replaced. CTM does not borrow: having the model write briefs on the spot, creating multiple bots by function, starting work proactively without a request,
multiple executors sharing credentials, or invisible autonomous memory. Mechanisms worth considering are listed by underlying capability in the order of section 6 of [Goals and Methods](goals-and-method.md):
execution routing and authorization by operation surface, credential references, an evidence—synthesis—review memory pipeline, approvals becoming rules, rules distinguished by wake-up source, and degradation when no one is present.
The three categories of dispatch errors observed in OpenBot testing can serve as test categories for block 1.

## 3. What is worth adopting: judging by CTM’s positioning and goals

CTM is positioned as the user’s sole conversational assistant, managing multiple parallel items of work and multiple executors, with memory that is not tied to a session. Whether a practice is worth adopting is judged only by whether it advances
the six goals in [Goals and Methods](goals-and-method.md), and whether it conflicts with CTM’s positioning. The fact that others have something we do not is not a reason.

### 3.1 Understand correctly: determine which work and which object the user is referring to

| Practice | Source | Judgment | Reason |
|---|---|---|---|
| Explicitly reference objects in messages (macros, @) | Devin’s knowledge macros | Adopt | Like interface selection, this is an unambiguous pointing signal at almost zero cost; when users want to be precise, they have a way to be precise without relying on CTM to guess |
| Knowledge has trigger descriptions of “when to use” | Devin | Adopt (for both documents and constraints) | Both retrieval and executor self-selection of documents rely on them; the number of CTM’s documents will keep growing, making accurate selection difficult without descriptions of their uses |
| Persona and user information are limited in length and always present | Letta memory blocks | Adopt for CTM itself | Understanding of the user is always needed to understand ambiguous messages, and on-demand retrieval could miss it; limiting the length keeps costs stable. But it is placed only in CTM’s understanding context, not given to executors |
| Hybrid keyword and semantic retrieval (such as BM25) | Zep and others | Do not adopt for semantic judgment | Conflicts with the principle that “semantic judgment uses only LLMs or vectors.” Looking up exact identifiers such as file paths and commit hashes is addressing, where it can be used |
| Isolate memory by project | ChatGPT project memory | Do not adopt | CTM needs to reference decisions and results across work; interference is controlled by scope (task constraints follow the tree, object constraints follow the object) |
| Divide an in-session tree by topic | Context-Agent、CTA | Do not adopt | The previous comparison already explained: constraints apply according to the work and objects they affect, not the topic in which they were stated |

### 3.2 Execute correctly: executors get enough context and do the work correctly

| Practice | Source | Judgment | Reason |
|---|---|---|---|
| State the goal, output format, tool and source guidance, and boundaries in the task description | Anthropic | Adopted (already included in the execution contract) | Its experience is that without these, subagents repeat work or leave gaps, which is exactly what CTM's execution contract is meant to prevent |
| Set an effort budget according to complexity | Anthropic | Adopted | The control layer needs a budget as a basis for deciding “whether to stop” |
| Executors maintain a checklist against deliverables | Manus's todo.md | Adopted (execution-layer convention) | Keeps the goal in focus during long executions; the control layer also uses it to judge formal completion |
| Keep a record of failures | Manus | Adopted: record failed attempts and their reasons in progress | For a new task or upon reactivation, the executor is new and cannot see the old session; without a record of failures, the new executor will repeat them—this is precisely the source of high-consequence errors such as “repeating a non-repeatable action” |
| Explicitly check “whether progress is being made” and replan when stuck | Magentic-One progress ledger | Adopted: when the control layer detects a stall, it hands control back to CTM for replanning | The risk of automatically “continuing” is spinning in place; a stop condition and a way back to planning are needed |
| Nested instruction files, with the nearest taking precedence | AGENTS.md, CLAUDE.md, Kiro steering | Adopted: allow nested `ctm.md` files in subdirectories | Constraint scope is more precise for multi-file modules; executors are familiar with this convention and are less likely to miss the files |
| Conditional applicability by file pattern | Kiro steering, Claude rules | Adopted for `ctm.md` entries | Needed when a module spans directories or involves only some files |
| One orchestrator handles all execution back-and-forth | Magentic-One | Not adopted | It would burden CTM with execution details; CTM has already delegated this part to the control layer |
| Isolated workspaces (branches, terminals, development servers) | Vibe Kanban, Conductor, etc. | Belongs to the execution layer | The concept layer recognizes only working directories; the execution layer provides isolated working directories for parallel modifications |

### 3.3 Remember: recover the correct state after a long time

| Practice | Source | Judgment | Reason |
|---|---|---|---|
| Write progress at milestones during execution | Anthropic (the main agent first saves the plan to memory) | Adopted | CTM's continuity depends on write-back; if write-back occurs only at the end, completed work will be lost if execution is interrupted or context reaches its limit |
| Write artifacts externally and pass only references | Anthropic, Manus | Already part of CTM's design | Confirms “put long content in documents and give only brief results in replies” |
| Update knowledge incrementally rather than rewriting the entire document | ACE | Adopted | Documents are repeatedly modified across many executions; rewriting the entire document can easily lose earlier content |
| Give facts validity intervals and invalidate old facts when contradictions arise | Zep／Graphiti | Already has a counterpart | CTM's decisions and constraints already have validity intervals and replacement; it will not switch to a knowledge graph organized by entity |

### 3.4 Answer accurately: knowledge queries

| Practice | Source | Judgment | Reason |
|---|---|---|---|
| Attach sources to each conclusion | Anthropic's citation step | Already has a counterpart | Query replies are already required to be traceable |
| Save query results as searchable records | — | Already in place | — |

### 3.5 Low burden: users correct less, and one correction is enough

| Practice | Source | Judgment | Reason |
|---|---|---|---|
| Suggest what to remember based on user feedback, then save it after the user edits it | Devin, Claude automatic memory | Adopted (adding “approve after editing”) | Consistent with CTM's “make inferences as suggestions first”; allowing edits is easier than only being able to accept or reject |
| Draft constraint files from a project's existing documentation files | Kiro's foundation file generation | Adopted, as a suggestion | Reduces what users have to explain verbally when starting a new project; only drafts the files, without making them effective directly |
| Organize large deliveries as “requirements → design → tasks” | Kiro specs | As a template for the planner | Useful for large deliveries; but many user messages are queries and corrections, so it cannot become a fixed workflow for all work |
| Kanban view | Vibe Kanban | An optional alternative view | Convenient for browsing by status; the main structure remains a tree because task constraints must propagate along the tree, which a flat Kanban board cannot express |

### 3.6 Cost is measurable

| Practice | Source | Judgment | Reason |
|---|---|---|---|
| Use cache hit rate as a key metric and keep the front of the context stable | Manus | Adopted | Putting the execution contract and content that remains unchanged over the long term at the front, and what changes this time at the back, adds almost no complexity but directly reduces cost and latency; add cache hit rate to cost metrics |
| Multi-agent token overhead is significantly higher than single-agent overhead | Anthropic | As a reminder | The structure of CTM plus the control layer plus executors also has overhead, which must be included in evaluations |

### 3.7 Summary

Everything adopted fits within CTM's existing structure, with no new concepts: the execution contract has several additional items; the control layer has “hand control back to CTM for replanning when stuck” and “milestone progress”;
failed attempts are recorded in progress; `ctm.md` can be nested and have path patterns; documents have purpose descriptions and are updated incrementally; explicit references can be made in conversation; persona and understanding of the user have limited length and are always present;
inferred memories can be edited before approval. These have been written into the [CTM concept model](ctm-concept-model.md).
What was not adopted was mainly rejected because it conflicts with CTM's positioning: burdening CTM with execution details, handing persona over to executors, isolating memory by project, using keywords to make semantic judgments, and replacing the work tree with topics or a Kanban board.
