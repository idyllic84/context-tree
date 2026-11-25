# Goals and Method

> This document explains what the project aims to achieve, how to measure it, and how to advance it. For the design itself, see [CTM Concept Model](ctm-concept-model.md).
> For the record of the direction correction on 2026-10-12 (evidence of deviation and the arrangements at the time), see section 3 of [Evolution](evolution.md) (the original record was removed during archive cleanup).

## 1. Goals

The project's original goal has always been: **a real-time task tree context manager** that gives executors smaller but sufficient context without reducing execution quality, and enables work to continue across sessions. CTM's design was proposed independently; similar work found in research (such as HiAgent's subgoal working memory) serves only as a point of comparison. See [Related Work Research](related-work.md).

Its specific form now is CTM: an assistant that the user interacts with. It must:

1. **Understand correctly**: Without a session, determine which work, object, or displayed item the user's message refers to, and distinguish queries from tasks.
2. **Execute correctly**: Give the executor context that is small but sufficient, so the executor can do what the user wants correctly, without overstepping, missing constraints, or inventing obligations.
3. **Remember**: Keep the goals, constraints, decisions, progress, and knowledge of work correct in long-term memory, and retrieve them across time and across work.
4. **Answer accurately**: Answer knowledge queries correctly and traceably, keeping historical and current information separate.
5. **Keep the burden low**: Minimize how often the user needs to correct CTM, and reduce errors of the same kind after one correction.
6. **Make cost measurable**: Model calls, tokens, and latency for each message, execution, and query must be measurable and acceptable.

## 2. Metrics

| Metric | Content | Corresponding goal |
|---|---|---|
| Understanding | Proportion of correct identifications of work, objects, and displayed items; accuracy of distinguishing queries from tasks and judging constraint types and locations | 1 |
| Execution | Whether the executor's understanding of and approach to the user's request are correct; high-consequence errors: wrong object or scope, continuing to use an overturned understanding, inventing obligations, omitting constraints in effect, missing key facts, repeating non-repeatable actions, treating reports as facts, excessive tightening | 2 |
| Memory | Whether work state, constraints, and decisions can be correctly retrieved after a long time | 3 |
| Query | Accuracy of query answers and completeness of source attribution | 4 |
| Correction | Frequency with which the user changes the tree, changes constraints, or repeats the same request | 5 |
| Cost | Number of calls, tokens, latency, cache hit rate; size of context delivered to the executor | 6 |

Comparisons: full history (truncated to the model's budget), recent window, flat summary, vector retrieval, HiAgent-style subgoal summarization. CTM is a hypothesis; losing to a baseline is also a conclusion and is retained.

## 3. Method

### 3.1 Reason first, experiment later

- **Advance the concept layer through walkthroughs**: Take typical scenarios and walk through them step by step in the order “message → understanding → write → action → execution context → answer,” looking for three kinds of problems: missing information, ambiguous judgments, and rule conflicts.
  Each concept must correspond to a situation in a scenario where “without it, the judgment would be wrong” (necessity); a distinction is worth modeling only if it changes the handling in at least one scenario (distinction test).
  After each modification, walk through all typical scenarios again.
- **Layers**: The problem and world model, concept model, mechanisms, and evaluation each answer different questions. Solve problems at the lower layer there; return to an upper layer only when observations show that its assumptions are wrong.
- **Experiments answer only questions that reasoning cannot settle**, mainly concerning model capabilities and scale (such as whether an LLM can reliably identify the target from messages and displayed materials). Before doing one, state clearly: the question to be answered,
  why reasoning cannot settle it, whether the experimental premises match the target scenario, and which result would change which concept. Keep experiments as small as possible, and write conclusions back to the corresponding layer.
- **Decision records**: Record problems, conclusions, and grounds in the design documents; when making changes, replace old content and move the process and rejected alternatives to the archive. Retain unfavorable results and failures.

### 3.2 Proper use of data

- Historical conversation records were produced with a session already open: the user said “continue” or “that” because the session had context. They **cannot be used directly to test CTM without a session**;
  direct replay inherently favors the recent window.
- Historical records are used to: summarize user habits as initial content for CTM's “understanding of the user” ([User Behavior Patterns](user-behavior-patterns.md),
  [Agent Reply Analysis](agent-reply-analysis.md)); understand how often scenarios occur; find counterexamples that cause walkthroughs to fail.
- Test data must match the target scenario: the user faces one assistant, multiple items of work run in parallel, and there is no session. When testing by block, use historical records and independent annotations to construct the input for each block
  (for example, build a reference memory based on the annotated work structure, then pass subsequent messages one by one to delivery), so that the bias introduced by sessions in the history does not enter the judgment under test; records from real use are the ultimate source of data.
- Labels come from the agreed results of two annotators independent of the system under test, and from the user's actual subsequent behavior (which work later messages continue, whether the user corrects anything, and the actual response to an executor's stop);
  items where the two sources disagree are not scored. Do not ask the user to spot-check: a judgment the user gives on a sentence outside its original context is not valid evidence.
