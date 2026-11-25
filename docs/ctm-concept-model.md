# CTM Concept Model

> CTM (Context Tree Manager) is an assistant between the user and execution agents. The user talks only to CTM; CTM uses a task tree and versioned documents as long-term memory,
> answers queries, dispatches and drives executors through the execution control layer, and prepares a small but sufficient context for each execution.
> For goals and methods, see [Goals and Methods](goals-and-method.md). The old version (v1: invisible CTM, with only messages and memory as input) is preserved in
> Section 4 of [Evolution](evolution.md) (the archive has been cleaned up).
> This document is organized as “world model → memory → operation → rules → scene walkthroughs → questions to validate”; the walkthroughs in Section 7 are the basis for the designs.

## 1. World Model

### 1.1 Participants and Layers

| Participant | What it is | Relationship |
|---|---|---|
| User | A person advancing multiple items of work at once, speaking as they would to an assistant | The sole source of intent, with the highest authority |
| CTM | Assistant: understands, remembers, routes, answers queries, and relays; writes an execution contract for each execution; maintains its own records placed beside objects (`ctm.md`) | — |
| Execution control layer | The driving layer between CTM and executors | Drives executors to completion according to the execution contract, passing up only matters that need CTM |
| Executor | A single LLM call, subagent, or session, with the form chosen by CTM | Does not talk directly to the user by default (to be considered later) |
| External world | The working directory and its files, services, and cloud resources | Operated on by executors (CTM writes only its own `ctm.md`); CTM observes its changes |

**Each party's business**: The user's work—code, documents, commits, and all changes in the external world—is done by executors; executors receive only the user's exact words and context, with none of CTM's own business slipped in.
CTM's own business—its memory, its `ctm.md` records placed beside objects, and its replies and proposals in the conversation—is done by CTM itself, not handed to executors. What the user tells CTM (preferences and rules to remember, adjustments to how CTM or all executors should act in the future) is also CTM's own business and is not delivered to executors.
Reason (real pilot trial on 2026-11-23): CTM slipped the writing of object rules into the input for an executor working in the same directory, and `ctm.md` went into the PR with that work's commit; words the user asked CTM to “remember globally” were delivered to an executor, which went and changed its own global configuration file. Both cases mixed CTM's own business with the user's work.

### 1.2 Interfaces

| Interface | Contents |
|---|---|
| Conversation | One continuous conversation between the user and CTM, with multiple items of work interleaved. Only a recent number of turns are retained to interpret short references. Every message CTM writes to the user can be referred to: pending items are numbered and marked with the task they belong to. The user can also explicitly reference nodes, documents, or entries in messages (for example, @a task). The conversation has a **current task**, displayed in the interface: by default, it is the task targeted by the user's last exchange; selecting another node in the tree switches it. Reports from executors on other tasks do not change it |
| Task tree | Work nodes as understood by CTM: title, status, progress, relationships, a marker indicating execution is in progress, proposed subtasks, and task constraints. The user can move, merge, split, rename, and change the status of nodes, change which node a message is attached to, move constraints, and change constraint types |
| Execution view | Executors for each task: associated node, form, status (working, waiting, idle), and current action. Each task records its current executor session (there are also ended sessions and read-only copies for queries); the full execution record can be viewed read-only when needed. The executor's replies are for CTM; only CTM's relay appears in the conversation (5.4). The user does not speak directly in an executor session: words spoken there do not enter memory, and doing so would also mean writing to the same session at the same time as CTM |
| Query panel | For display only, with no input box. The user asks questions in the conversation; for segments CTM determines to be queries, the replies are displayed here: comprehensive, with sources and times marked, and historical and replaced statements clearly marked as historical. Previous query replies are retained for viewing |
| Document browsing | Tree node pages (task metadata, task exchange records), knowledge documents, project documents; version history and diffs; bidirectional links (3.7) |

“Breaking the session” means that memory and work are no longer tied to a particular agent session, not that conversation is eliminated.

### 1.3 What CTM Can Know

Can know: the recent part of the conversation (including what it has said and shown) and everything written to memory; the user's changes and selections in the interface;
executor outputs and execution traces; observations of the working directory and resources; time. Cannot know: the user's unstated intent or external changes that have not been observed.

### 1.4 How the User Speaks (Premise, to Be Checked Through Research on User Habits)