- **Annotate according to the CTM scenario, not the source session**. Annotators see only what CTM actually had at the time: the content in a single conversation before this message (multiple sessions interleaved in chronological order) and where each message was delivered,
  CTM's memory at the time (what work exists and what the user has said in each item of work), and the interface state (current work and whether the user has selected a node); as subsequent evidence, use only later messages in this conversation, not the context or subsequent content of the source session.
  Annotate how CTM should handle the message; mark “unclear” when it cannot be determined in this scenario. In the source session, the user said “continue” or “this” because the session had context. CTM does not have that context, so it cannot be used to assign labels.
- **Structure has no unique answer; evaluate by consequences**: There are often several reasonable ways to organize the tree (which Goal to place something under, what is the parent of what, and how finely to divide it), and the tree can be adjusted at any time. Comparing or spot-checking against one person's organization at one point in time cannot measure how good the tree is; it only counts another reasonable approach as wrong. Evaluate structural judgments by their consequences: it is an error when a new execution inherits irrelevant constraints, when required long-term requirements are not passed on, or when the scene the executor sees is not useful for this work. Judges decide “whether this placement is reasonable”; count it as an error only if both consider it unreasonable, and also report the proportion for which “several placements are reasonable.” In real use, the user changing the tree directly is the most direct signal.
- Measure every modification on unused data; do not repeatedly use the same batch of data to tune the same prompt. No single run exceeds 30 minutes.

### 3.3 Division of Work with the User

The user provides direction and goals and challenges the reasoning; the researcher is responsible for all other judgments: working through scenarios and challenging their own reasoning, conducting research or small experiments when uncertain, making decisions based on the project goals, and reporting conclusions and supporting reasons,
without asking the user to decide design and evaluation questions. The user's proposals must be understood critically: test them in scenarios, identify gaps and risks, and then provide an improved plan rather than copying them.

### 3.4 Block-by-Block Optimization

CTM's work is divided into blocks by **judgment**, not by call or code: one call can belong to two blocks at once (the delivery call gives both “where it goes” and “where the new work is attached,” evaluated against the annotations for blocks 1 and 2, respectively).
Each block has its own inputs, outputs, metrics, and test set. **When measured separately, upstream inputs are always reference inputs**—annotations or outputs from a frozen fixed version—so only that block's errors are measured;
if a block can only be evaluated through another block, the division into blocks is flawed. Checks of the whole pipeline (delivery consistency in replay, constraint delivery, cost, etc.) are only for monitoring: they are used to find problems,
attribute them to a block, and then confirm and improve them using that block's independent evaluation. Parts of the code that execute according to rules (successors can execute after prerequisites are complete, results are folded upward, and constraints are inherited along the tree) are ensured by unit tests, not judgment blocks.

| Block | Judgment to make | Reference input | Metrics and annotations |
|---|---|---|---|
| 1 Delivery | Which existing work this message goes to, or whether it is new work, a side question, research, or control | Reference memory built from annotations and the current task | Compare the destination and method with the annotations |
| 2 Work relations | What relation exists between two items of work: a component, sequential steps, which Goal it serves, whose results it needs, or whether they are actually the same item. The placement of new work, structure judgment, Goal, moves and merges in maintenance, and cross-task references are all judgments of this kind | A set of known work items (title, purpose, original words), and relations provided by the system | Whether every relation written in the tree is true (precision); pairs of work items that the judge considers should be connected but are separated in the tree (recall). No comparison with a particular “correct tree”; multiple reasonable structures can all score highly |
| 3 Memory write | What to remember, which category to record it in, which level to attach it to, and which entry to replace | Reference delivery and reference tree | Recall, precision; coverage based on meaning (attaching an item to a node makes it apply to the work below it: what should and should not be covered); whether replacements are correct |
| 4 Execution context | What to select from memory to give the executor | Frozen reference memory (delivery and tree construction according to annotations, stored original exchanges, summaries and entries from a frozen version) | How much of the information the executor needs and that is actually in memory entered the context or was accompanied by a clue that can be used to find it; context length |
| 5 Result write-back | Progress summary | Executor's reply | Check each sentence for supporting evidence; whether information actually needed later was written in |
| 6 Execution control | Stop type, whether it is formally complete | Recorded stops | Annotations agreed on by two people and the user's subsequent actual response |
| 7 State | What state a work item is currently in | Reference record of the work item, and whether it was subsequently continued according to the annotations | State annotations agreed on by two people |
| 8 Answering queries | Whether to answer from memory or dispatch read-only execution, and whether the answer is correct | Memory and questions | Probe questions generated from records and scored by two people |
| 9 Relay | What to tell the user, how to number it, and which alternatives to offer | — | Can only be tested in real use |

See [Boundaries and Interfaces of the Blocks](block-interfaces.md) for the data each block reads and writes and its users; the current state, commands, and results are recorded in [Plan for Blocks 3–6](blocks-3-6-plan.md) and section 7 of the implementation plan.

### 3.5 Automated Evaluation

Relying on user pilot trials for feedback is too slow. Evaluation runs automatically on real conversations newly added by the user each day; every change is compared with the previous version on a recent segment that no change has seen, so test data rotates naturally.

- **Replay**: Starting from the memory before this segment, give new messages to CTM one by one in chronological order; the executor is not rerun, and replies recorded in the history are used instead. At each step, the past CTM sees is real,
  and only the decision at that step is evaluated (where to deliver it, what to give the executor, and what to record), so the user's later words in the history remain valid evidence; replay cannot evaluate how the conversation would proceed after CTM changes its behavior, so simulated users are used to supplement it.
- **Four types of checks** (judged by two judges independent of the system under test, counting only cases where they agree):
  1. Correction points: Where the user corrects the executor, first identify the cause—CTM (information stated elsewhere was not passed along, or delivery went to the wrong work), the executor (the information was already in the current session), or the user changed their mind;
     where CTM is the cause, check whether what CTM gives the executor in the same scene contains the information required by the correction.
  2. Delivery consistency: When CTM delivers messages that the user continued to send in the same session in the real history to different work items, judge whether the delivery was correct; messages that return after a long gap are counted separately.
  3. New executor's context: Where CTM starts a new executor, check which information from earlier conversations the real executor's answer depended on and whether it is in CTM's context; how much content in the context is unrelated to the current request (leakage).
  4. Cost: Calls, tokens, and time per message, and the size of the context given to the executor.
- **Public data as a supplement**: MemoryCode (coding instructions given and then updated across sessions, scored using its own rules, with full-history and no-history controls); aider and SpecStory conversations committed to public repositories
  (another real user, to avoid adapting to only one person). They are mostly in English and cover a single project, so they only supplement rather than replace the other data.
- Under the user's original way of working (one session open for several days), corrections mostly occur during repeated revisions in the same session, and the cause is usually the executor; events where information is lost across sessions are rare.
  Therefore, looking only at correction points is not enough; delivery consistency and the new executor's context are the main checks in the CTM scenario.

## 4. Experience Gained So Far

| Experience | Source |
|---|---|
| A research cycle without a measurable goal turns every counterexample into a new qualification, appearing to make progress while actually drifting away from the goal | Sections 2–3 of [Evolution](evolution.md) |
| Errors that require correction are mostly judgments about behavior at the time, not missing memory; long-term state, however, clearly depends on memory | Pilot 01 (cleaned up) |
| Time weighting significantly improves location without a session; explicitly judging “continuation, switch, new work, unrelated” improves new work identification | Validation 01, Optimization Plan (cleaned up) |
| Dumping all memory into the executor creates confusion, especially when outdated or overly broadly placed constraints cause excessive restriction; supplementing strictly as needed can avoid adding confusion | Validation 02 (see [Evolution](evolution.md) 3.2) |
| Only a small portion of agent replies is actually used later; the user cares about the parts they point to and the key points needed to continue work | [Agent Reply Analysis](agent-reply-analysis.md) |
| Testing directly with session history leads to conclusions biased toward the recent window | Limitation of Validation 02; pointed out by the user |

## 5. Retained Principles

- Organize by work and purpose, not by subject, directory, or time; the same object or topic does not imply the same work.
- Use only LLM understanding or vector similarity for semantic judgment; do not use literal, keyword, or regex matching as a semantic fallback.
- Do not create obligations the user did not request; unknown is neither complete nor failed; keep reporting separate from verification.
- Calculate budgets based on each model’s actual limit; do not impose an artificially small window.
- Keep private records outside Git; do not modify production providers, credentials, or the pi runtime until an explicit runtime integration step; do not touch other projects.


## 6. Future Direction and Capability Roadmap (2026-11-25)

**Direction**: CTM is a personal assistant. After a period of adaptation, its context automatically aligns with the user’s work goals, and it mobilizes multiple runtime environments to complete tasks:
It remembers the user’s preferences and goals and proactively assists; it knows the runtime and modification environments for each task, executing not only locally but also using remote resources over the network; it remembers every code repository the user has worked with.
All these capabilities extend from the existing model, rather than being copied from other products.