- When continuing something just said in the conversation, the user uses short references (“okay”, “this”, “change it”)—the recent part of the conversation is the context.
- When switching to another item of work, the user will most likely name the work, an object (project, service, file), a deliverable (document, PR, report), or a time (“the one from yesterday”); about 60% of the first messages in new sessions in the history can be located from the messages alone, while the rest rely on the environment, such as the directory in use at the time—in CTM, this corresponds to selecting a node in the tree. Advancement, control, and status requests without pointing, such as “continue”, “what about now”, and “how is progress”, always target the current task (CTM always has the item of work from the user's last exchange): if the user wants to switch to another task and then say “continue”, they first select that task.
- “The second one” and “that plan” as said by the user most likely point to content CTM has just shown or a passage currently being viewed in document browsing.
- The user may paste entire blocks of logs, errors, code, or documents: the material itself is not an instruction; the objects in it (service, file, error type) and the accompanying sentence identify the work.
- Identifiers written by the user (file name, PR number, branch, region) may contain spelling errors.
- When several items of work are running in parallel, “just now” can span many turns: in replay, the work referred to by about 5% of messages was last mentioned more than 20 turns earlier; when returning to work from several days ago, the user will most likely name the object.

## 2. Four Types of Context

| context | Reader | Purpose | Principle |
|---|---|---|---|
| Understanding context | CTM | Determine where to deliver this message and what to remember (5.1) | Pointing and objects: the message and the last two turns; delivery: the current state of candidate work and the tree around it, recent conversation, interface selections, pending items and displayed entries, running executors; memory: current entries at the delivery location and along that path, and for objects and globally |
| Execution context | Executor | Do the next step correctly | Execution contract + small initial content; the executor asks for or reads what is missing; contains only what is currently effective; does not contain persona or understanding of the user |
| Query reply | User | Understand, check, decide | Comprehensive and traceable; history marked as history |
| Correction input | CTM | Correct its own organization | User changes to the tree, constraints, decisions, and documents |

Execution context and query replies have different readers and purposes, and are constructed and evaluated separately.

## 3. Memory

Long-term memory is in the tree and documents. Each message is written in as it arrives, so nothing is lost when it slides out of the conversation window, and there is no need to compress the conversation.

### 3.1 Nodes and Edges

| Class | Nodes | Purpose |
|---|---|---|
| Work | root, Goal, Task／subTask | Single-parent tree: root → Goal → Task → subTask |
| Constraints and decisions | Task constraints (on tree nodes), Decision, Rejected | Short entries from the user or adopted by the user; authority resides here, not in documents |
| Object constraints | Constraint comments in object files, or entries in `ctm.md` in the containing directory or its parent directories (`ctm.md` stays local and does not enter the repository) | Rules of the objects themselves; CTM only indexes them |
| Conversation | Turn (a message from the user or CTM), Segment (a segment of a user message), Display (something CTM has displayed, with numbered entries) | The recent window is used for understanding; message segments are attached to their respective nodes and retained long-term |
| Query | Query (question, answer, source, observed state) | Does not enter the tree; linked to related nodes |
| Execution | Run (one executor: execution contract, initial context, round trips through the control layer, outputs and traces) | Evidence; an executed task corresponds to one session (usually always resumable), and queries use a fork of it |
| Knowledge and objects | Document, objects (files, modules or components, interfaces, services), FileVersion, Resource | Knowledge is written in documents and evolves with versions; versions are linked to the Run and task that produced them |

Main edges: root→child→Goal→child→Task→child→Task; Task→dep(serial, convergence, conditional, either-or)→Task;
Segment／Query→about→node; Display→about→node／decision; Run→serves→Task; Run→produced→FileVersion;
Task→involves→object; object→contains→file; Decision→detailedIn→Document; Task→uses→Decision／Document／research／results from elsewhere, as well as sibling constraints that CTM judges also apply to it (cross-task references);
Decision→supersedes→old decision; FileVersion→prev→FileVersion. All nodes and edges carry timestamps (Section 4) and record their sources: user, CTM, executor, planner, maintenance, interface modification.

### 3.2 Resolution

Nodes are represented in layers: L0 handle, L1 card, L2 details, and L3 original text. One layer is selected for each node at delivery; L1 is derived from L2. Execution context has a length budget. When it is exceeded, first lower the resolution of the parts farthest from the current work; do not lower the resolution of the current task, constraints and decisions, or the user's exact words.

### 3.3 Root Node (Global Layer)

Content that does not belong to any Goal and remains valid long-term is placed on the root. The user can view and modify it in the interface, and each modification is versioned.

| Content | Examples | Who uses it |
|---|---|---|
| Assistant settings (persona) | Role and responsibilities; principles (state uncertainty truthfully, do not exceed authority, acknowledge errors first); communication style; degree of initiative; risk orientation | CTM only |
| Understanding of the user | Role and expertise; working style (parallel progress, brief references, preference for minimal changes, reviewing diffs personally); common intent patterns; things often corrected in the past; delegation habits | CTM only: used to understand ambiguous messages, decide how much detail to include in a relay, judge what to ask, and accurately define the scope of a contract |
| Overall goals and priorities | The most important things during this period, their order, and what cannot be sacrificed | CTM uses these to understand, order pending work, make trade-offs in conflicts, and offer suggestions; they do not grant authorization |
| User preferences and global constraints | “Do not use PowerShell” “Write documents in Chinese” | These are task constraints on the root, inherited downward and followed by both CTM and executors |
| Common environments | Machines, common working directories, accounts and their uses | Source of work locations for execution; volatile items carry observation times |

- Conversations that do not belong to any Goal (requirements for CTM, preferences, discussions of overall goals, questions spanning goals) are attached to the root, forming the root's exchange record.
- **Separate sources**: User settings and CTM inferences are recorded separately; inferred preferences and changes in goals first appear as suggestions and take effect after the user approves them.
- **Understanding of the user** is inferred: each entry records its basis, confidence, and time; it is visible and editable by the user, and the user's new statements take precedence when they conflict with it; it is limited to work-related aspects;
  initial content comes from user habits summarized from past collaboration ([User behavior patterns](user-behavior-patterns.md)). It cannot override the user's explicit statements or make decisions on the user's behalf.
- **Always present, limited in length**: Persona and understanding of the user are limited in length and always placed in CTM's understanding context, rather than retrieved; when they exceed the limit, CTM proposes merging entries or deleting low-confidence ones.
- **Stable**: A change to persona is an explicit event; when an overall goal has had no corresponding activity for a long time or work has clearly shifted, CTM asks for confirmation rather than rewriting it on its own.
- Overall goals explain “why and what takes priority”; a Goal is a child node of the root and a specific purpose. It can serve multiple overall goals (represented by links).

### 3.4 Task Tree

- **Criterion**: A Goal／Task must have a clear output (a deliverable such as a document, code, report, or configuration), or change the state of some resource (a file, service, environment, or data).
  A request made only to find something out is a query (5.3); no node is created.
- **Research work**: Research that gathers information externally (online sources, other projects, papers and documents) aims to find things out. Its output is a long-form conclusion, written as a knowledge document (not a deliverable). When the user has not said which work it serves,
  or its content is unrelated to existing work, it is not attached to the task tree but recorded in the query list like a query; however, it can continue across several turns and have its own requirements, execution session, and conclusion document. When a task later uses it, the reference is recorded,
  and that task's context includes its conclusions; if the user later says which work it serves, or maintenance recognizes that it is indeed part of some work, it is then attached to the tree.
  A question about the project itself (code, session history, things done, current state) is a query (5.3): first find the related task in the tree and answer using a fork of its session. It is not a research entry.
  Research that continues an earlier step follows the preceding item: if that item is a research entry, it continues that entry; if it is a task, it belongs to that work. CTM judges all of these by context.
- **A Goal is a long-term goal**: Only Goals are directly under the root, and every Task is attached under the Goal it serves. A purpose stated by the user (“I want to make a ...” “Now we need to do ...”) is created as a Goal when stated; when the user has not stated one, CTM summarizes the long-term goal served by this request: for example, “transcribe these three files” is a Task, and its Goal is “transcribe files”; future transcription requests continue to be attached under this Goal. When summarizing, ask: Can future work with the same purpose be attached here? A Goal is not the request itself, nor is it a project or working directory (a working directory is where work takes place; one Goal can span several working directories). A Goal summarized by CTM is marked “CTM summary”; the user can rename, merge, move, or confirm it on the tree.
- **Sources of Tasks**: The user, CTM's synthesis, the planner (a planning agent invoked by CTM), the executor (a branch opened during execution), or the user creating one in the interface.
  Nodes opened by the planner or executor are initially proposals and become plans only after user approval or when they fall within the authorized scope. A large deliverable can be organized by the planner through documents following “requirements → design → implementation tasks”; this is only one planning template, not a fixed process for all work.
  When the user asks for planning first, or explicitly specifies a large deliverable to be completed in steps, delivery marks the new work “planning required,” and CTM invokes the planner; otherwise, the executor arranges the steps during execution. A one-off request is also a Task attached under the Goal it serves.
- **Placement**: The tree reflects the composition of the work itself. Tasks under a Goal are specific work toward that goal; the relationship between a Task and its subtasks is containment: subtasks are parts of the parent task, and the parent task is complete only when all subtasks are complete; siblings are parallel parts or sequential steps of the same work (sequence is linked by serial relationships). Whether to split into subtasks, and whether to split by steps (confirm which three files／transcribe／summarize) or by parts (transcribe A／B／C), depends on the situation.
  These are only general directions, not rules to apply mechanically: the same type of action (pushing, verification, writing documentation, troubleshooting) may be a sibling, a subtask, or simply a continuation of the same work in different contexts. CTM judges placement in context, considering:
  - **Whether to create a node**: Create a separate node only when there is an output that can be accepted independently, or requirements belonging only to it (local constraints); a continuation of the same work (for example, “push and create a PR” after a commit) may simply be a progress entry for that work; wrap-up after execution (cleaning temporary artifacts, shutting down services, switching or deleting branches) is a continuation of that work and does not get a node; intermediate steps within the same execution are not split off.
    When a problem discovered during execution belongs to the work itself and indicates it was not done well or was not finished, the user's “continue resolving it” is a continuation of that work and is recorded in progress, without creating a new node; it becomes a subtask only when the problem has requirements belonging only to it, requires separate acceptance,
    or is to be pursued separately later or on another track. Fixing a problem found by investigation, query, or review and delivering a new output is new work, attached according to its composition.
    When a subtask is a direct continuation of the parent task's current execution, do it in the parent task's session (reuse its session).
  - **Same work, subtask, or sibling**: Look at how the work is composed in context, rather than the type of action. For example, “analyze the integration approach” and “implement according to the approach” are two parallel parts of the same work; the latter is not attached under the former. The working directory is an important reference: work on the same task is usually in the same place, and work in different working directories is mostly different tasks (one task may also span two repositories); it is only a reference, not a boundary, and the party making the judgment must consider the content.
  - **Group under a Goal and the same parent**: The user often raises the same work step by step, days or even weeks apart (the user's exact words: every time a new task is created, consider whether the last few tasks are actually subtasks of one task; the tree is dynamic and needs regular correction). So when creating a task, CTM considers which Goal it serves and whether it and any of the recent tasks are parts of the same task; afterward, it must also regularly review the existing structure, not just newly written records: group work not yet under a Goal under the Goal it serves, merge Goals with the same objective, and group several parts of the same task at the same level under one parent task. A parent task is a specific task with an identifiable output; grouping by period, phase, or domain spreads constraints and the scene to work that merely shares a phase. There are often several reasonable ways to organize the same batch of work, with no unique answer, and the tree can be adjusted at any time; choose the one that better serves the tree's uses (inheritance of constraints, the scene seen by executors, and the user finding their own work on the tree).
  - **Check the consequences for constraints**: One purpose of branch nodes is the isolation and inheritance of constraints, but structure is not determined by constraints. Before deciding placement, check: would this placement pass existing constraints into unrelated work, or prevent required constraints from reaching it? If so, the placement is most likely wrong; reconsider it.
  Candidates for the parent node come from work found at delivery and existing Goals (5.1); new work is attached at least under the Goal it serves. If it is not clear which work under the Goal it belongs to, attach it under the Goal and organize it later. A new requirement raised by the user midway through a piece of work is often prompted by it—for its sake, because of its results, or as a thought arising from it—even if what is requested is more general; the user may also simply have remembered something else. So when judging placement, analyze why the requirement was raised at this time and how it relates to the current work: the current task is not the default parent of the new work, but the reason it arose is an important basis for judgment; when it arose from the current work but its output is more general, either placing it under that work or making it a separate item may be reasonable. CTM records which work was being done when each piece of work was raised, for use in later structure organization. There is no depth limit. The tree is dynamic and adjusts as new work and requirements arise; each adjustment lists changes to the constraints inherited by each node and informs affected executors.
- **Relationships**: Serial, parallel, convergence, conditional, either-or; they can be mixed and revised; order on the tree does not indicate execution order.
- **Status** is driven by events and records time, reason, and source: proposed, pending execution, executable, in progress, blocked, paused, complete (based only on the executor's report), verified (complete with verification traces), abandoned, replaced, reopened; both kinds of completion are task statuses judged by CTM in context, differing only in their basis, and user approval is also one basis.
  An executor's report that “this request is done” is recorded only in the execution record and does not mean the task is complete: tasks often have further user follow-up questions and modifications. CTM judges whether a task is complete by context (user approval, whether the purpose has been achieved, and whether work continued afterward).
  Completion of a prerequisite makes its successor executable; when a prerequisite's result is overturned, the successor awaits rechecking. Whether a parent task is complete is judged when needed (the user asks for progress, a successor depends on it, or results need to be folded upward): check whether all subtasks are complete and compare them against the parent task's purpose—subtasks are added step by step and may not yet cover the whole purpose.
- **A task's content** consists of only three things: goal and scope (including working directory and runtime environment: addresses, clusters, ports, key locations, and relevant directories needed to continue the work; and the user's guidance on approach and plan, such as “pay attention to what the previous steps resolved and how they resolved it” and “test broadly.” Like constraints, it is inherited downward and ends with the task, but is labeled guidance, not a hard restriction, when handed to the executor), constraints and decisions, and progress (one brief summary per execution: what was done (including versions produced, branches, PR numbers, etc.), which documents and files were updated, verification status (traces or self-report), pending items, and approaches that were tried but failed and why—a new executor cannot see the old session and will repeat failures if they are not recorded; each entry carries its write time and reflects the state at that time), plus status, pending items, in-flight executions, and links to related documents. Knowledge is not stored in tasks: approaches such as how to run, test, or query are written into documents by executors according to the output conventions; environments shared by multiple projects are written into common environments on the root. **CTM does not extract facts item by item from executor responses**: the original response is saved as execution evidence, and CTM writes only that one brief summary; if the response still contains lengthy content, it is saved as a document in full; other details remain in documents and execution evidence, to be retrieved when needed or read by the executor; which content becomes a decision, a rejected approach, or a pending item is determined by the user's reaction to the relay (5.2 item 6). Facts about environments, locations, and so on stated by the user in messages are written into the task's scope, with time and replacement relationships recorded at write time, just like constraints and decisions; an executor's report cannot replace constraints and decisions stated by the user.
- **Fold upward on completion**: Results and conclusions (including “not feasible”) are written into the parent task and passed to successors.
- **Results fold upward, task constraints pass downward**, both along the same tree.

### 3.5 Constraints

| | Task constraint | Object constraint |
|---|---|---|
| What it concerns | How this work is done: scope, method, process, pace (“only change newly added code this time,” “do not test yet”) | Rules the object itself must satisfy: design conventions, interface contracts, invariants (“transport cannot expose a sampling rate parameter”) |
| Storage | Tree nodes: root, Goal, or Task | Constraint comments in the object’s file; for objects that cannot have comments (JSON configurations, generated files, binaries) and multi-file modules, in the `ctm.md` of the nearest directory containing them; for the entire project, in the `ctm.md` at the root (`ctm.md` stays local and does not enter the repository); for objects outside the working directory, in the object description in the CTM document area |
| Who it applies to | The node and all its descendants | Any work involving the object, regardless of which Goal it belongs to |
| Lifetime | Until the node ends; if valid for only one message, until the next message | Until modified or revoked by a user decision; no comment means no constraint |
| How it reaches the executor | Task constraints on the path from the root to the current task enter the execution contract | The execution contract requires the executor, before modifying a file, to check its constraint comments and all `ctm.md` files on the path from the project root to the directory containing the file |

**What is a constraint**: A constraint is a restriction on work or a rule that must be followed (scope, methods and tools, process and pace, format, such as “use az cli,” “the list is very long, fetch it in batches,” “please continue making progress for multiple turns”). The following are not constraints:
Guidance on approaches and plans (“pay attention to what each previous step solved,” “test broadly”) belongs to the task’s goal and scope and is marked as guidance; requests for wrap-up actions or starting the next step (“clean up temporary artifacts, keeping only key records”) are work content for this occasion;
corrections to previous approaches (“first analyze only user messages; for agent replies, use an LLM to summarize them first”) are decisions that replace the corrected approaches.

**Task constraints**: Deeper, more specific, and newer constraints take precedence; a constraint on a child node that contradicts one on an ancestor is valid only if the user explicitly states it, and is recorded and marked as an exception on that subtree.
CTM judges which node to place it on based on the user’s words (“from now on,” “all,” and “this entire feature” are signals to place it higher); when uncertain, place it lower rather than higher—
placing it too high brings the constraint into unrelated work and causes excessive restrictions, while placing it too low at worst leaves a constraint missing elsewhere, which can be corrected when the user mentions it or by lifting it in the tree.
**Lifting and rolling back constraints**: When the same requirement appears on several branches, CTM judges where it should go: if it applies to all work under a common ancestor, lift it to that ancestor; if it concerns an object, propose changing it to an object constraint; if it is a personal habit that applies to all work, propose making it a preference on the root.
Moves to the root and changes to object constraints are proposals and take effect only after the user approves them. An incorrect lift can be rolled back: when the user says it does not apply somewhere, record it as an exception on that subtree, or move it back down.
**When new work is added at a level**: While working on one item, the user often states a requirement for the larger whole (a rule for the same artifact, or a practice to follow every time for this kind of work). It is attached to that item, and siblings added later do not receive it, so the user has to say it again. Therefore, when new work is created, if siblings at the same level have constraints, CTM judges which of them also apply to the new work and references them for it (when handing it to the executor, noting that this is CTM’s judgment and identifying the work for which each was originally a requirement). The siblings and the rest of the work at this level are left unchanged; the user can remove the references in the tree. Lifting these constraints to the common ancestor, or grouping several items under a new ancestor, would bring them to work that merely shares the same level. This caused too much unintended impact in evaluations, so it is not done (implementation plan section 7, “Consequences of constraint delivery”).

**Object constraints**: Constraints stay with the object. Executors read them when they open the object, and people can also see them in the file. Changes leave a history in version control, and the constraints remain valid outside CTM.
- **Nested `ctm.md` files**: Any directory can have a `ctm.md`, which applies to files in that directory and its subdirectories; every `ctm.md` on the path from the project root to the file’s directory applies. When entries conflict, the one closest to the file takes precedence (consistent with the AGENTS.md convention, which executors know). An entry in a closer `ctm.md` that contradicts an ancestor can likewise come only from a user decision, and must be marked as an exception to the ancestor. When a module spans several directories or involves only some files in a directory, an entry can specify the applicable path patterns.
- When the user states an object constraint, CTM records it. While the work it belongs to is underway, it is handed to that work’s executor through the conversation—the executor has the user’s original words, and subsequent refinements and replacements are also relayed through the conversation;
  before an executor that needs to read it from a file starts—an executor for another work item, or a new session entering this directory—or when the work it belongs to ends, CTM itself writes it into the `ctm.md` of the nearest directory containing the object
  (when the object is not a path in the working directory, write it at the project root and specify the object in the entry; when the statement does not belong to any work, write it immediately); use a uniform marker and note the source and time.
  It is not written immediately because files and conversation are two separate routes: the executor reads the file upon starting work, while CTM’s memory write happens after dispatch, so an immediately following refinement within the same work always arrives one step ahead of the file
  (2026-11-24 real pilot trial: “adjust in url order this time” was mistakenly recorded as an object rule and written immediately; the next sentence limited it to adjusting only the newly added parts, but the executor still read the old entry, judged it a conflict, and stopped to ask the user). `ctm.md` is CTM’s record: it stays on the local machine only (when CTM writes it, CTM adds it to the repository’s local ignore list `.git/info/exclude`); executors only read it, and do not modify or commit it.
  The reason (2026-11-23 real pilot trial): a rule written into `ctm.md` entered a PR in a public repository with a commit. The user had to correct it and set the global rule “do not commit ctm.md.”
- CTM proposes writing constraints into source comments (at the same time as writing them into `ctm.md`): constraint comments are part of the code, enter the repository with it, and can be read by colleagues and other agents; but it is the user’s code, and judgments about “an object rule or a change for this occasion”
  often differ (independent judges also often disagree). So CTM raises it as a numbered pending item (should this rule be written into a comment on X?). After the user answers,
  the proposal and the user’s original words are handed to the executor for that work: write it if the user agrees, and do not write it if the user disagrees.
- After an object constraint is replaced (including when the user says it no longer applies), CTM immediately deletes its entry in `ctm.md` (deleting the file if only CTM’s explanatory text remains), and withdraws any unanswered proposal to add a comment; if the user has responded to a proposal to write it into a comment, CTM then proposes updating the comment. Executors read only current rules; executors that have read the old entry learn that it has been replaced in the next relay.
- The cost of an incorrect judgment is therefore not high: the most common mistake is to record details of the current change as a rule, while the user’s next few sentences often refine that same change—they replace the mistakenly recorded rule before it is written to a file;
  any extra entry that remains is only in the local `ctm.md`. If it later conflicts with a requirement, it causes the executor to stop and ask once, and is replaced as soon as the user answers; comments entering the code require the user’s consent.
  This is more appropriate than making the judgment stricter—two stricter versions of the memory instructions (V10, V11) both missed genuine long-term rules as well, and missed rules are quietly violated.
  Object constraints are carried by the files where objects reside, and concern specific objects. For a specific object that does not yet have a file (a website being planned), the constraint stays on the work in which it was stated and is written beside the object once there is a working directory;
  a convention concerning no specific object but applying to all the user’s code or all work (“add a prefix to all function names”) is not an object constraint. Record it as a task constraint or global constraint according to the scope of the user’s words—
  if recorded as an object constraint, it has nowhere to reside and cannot reach any executor (all such rules were lost in the MemoryCode long-conversation evaluation).
- Constraint comments can be modified only through a user decision, and `ctm.md` is rewritten only by CTM according to memory; if an executor deletes or modifies them, the execution control layer treats it as overstepping and escalates after discovering it in the diff.
- When an object is refactored, split, or deleted, the executor migrates the constraint comments with it, or asks the user to confirm whether they no longer apply; when an object mentioned in `ctm.md` changes, the executor explains this in its reply, and CTM updates the entry.
- When first encountering a project, draft `ctm.md` entries based on the project’s existing instruction files: if this is to be done, CTM reads those files itself and presents the entries to the user as proposals, without passing them along to executors (not yet done).
- CTM indexes memory by object (for queries, conflict checks, interface display, and `ctm.md`). Objects (“the transport layer,” “the billing part”) are recognized through semantic understanding, not literal matching.

**Distinguishing the two**: Ask “Should this rule continue to apply in any future work involving this object, without being stated again?” If yes, it is an object constraint (for example, a long-term convention for a memory file, or the design of a test itself); if it concerns only the output for this occasion or the approach to this work, it is a task constraint (for example, the format of this change, the description of this one PR, or the scope of this research). Judgments about investigation directions and causes are decisions, not constraints. When uncertain, treat it as a task constraint first; the same requirement appearing repeatedly in different tasks
is a signal for CTM to propose changing it to an object constraint. The user can change the type or location of a constraint in the interface.
**Conflicts between the two**: When the user’s words themselves modify a rule (“change to…,” “no longer…”), this is a user decision. Replace the old rule during the memory write without asking. When a requirement in a task contradicts an object constraint and the user has not indicated an intention to change the rule,
the executor discovers it when modifying the file—it reads the constraint comments and `ctm.md`, and also knows what actually needs to change this time. This is more accurate than CTM guessing at the message stage, and avoids an extra check for every message—the executor stops and reports it through the execution control layer as something requiring a user decision,
and CTM asks the user whether this is an exception for the task or a change to the object constraint.

### 3.6 Decisions and Documents

- **Decisions** are short entries, stated by the user or adopted by the user, in three categories: established (approved plans, selected approaches, judgments about causes or directions, acceptance of results), rejected (listed separately as “do not use again” when given to an executor),
  questioned (the user questioned an agent’s conclusion without rejecting it: marked “questioned by the user, verify before use” when given to an executor, and replaced by a new decision when subsequently confirmed or rejected). New decisions replace old decisions; the old ones are retained as history.
  Authority rests with the decision entries. Documents only provide further explanation and cite decision IDs. When a decision referenced by other tasks changes, those referencing it are marked for rechecking.
- **Knowledge is in documents**: analyses, designs, investigation conclusions, and explanations of mechanisms and configurations are all written as documents. Subsequent execution continually updates them, creating a version history; details are not split into numerous knowledge entries.
  Each version links to the execution, task, and decisions at the time that produced it.
- **Types**: knowledge documents (continuously evolving), deliverables (documents, emails, and review comments requested by the user, from draft to final), reports (conclusions of an investigation or test, dated, append-only and not rewritten), and plans.
- **Agent behavior guidance**: Goal and Task are concerned with user-facing goals and outputs, while knowledge documents are concerned with concepts; behavior guidance is a third category: what an agent should do when encountering a type of concept or performing a type of operation (for example, how to start a subprocess or what tool to use for search), similar to a skill.
  General practices of this kind stated by the user are stored as behavior guidance documents, with a description of “when to use” them. When work is given to an executor, it is given an index and reads the documents itself when needed; they do not go into the task tree. A practice that applies only to a particular work remains guidance or a constraint for that work:
  the distinction is whether the user is saying how this work should be done, or how this type of operation should be done in any work; the same sentence may be either one in different situations, and CTM judges from the situation.
  There will also be inventories of tools, skills, and MCPs later; for now there are only behavior guidance documents.
- **Writing**: distinguish verified from unverified statements, and note the basis for verified ones (command output, file versions, tests).
- **Location**: knowledge documents are in the CTM document area by default; deliverables are in the task’s working directory, as project documents.
- **Which document to choose**: each document has a one-sentence description of its “purpose and when to use it”; CTM provides an index of relevant documents in the initial context, and the executor selects a document to update or proposes creating a new one, reporting this in its response; the same document is assigned to only one executor for modification at a time.
- **Incremental updates**: knowledge documents are modified by section, not rewritten in full, to avoid information loss from repeated rewriting.
- **Outdated**: after a decision is replaced or a file changes, sections that reference it are marked as outdated and updated the next time the document is used, or when the user requests it.
- **The working directory is the boundary at the concept level**: CTM recognizes only the working directory and the observed versions of files in it; version control details such as branches and commits belong to the execution level.
  Only one executor that will modify a given working directory is assigned to it at a time; when parallel modification is needed, the execution level provides isolated working directories, which are different working directories as far as CTM is concerned.

### 3.7 Document Browsing

The task tree handles structure and correction; document browsing supports in-depth reading. Selecting a node in the tree opens its page; sources in query responses also link here.

| Page | Content | Source and editing |
|---|---|---|
| Task metadata | Purpose and scope, working directory, status and history, constraints and decisions, progress, relationships, execution records, related documents | Generated from memory; changes here are changes to the tree |
| Task exchange record | User messages related to this task, CTM’s relays and questions, summaries and final responses from each execution | Generated from saved records, not maintained separately, not editable; consult this to review the course of the work; executors can also read it when needed |
| Knowledge documents | Documents in the CTM document area | Versioned; can be edited directly, producing a version sourced from the user |
| Project documents | Documents in the task’s working directory | The current contents of the working directory; editing is equivalent to modifying files in the working directory |

- All pages are generated from the same memory; the interface is only a view. Version history and differences can be viewed, and outdated sections and verified and unverified statements are marked on the pages.
- Bidirectional links: document ↔ tasks that use or produce it, decisions it references.
- When a user-edited document conflicts with a decision in the tree, CTM treats it as a new statement by the user and proposes updating that decision.
- The page the user is viewing and the selected passage are location signals.

## 4. Time

Time runs through the entire graph and answers four kinds of questions: which instance is meant, what stage things are at now, what was known at the time and what was corrected later, and whether a piece of information is still usable now.

- **Records**: occurrence time, time learned, validity interval (constraints, decisions), observation time and window (volatile state), deadlines and event conditions, planned and actual, in-flight duration, most recent activity time.
  Calendar time, elapsed time, position within media, and cumulative usage are different axes.
- **References**: “just now, yesterday, last time, the first version, before the fix” are resolved to specific tasks, attempts, versions, or periods; a retry and a new round are different instances.
- **Stages and timing**: gate conditions are triggered by events; the passage of time does not automatically complete, cancel, or unpause anything; in-flight operations remain pending until they complete.
- **Correction and replacement**: when constraints and decisions stated by the user (including rejected approaches) and information about the environment are written, they are compared with current entries in the same scope, and which entries they replace is recorded (executor reports do not replace them; progress is the state at a given time, and the latest takes precedence); old entries retain their original time and “replaced by whom” and are no longer provided as current entries. Rejected approaches are saved together with the approaches that replace them, and listed separately as “do not use again” when given to executors on the same line of work.
  The user can also simply **withdraw** something already recorded—say that it is wrong or no longer needed, without providing a new approach: record the user’s statement (what is no longer wanted), and invalidate the withdrawn entry through the replacement step. The direction must not be reversed when recording it: if the user wants to remove a rule and it is recorded as “rejected: remove this rule,” the executor reads the opposite requirement (real pilot trial on 2026-11-24). A separate “withdrawal” category was tried (memory V12): the extraction step could not see already recorded entries and could not distinguish withdrawing something already recorded from a new negative requirement. It was never used and instead caused decisions to be missed, so it was not adopted.
- **Applicability**: constraints and decisions are governed only by their validity intervals and replacements; they do not decay over time. Volatile state carries an observation time and a method for rereading it, and is not treated as current fact.
- **Time weighting during retrieval**: apply continuous weighting to all candidates, with a floor; when a message contains a time reference, center the weighting on the referenced time instead.

## 5. Operation

### 5.1 User Messages

For each message, CTM only needs to decide two things: **where and how to deliver** the user’s words (which executor’s session, as content for this work or as a side question, where new work attaches to the tree),
and **what to record** (constraints, decisions, facts, and guidance that will be needed later and whose original wording will fall out of the window). Other judgments belong to other roles: the executor reads the original words and the scene and understands for itself what to do,
the control layer checks irreversible actions against the contract, object constraints are read by the executor when modifying files, and structural organization is completed through maintenance.

1. **Pointing and objects** (one lightweight call, no assignment decision): determine the ways in which the message points to the work it addresses (multiple selections allowed), and extract the objects and time references it mentions; pasted material is kept separate from the user’s words.
   The pointing method determines where to look for candidates:

   | Pointing method | Where candidates come from |
   |---|---|
   | Response to a recently shown result, plan, or pending item (approval, rejection, correction, follow-up, verification, answer to a clarification) | Recently shown entries and the work to which pending items belong |
   | Progression, control, or status inquiry without pointing (continue, stop, how is progress) | Current work (the one the user last exchanged messages about); running and waiting executors are only references |
   | Recent reference (this, it, just now) | Work visited in the last 10–20 turns |
   | Naming work, an object, an artifact, or an identifier | Object → object in memory → work that has touched it, regardless of how long ago |
   | Time reference (yesterday, last time, the first version) | Work near the referenced time, cross-checked against object retrieval results |
   | Pasted material | Objects in the material → as above; running work |
   | Reference to a plan or conclusion established elsewhere | Current decisions in memory (these were stated by the user and bring out the work they belong to as objects); document indexes will be considered later |
   | New requirement | Still use its objects to find related work (it may be a continuation, part, or next step of some work), current line of work |
   | External research | Research entries in the query list, related work |
   | Pleasantries | No candidates needed |

   Objects are written as explicit descriptions after resolving references; identifiers are copied exactly, without correcting spelling. Interface selections and explicit references (nodes selected in the tree, pages and passages in document browsing, @-referenced objects) directly determine assignment and need no candidates.
2. **Candidates** (code): set a quota for each path according to the pointing method and take their union, without closing off any path (an incorrect pointing-method judgment only adds a few candidates and will not miss the correct path). The object path:
   compare objects in the message with objects in memory—currently, objects in memory are objects the user mentioned in past messages (the user’s own wording, attached to the work after message delivery) and files modified by each work;
   identifiers are identical or differ only by a spelling error (character-by-character comparison is used only for identifiers), and names are matched by embedding similarity. Quotas are per object: each object found brings out all work that has touched it (a family of work, subject to a cap),
   without selecting one for the LLM here by score or time. Do not use the vector of the entire message: it mixes in wording and material, and often finds work that is merely close in topic.
   Whether identifiers produced by executors (PR numbers, branches, documents) should also be treated as objects will be considered later.
3. **Delivery** (one call; if none of the candidates is suitable, or a duplicate check is needed before creating new top-level work, expand to the full tree and call again): list candidates grouped by object, examine the current state of each work (status, recent results, open issues,
   what the user recently said about it, whether the executor is busy or waiting, work done afterward) and recent conversation, rank the most likely items within the family of work on the same object, and decide where and how to deliver;
   show the next two or three items to the user as alternatives, so an incorrect selection can be changed with one click. Delivery methods: the original work’s session, new work and its position in the tree (the Goal it serves—an existing one, or a newly summarized long-term goal—and where it attaches under the Goal, 3.4), borrowing the parent task’s session, a side question (read-only fork),
   a research entry, control of a particular executor, or asking the user first because the request is unclear and the action is irreversible. Words addressed only to CTM (preferences and rules it should remember, adjustments to its or all executors’ future practices) are not delivered to an executor; they are recorded in step 5, and the response explains what was recorded (1.1). Mark new work that needs planning first (3.4). When a message must be delivered to several places, deliver it separately. State in the conversation where it was delivered, so the user can see and correct it at a glance.
4. **Dispatch** (code): assemble the execution context according to the delivery location (5.2), or forward the user’s original words and newly effective entries to the original session; save long pasted material as a document, and give the executor the original text or its reading location.
5. **Memory** (after dispatch): at this point, which work the message was delivered to is known. One call extracts constraints, decisions (including rejected and questioned ones), facts, guidance, and behavior guidance, and determines their respective locations (3.5, 3.6);
   when there are new entries and there are current entries on this path, for the object, or in the global scope, make another focused comparison: compare each new entry only with the few current entries closest to it, and determine which one it replaces, or whether it is merely a duplicate (Section 4). During comparison, both new and old entries are marked as rejected or questioned where applicable—a rejected approach is literally contradictory to the requirement it rejects. Without the marking, when the user reiterates a rule misunderstood by an executor, the recorded “rejected: the executor’s misunderstanding” will replace the rule the user just reiterated.
   Replacement is kept separate from extraction because when one call must both extract and compare against all current entries, it pairs them off casually, resulting in many incorrect replacements—an incorrect judgment can cause a still-valid requirement to be marked “do not use again”,
   which costs more than a missed replacement (when one is missed, both entries are given to the executor, and the execution context handles them with “newer takes precedence”).
6. **Response**: explain the arrangements in the conversation; the task tree displays them at the same time.

### 5.2 Execution

1. **Form**: Use a single call for analytical questions; use a subagent or session when reading or writing files or running commands is needed.
   The **working directory** is determined by CTM for each task, and the executor runs there: the directory stated in the message ＞ the directory of the work it belongs to (the parent or preceding step) ＞ determine the project it belongs to from the user's words and the directories where they have worked; work that does not belong to any project (writing documents, looking up information, general affairs) has a separate temporary directory under CTM's own directory. The user does not need to specify a working directory in advance.
2. **Lifecycle**: If CTM judges that the message continues the original task, it reuses the original task's session; if it judges that it is a new task, it creates a new session. A session normally has no end state and can be resumed no matter how much time has passed;
   it ends only when the context is near its limit and the user is unwilling to compress it. If the original task is already complete and the scene has been changed by subsequent tasks, when the user says “continue” again, it is most likely a new task: create a new session and start again from the scene,
   leaving the executor to judge the current situation by comparing the original task with the results of subsequent tasks in the context (CTM does not record its relationship to the original task). The consequences of the two kinds of misjudgment differ: if it is mistakenly judged to be a continuation, the executor works with an outdated scene;
   if it is mistakenly judged to be a new task, details in the original session are lost, but the new session has the context of the path and siblings—CTM weighs the trade-off in light of the situation.
   When reusing a session, CTM forwards: the user's original words, constraints, guidance and decisions on the path that have not yet been conveyed, approaches that have been replaced or rejected, notifications that the files involved have been modified elsewhere, and conclusions from queries answered in a fork.
   Executor states: working, waiting (for the user or CTM), idle.
3. **Initial context (assembled by CTM, kept small)**:
   - Execution contract: **the goal is the user's original words** (when one message involves multiple pieces of work, take the passage belonging to this task and quote it verbatim); authorization is based on the original words, and where the original words are silent, the task's previous authorization and still-valid restrictions carry over. Irreversible actions are authorized only when the user explicitly requests them. CTM does not rewrite the user's words, add requirements on the user's behalf, or tighten or loosen them on its own—in evaluations, contracts rewritten by CTM significantly reduced the executor's accuracy,
     with the main errors being invented obligations and excessive tightening (evaluation progress stage 4). Fixed terms: before modifying files, review and follow the constraint comments in the files and `ctm.md` at every level on the path; do not delete or modify them; ask CTM first if information is missing;
     the response briefly states what was done, which files were changed, the verification status, unresolved issues, and matters requiring the user's decision; long content goes into a document. Contracts generated by the planner for a plan step also have completion criteria and a resource budget;
   - Current state of the task: purpose, working directory and runtime environment, stage, progress and verification status, pending items, results handed over by prerequisite tasks;
   - Task constraints and decisions on the path (including preferences and global constraints at the root);
   - Recent progress: summaries of the most recent executions (including failed attempts and their reasons); **the original text of the last few turns of exchange for this task and its parent**—the user's words and the endings of executor responses;
   - **Recently executed sibling tasks (about 7) and recently executed siblings of the parent task (about 3)**: their results, decisions, and original text of recent exchanges—they make up the scene in which this task sits, and the numbers roughly correspond to the range of surrounding work a person can remember; siblings' constraints and guidance are not included (constraints are attached to siblings precisely to isolate them); tasks attached directly under the root have no such siblings;
   - **The original text of the last few turns of the conversation (about 6 turns)**, regardless of which work they belong to, with a note that they may belong to other work, are only for understanding what this message refers to, and that their requirements belong only to their respective work—the user alternates between multiple pieces of work in one conversation, and a new request often directly follows something just completed in another piece of work (such as “commit the code”); scopes organized by the tree cannot reach that far (evaluation block D: the proportion with all required information in the context rose from 0.22 to 0.44, missing information fell from 0.38 to 0.15, and no executor was observed following requirements from other work);
   - An index of Agent behavior guidance documents;
   - Paths and purposes of relevant documents (the executor reads them as needed); content the user pointed to this time; a list of items that can be asked about (titles of relevant decisions, constraints, and documents).
   The initial context includes only what is clearly needed for this work, organized in a fixed order (fixed terms and long-unchanged parts first, parts that change this time last), to facilitate model cache reuse.
4. **Execution control layer**:
   - Distinguish the types of executor stops: if the next step is within the contract and it is only asking whether to continue, have it continue directly; if it asks for approval of a direction or plan before acting, or requests an action with side effects or outside the scope, allow it under the contract or escalate it; if it proposes optional steps or several options not required by the contract, hand it to CTM: CTM answers on the user's behalf when the user's original words, current constraints and decisions, and understanding of the user at the root already clearly provide the answer; otherwise, ask the user; if it needs information, hand it to CTM;
   - Check formal completion: whether all required deliverables are present, whether the response meets the agreement, and whether long content has been written into documents; request completion when these are not satisfied;
   - Handle errors, retries, timeouts, and budgets; stop and escalate when continued attempts produce no new progress or the same error recurs, and let CTM decide whether to replan, narrow the scope, or ask the user;
   - When the executor encounters an irreversible action or one beyond the boundaries, allow it under the contract; escalate if the contract does not cover it; escalate if constraint comments are found to have been deleted or modified;
   - Long-running executions report brief progress at milestones, and CTM immediately writes it into task progress to avoid losing completed work if execution is interrupted or the context reaches its limit;
   - Pass only these to CTM: inquiries that require memory to answer, matters requiring the user's decision, actions outside the authorization, milestone progress, completion, and failure. Records of exchanges remain in the control layer as evidence.
   - The control layer judges only formal completion; CTM and the user judge whether the work was done correctly. It does not hold memory.
5. **Between CTM and the executor (through the control layer)**:

| Direction | Content | Handling |
|---|---|---|
| Executor → CTM | Inquiry: a decision, constraint, file location, result of another task, or past approach | CTM answers from memory (giving only what is currently valid); if unavailable, says “I don't know” or asks the user |
| Executor → CTM | Request: user approval, a choice, or additional information is needed | Relay to the user as a pending item and pass the response back; the executor first does the unaffected parts and lists the assumptions made in the response |
| Executor → CTM | Completion, failure, blocked | Write back and relay according to the notification rules |
| CTM → Executor | New messages from the user about this task, constraints and decisions newly established elsewhere | Send to the active session |
| CTM → Executor | Control: pause, stop, resume, change scope | The control layer carries out the action and reports the effects already produced |

6. **Result handling**: Save the response and traces as evidence for the Run; CTM briefly summarizes the response and writes it into task progress, and links new versions of documents and files to this execution and task;
   long content in the response is saved as a document.
   - User in the loop: CTM decides what to relay; the user's response to the relay determines which content becomes decisions, rejected proposals, or pending items.
   - Plan steps advanced autonomously: the control layer first judges completion against the completion criteria, and CTM passes the results to successor and parent tasks.
   - When the executor's account conflicts with the traces, the traces take precedence; when relaying, state which parts are supported by traces.

### 5.3 Query

A request made only to find something out, without requiring an output or changing resource state, is a query: explanations, lookups, causes, current state, progress, “what did we decide before.”
Queries have no separate entry point: the user speaks only in the conversation, and CTM determines segment by segment whether each is a query or a task. Replies to segments classified as queries are shown in the query panel.

0. **Classification and correction**: When unsure whether something is a query or a task, treat it as a query—a query is read-only and changes nothing, so if it was classified incorrectly, the user can turn it into a task by saying “I want you to change it”; treating a query as a task instead could result in changes the user did not ask for. CTM states “answering as a query” in the conversation, and the user can change the classification at any time.

1. **No node**: Query records are linked to the relevant work; those unrelated to any work are linked to the root.
2. **Answering**: When the question concerns recorded matters (what was done, decided, or said, progress and results) and memory can answer it completely, CTM answers directly; when it concerns the current state of files, logs, runtime state, or external data, or calls for explanation, analysis, or reasoning, CTM dispatches read-only execution and gives it relevant records from memory as leads—the records may be outdated or merely claims not verified by the executor, and piecing together previous statements alone cannot adequately answer explanatory questions either (evaluation block G: previously, answers found in memory were given directly, and about 70% of answers based on memory were incomplete or wrong). The contract for read-only execution prohibits all modifications: when the question concerns the project itself (code, history, things done), first find the relevant tasks in the tree;
   if a relevant task has a session, fork that session to answer (it already knows about these things, and the query process does not enter its execution context); otherwise, create a new read-only executor. Longer replies are likewise saved as documents.
   A query is associated only with the task it asks about. The answer is recorded as the result of the query and does not become content or progress of that work (otherwise, that work would appear to be doing these analyses too, and later messages would be incorrectly attached to it).
   Observed volatile state is saved as a record with its observation time.
3. **Display**: The complete reply is shown in the query panel, with numbered entries and source links to the document viewer; the conversation gives one or two sentences of conclusion and a link pointing to the reply. Thus the query's conclusion is visible in the conversation window, and later references such as “change it according to the second item” can resolve to entries in the panel. Task segments in the same message are answered in the conversation as usual.
4. **Recording**: Queries and replies are saved as searchable query records; at this stage, they are not automatically written to knowledge documents, nor do they automatically generate a Goal or Task.
5. **Turning into a task**: A task is created only when the user requests an output or change after seeing the result, with the relevant query results included in the initial context. If obtaining an answer requires changing state, CTM asks first.

### 5.4 Relay and notification

Every message CTM writes to the user is a display item that can be referred to: pending items and options are numbered and marked with the task they belong to, and the user is asked to decide only matters they can distinguish from one another at any one time.
Matters requiring a user decision, blocked work, completion, and deviations from expectations go into the conversation; other progress is updated only in the task tree and execution view.

### 5.5 Interface modifications

Each kind of modification addresses four aspects together: memory relationships (messages, constraints, and decisions are reattached accordingly); running executors (affected ones receive updates, and executors of abandoned tasks stop what they are doing; sessions are retained and reused when tasks are reopened);
pending items (transferred or withdrawn); reference points (used as a basis for future location and maintenance, not turned into hard rules).

### 5.6 Periodic maintenance

Read the message segments and progress written to memory since the last maintenance and what they belong to (the Segments and Run summaries attached to nodes for long-term storage in 3.1, not retained conversations; do not look only at the node list): merge duplicate tasks, correct parent-child and ordering relationships, group parts of the same work proposed step by step under the same parent (create a Goal for a purpose the user has stated; otherwise create a Task-level parent), reattach incorrectly attached messages to the work they actually belong to or split new nodes out of them (when new work is delivered as a continuation of current work, or a series of inquiries later develops into a work item, a node will contain messages from other work; constraints, decisions, mentions, and execution summaries for those turns written from these messages move with them; sessions already in execution are not split, and subsequent messages are delivered according to the new assignment), adjust the placement of constraints (lift and rollback, 3.5), fix statuses, and rename; run periodically, and also recheck new nodes attached under the root whose work cannot yet be identified after a few more related records have been written; this batch of records covers only work since the last maintenance, so maintenance also reviews the existing structure (3.4): group work under the Goal it serves, merge Goals for the same goal, and group several parts of the same task under one parent task; organize documents (merge duplicates, split oversized ones, mark outdated ones);
migrate constraint comments when objects are refactored. Parts modified by the user are not locked, but are changed directly only when the user's later words or actions contradict them; CTM's inferences alone can only support suggestions.

## 6. Rules

- **Authority**: User messages and interface modifications ＞ CTM's inferences ＞ periodic maintenance.
- **Rule precedence**: Explicit requirements in this message ＞ task constraints and decisions ＞ global preferences and global constraints ＞ CTM's understanding of the user ＞ persona defaults.
  When an object constraint conflicts with a task requirement and the user has not said to change the rule, the executor stops and reports through the execution control layer for the user to decide; the overall goal does not participate in this ordering and does not grant authorization.
- **Action boundaries**: The user's current message governs; for anything not stated, retain the task's previous authorization and still-valid restrictions, without independently tightening or loosening them.
- **Whether to ask or act depends on reversibility**: Local changes are versioned and can be reverted, so act first on the most likely understanding and mark that understanding in the conversation and on the tree; for
  irreversible actions or actions with external effects, such as committing, pushing, deploying, deleting, or sending externally, ask first when the understanding is uncertain. Irreversible actions encountered only during execution are allowed or escalated by the execution control layer according to the contract.
- **A proposal is not authorization**: Work put forward by planners and executors is only a proposal; work within the scope already authorized by the user can proceed directly.
- **Each handles its own work**: Executors do only the user's work and receive only the user's original words and context; CTM does its own work (memory, `ctm.md`, proposals) itself and does not pass it along to executors; words addressed to CTM are not delivered to executors (1.1).

## 7. Scenario walkthroughs

Each scenario is walked through as “message → understanding → write → action → execution context → reply,” recording the design it supports.

**S1 Query and task**. User: “Help me find out why the Y alert for service X keeps firing.” The user wants the cause → query, no node created; memory has no answer, so dispatch read-only execution;
the result is shown in the query panel, and the query record is linked to work related to service X. The user then says “Then fix it”; only this is a task (changing the service state), with the query result just obtained included in the initial context.
Execution requires a working directory and runtime environment; if these are not in memory, CTM asks first. → 3.4 criteria, 5.3.

**S2 Short approval during parallel work**. CTM has just relayed a plan for task A awaiting approval and the result of task B. User: “Okay, start.”
Pointing is to the most recently displayed pending item; if the same relay contains two pending items, it is ambiguous. → Number pending items and mark their tasks; bind short approvals to the most recent explicitly presented item;
when there are several at once, handle reversible ones according to the most recent one and explain, and ask first for irreversible ones (5.4, section 6).

**S3 Returning to old work the next day**. User: “Continue yesterday's transcription clear change.” Time reference “yesterday” ＋ object “transcription clear” → task T.
If T is not finished and there have been no major changes to the scene in the meantime, this is a continuation of T; reuse its session. If T is finished and subsequent tasks have changed the relevant code, this is a new task; create a new session, include the results of T and the subsequent tasks in the context, and have the executor check the scene.
When reusing, CTM forwards the user's words and the constraints and decisions newly established along the path while T was idle, files changed elsewhere, and relevant query conclusions; when creating a new session, continuity depends on write-back quality. → 5.2 items 2, 3, and 6.

**S4 Correction**. CTM has relayed T's implementation result. User: “No, transport must not expose a sample rate parameter.” This statement concerns the design of the module itself → object constraint,
CTM records it and at the same time rejects the executor's approach; T's session already knows from the conversation. Before an executor from other work enters this directory, CTM writes it into `ctm.md` in the transport module directory and proposes writing it into a constraint comment in the transport entry file. T's session is still active, so CTM forwards the correction to it.
Work under other Goals that modifies transport will read this constraint before changing files. → 3.5.

**S5 Delegated planning and execution**. User: “Finish feature X: design it first, then implement it, and submit a PR after the tests pass.” CTM calls a planner, and subtasks appear in the tree as proposals;
after user approval, they are dispatched according to dependencies; “submit a PR” is already authorized in the original words, so it is recorded on the corresponding subtask, with the gate “tests pass.” Executors often stop midway to ask questions,
and the execution control layer has them continue according to the contract; progress is updated only on the tree, while completion, blockage, and matters beyond authorization go into the conversation. → 5.2 item 4, 5.4.

**S6 Verify a report**. CTM relays “T is complete, 14 tests passed.” User: “Were the tests really run?” This is a query: CTM checks execution traces; if there are commands and output, it answers directly and provides evidence;
otherwise, it dispatches a read-only verification. → 5.2 item 6, 5.3.

**S7 Dependency on another task**. In task B for writing documentation, the user says “Write it according to the plan we agreed on.” The pointing method is a reference to a conclusion elsewhere; current decisions in memory are among the candidate sources,
and the decision approved by the user in A brings up task A; delivery still goes to B. B's initial context includes only this decision, not A's thread, and a cross-task reference is recorded. If A's decision changes later, B is marked for rechecking. → 3.6, 5.1.

**S8 Action after a query**. User: “What did we decide about the sample rate before?” CTM presents the current decision and the replaced history in the query panel, with numbered entries.
The user then says “Change base_recognizer according to the second item”: “the second item” resolves to a displayed entry; if the selected entry is historical, a new decision is created to replace the current decision, and the user is told that this reverts to the old plan;
then a task is created. → 5.3, 5.4.

**S9 User edits the tree**. The user drags a message from T1 to T2 and merges T3 into T1. Constraints and decisions produced by this message are reattached with it; if T2 has a running executor, it receives an update;
during the merge, the executor with less progress is stopped, and its results are written back to the merged task; the modification serves as a reference for future maintenance. → 5.5.

**S10 External changes**. The user manually changed a file, and the deployment state changed too. CTM observes the change and creates a version whose source is the user; the deployment state is recorded with its observation time.
Running executors involving that file receive an update. → 3.6, section 4.

**S11 Ambiguous reference**. User: “Change that configuration back.” Both of the two most recent work items changed configuration. Local changes are reversible: act on the most likely understanding, state “understood as changing T3's configuration back to a certain version,”
and mark it on the tree; if already pushed or deployed, ask first. → Section 6.

**S12 Interrupting execution**. User: “Stop that deployment for now.” The pointing method is control, candidates come from current and running work, and delivery is classified as control of the executor currently deploying; CTM stops or pauses it through the execution control layer,
the task is paused and the reason recorded, and any external effects already produced are reported truthfully. → 5.1, 5.2 item 5.

**S13 One message involving multiple work items**. User: “Don't merge A yet; change B's documentation according to the new plan; also check C's alert.” Delivery splits it into three parts and delivers them separately:
control for A, work content for B (“the new plan” is explained by B's current decision in memory), and a side question about C; memory records only the decision “do not merge A for now.” The reply is grouped by work, with each group separately referable. → 5.1.

**S14 Pointing out a problem while browsing**. The user selects a passage in a design document in the document viewer: “What this says is wrong; it should be commit first, then flush.”
The location signal is the paragraph being viewed; this is a correction to the design, forming a new decision that replaces the old one. The document section is marked as needing an update, and a rewrite is proposed for the next related execution. → 3.6, 3.7.

**S15 Preferences and understanding of the user**. User: “From now on, give the conclusion first in replies.” This is an explicit user preference, written at the root and effective immediately.
The user saying “Remember globally: do not commit ctm.md” is also in this category: the words are addressed to CTM, so CTM records it as a global constraint at the root and explains in the reply what it recorded, without delivering it to any executor—if delivered to an executor, the executor would treat “remember” as work to do and change its own configuration file (this happened in a real pilot trial on 2026-11-23).
On the other hand, CTM notices that the user has narrowed execution scope several times and forms an understanding of the user, “prefers minimal changes,” recording its basis as an inference and using it to define the scope of future contracts accurately,
but not overriding a broad change explicitly requested by the user on a particular occasion. → 3.3, section 6.

## 8. Design Conclusions

| Question | Conclusion | Basis |
|---|---|---|
| CTM's role | The user's sole conversational assistant; manages executors, maintains memory, answers queries, and relays results | 1.1 |
| Conversation | One continuous conversation, retaining only the recent window; long-term memory is in the tree and documents, messages are written to memory at the time, and the conversation is not compressed; pending items must go into the tree | 1.2、S2 |
| Delivery | For each message, determine only where and how to deliver it, and what to record; depending on how it points, take candidates from recent work, current and running work, objects (objects the user has mentioned, files that have been modified, current decisions), and time, then use one call to rank and select among a family of work related to the object; UI selection and explicit references determine the target directly; advancement, control, and status inquiries without pointing go to the current task | 1.2、5.1、S2、S7、S11、S12、S14 |
| Tasks and queries | Goal／Task must have a clear output or change the state of a resource; queries do not create nodes, are executed read-only, and have their records linked to relevant nodes; research not specified as serving a particular work is recorded in the query list, with conclusions written as a document that can be continued, referenced, and later attached to the tree; queries are raised in the conversation and identified by CTM, the response is displayed in a query panel without an input box, and the conclusion and link are provided in the conversation; when unsure, treat it as a query | 3.4、5.3、S1 |
| Tree hierarchy | root (global layer) → Goal → Task → subTask; a Goal is a long-term goal (stated by the user, or summarized by CTM from requests and marked as a CTM summary, which the user can change); later work with the same purpose continues to be attached beneath it; it is not a project or a working directory; every Task is under a Goal; a Task contains its subtasks (the parent task is complete only when all subtasks are complete); siblings are parallel parts or sequential steps; whether and how to split depends on the situation; wrap-up after execution is a continuation of work and does not create a node; the working directory is an important reference for judging whether work is the same task or a component of it, not a boundary; when creating a task, consider its Goal and its relationship to recent work, and periodically review the existing structure; group parent tasks by a specific piece of work, not by phase or domain; check placement by the consequences of constraints; the current task is not the default parent of new work | 3.3、3.4 |
| Root node | persona and understanding of the user are given only to CTM; the overall goal is used only for understanding and suggestions; preferences and global constraints are inherited downward | 3.3、S15 |
| Task content | Goals and scope, constraints and decisions, progress; knowledge is in documents | 3.4、3.6 |
| Constraints | Task constraints propagate downward from tree nodes; when unsure, place them lower; object constraints are comments in object files or entries in `ctm.md` at each level along the path (the nearest takes precedence); without comments there are no constraints; `ctm.md` is written by CTM (before an executor that needs to read it from the file starts); comments are proposed by CTM and written by an executor after the user agrees | 3.5、S4 |
| Respective responsibilities | The user's work goes to executors, with only the user's exact words and context; CTM handles its own matters (memory, `ctm.md`, proposals) and words addressed to CTM itself | 1.1、Section 6、S15 |
| Decisions and documents | Decisions are authoritative, brief entries; Agent behavior guidance is a third kind of knowledge (of the same kind as a skill), stored as a document with “when to use”; documents have types and versions, distinguish verified from unverified, reference decision IDs, have one writer at a time, and are revised when used if outdated | 3.6、S7、S14 |
| Working directory | At the concept level, only working directories and file versions are recognized; branches and the like belong to the execution level; one modifier per working directory at a time | 3.6 |
| Execution | If judged to be a continuation of the original task, reuse its session; if judged to be a new task, create a new one (it is usually a new task when the original task is complete and the scene has changed); sessions normally do not end; queries fork a session for answering; a new executor's initial context is relatively small (paths, recently executed siblings, and the original text of the last few turns of conversation); the executor asks for what is missing; the contract uses the user's exact words as the goal, without rewriting or adding requirements; attach the original text of recent exchanges on the work line | 5.2、S3；evaluation phase 4 |
| Execution control layer | Drives execution to completion under the contract; continues directly after pauses within the authorization; passes only matters requiring memory, user decisions, out-of-bounds actions, completion, and failure to CTM | 5.2、S5 |
| Results | CTM summarizes and writes to progress; long content goes into documents; when the user is in the loop, the user's reaction determines what to remember; traces take precedence over self-reports | 5.2、S6 |
| UI modifications | The user is authoritative; propagate across four aspects; no locking, but only the user's later input directly changes it | 5.5、5.6、S9 |
| Action boundaries | Follow the current message; otherwise retain the task's authorization; whether to ask or act depends on reversibility; the control layer checks irreversible actions at execution time | Section 6、S11 |
| Time | Constraints do not decay; volatile states carry observation times; time references are resolved to specific instances | Section 4 |

## 9. Questions That Reasoning Cannot Resolve and That Need Validation

1. **User habit premise (1.4)**: How users identify work when there is no session context.
2. **Understanding**: The accuracy of locating work and resolving references, distinguishing queries from tasks, and judging the type and location of constraints, especially in ambiguous cases such as S2 and S11.
3. **Execution**: Whether a relatively small initial context plus questions as needed can enable executors to act correctly; whether executors follow constraint comments and fail to ask when they should.
4. **Control layer**: The accuracy of distinguishing procedural pauses from substantive issues.
5. **Relay**: The proportion of cases in which users ask follow-up questions or make corrections because the relay was incomplete.
6. **Correction burden**: How often users need to change the tree, and whether similar errors decrease after changes.
7. **Cost**: Model calls and tokens per user message, execution, and query.

See [Goals and Method](goals-and-method.md) for validation methods: test data must match the target scene (the user faces one assistant, with no session); history from within a session cannot be used directly as a test.


## 10. Future Directions (Not Yet Designed)

CTM is a personal assistant: after a period of adjustment, its context automatically aligns with the user's work goals, and it draws on multiple runtime environments to complete tasks. To do this, the model needs three more axes in addition to the work tree and object axes:
**Resources** (repositories, machines, remote hosts, clusters, services, with identity, state, rules, and permission attributes, bidirectionally linked to work), **feedback** (the user's corrections and approvals are attributed to judgments,
and consolidated into understanding of the user, preferences with a scope of application, methods of working, and long-term authorizations), and **non-message input** (time and events, which, like messages, are first judged as to which work they belong to).
None of these has been designed yet; see Section 6 of [Goals and Method](goals-and-method.md) for the underlying capabilities needed and their order. The design must still follow the rules in Section 6: the user's words take precedence, ask or act according to reversibility,
do not create obligations on the user's behalf, and give executors only a small but sufficient context.