**What the model needs to add**: The existing model has two organizational axes (work tree; objects), two inputs (user messages; executor replies), and the outside world appears only as working directories and files. The direction requires three more axes:
- **Resources**: Repositories, machines, remote hosts, clusters, and services are entities with identities, states (with observation times), rules, and permission attributes, linked bidirectionally with work (where tasks run and which resources they modify);
- **Feedback**: Attribute the user’s corrections, rejections, restatements, questions they consider unnecessary, and approvals to the judgment that caused them (delivery, memory, context, control), then consolidate them into understanding of the user, preferences with scopes, ways of working, and long-term authorizations, and measure their effects;
- **Non-message inputs**: Time and events (CI, PR, deployment, alerts, executor completion) are also inputs. As with messages, first judge which work they belong to, then propose or prepare within the authorized scope, without creating obligations for the user.

**Underlying capabilities needed**:
- A Resource model: Resource identity (different clones and remote addresses of the same repository, and what the user calls it; environment identity); resource state; knowledge and rules about resources; relationships between work and resources; populate from history, execution traces, and observations.
- B Execution plane: Place executors locally, on remote hosts, or in the cloud; only one modifier at a time for a resource being modified (use worktrees to isolate parallel work in the same repository); decide whether to ask first or act first by “action × resource”; pass credentials to the execution environment only by reference; include a description of the current environment in the execution context.
- C Learning loop: Result signals and attribution during operation; consolidate them into proposals outside the critical path and have the user confirm them; extend the scope of preferences and the user model to goals, resources, and types of work; goal model (priorities, deadlines, success criteria, progress); process memory; authorization that can learn; measure adaptation (when completion rates do not fall, the number of corrections, questions, and times the user opens the original reply decreases).
- D Proactivity: Ingestion of events and time; event delivery; what is worth interrupting the user for and a budget for interruptions; authority boundaries when no one is present (only prepare reversible actions, only propose irreversible ones, say nothing when there is no change).

**Order** (by necessity and difficulty; the foundational capabilities have not yet been polished, so only new capabilities that are easy and directly help the foundation are done first):

| Order | Capability | Necessity | Difficulty | Reason |
|---|---|---|---|---|
| 1 | Result signals and attribution during operation | Highest | Low to medium | The old evaluation corpus has been cleared; polishing the foundation can only rely on real use; it does not depend on other parts and is the evaluation foundation for every subsequent step |
| 2 | Polish block 1 delivery | Highest | Medium | About 18% are connected when a new one should be created; three cases have not been systematically measured: treating a new deliverable as a supplement, control finding the wrong object, and answers to an executor’s report that should be delivered back to it; median time before work starts is about 14 seconds, about 14,500 tokens per message |
| 3 | Polish block 3 memory | Highest | Medium to high | One-off changes and long-term rules are hard to distinguish (about half of object constraints are remembered correctly); replacing an entire entry when only part should change; duplication between constraints and decisions; remembering a rejected direction as the opposite |
| 4 | Polish block 4 execution context and block 2 structure | High | Medium to high | Steps in the same work are scattered across several work items; errors issued between a temporary hold and a correction, and propagation of corrections to a running executor, have not yet been measured |
| 5 | Resource identity and repository registration | High | Low to medium | Most can be established deterministically from imported history, execution traces, and git remotes; directly helps delivery (finding candidates by repository) and context (builds, tests, conventions) |
| 6 | Structured recording of task runtime and modification environments (still executing locally) | High | Low to medium | A prerequisite for the execution plane; does not itself touch remote environments; test it using evaluations of blocks 3 and 4 |
| 7 | Polish control and relay (blocks 6 and 9), and whether executors honor agreements | Medium | Medium | False reports of overstepping during the pilot trial, answering on the user’s behalf about irreversible deletion, and discrepancies between executor self-reports and tool records all belong here; item 1 is needed to measure them systematically |
| 8 | Expand the scope of preferences and the user model | Medium to high | Medium | Reuse the scope mechanism for constraints; the difficulty is deciding which layer to put them in; the first step in adaptation |
| 9 | Goal model | Medium | Medium | Both context selection and proactive proposals depend on it; inferences are confirmed by the user |
| 10 | Consolidation in the learning loop (understanding of the user, ways of working, long-term authorization) | High in the long term | Medium to high | Depends on items 1 and 8; learning authorization incorrectly directly affects safety and must be confirmed by the user |
| 11 | Execution plane (remote placement, credential channels, per-resource authorization, isolation) | Required for the direction | High | Errors in remote environments are more likely to be irreversible; items 5, 6, and 7 are prerequisites |
| 12 | Non-message inputs and proactivity | Medium | Highest | The cost of interruption is hard to measure, event delivery is a new challenge, and safety requirements are strictest when no one is present; items 9, 10, and 11 are prerequisites |

The execution plane and proactivity come last: both expand CTM’s range of actions into irreversible domains, and will only amplify errors while delivery, memory, and control are still making mistakes.
For comparisons with related products (the problems each solves, and mechanisms that can and cannot be used as references), see [Related Work](related-work.md) 2.9.
