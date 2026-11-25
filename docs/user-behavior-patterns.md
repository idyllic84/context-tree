# User Behavior Patterns

> Purpose: These are user habits summarized from past collaboration. They serve as the initial content for “understanding of the user” (3.3) in the [CTM concept model](ctm-concept-model.md),
> and are also used to determine which scenarios are common and to find counterexamples for reasoning through scenarios. They come from historical records within sessions and cannot be used directly as tests for scenarios without sessions (see [Goals and Method](goals-and-method.md)).
>
> Data: Local agent conversation logs, with 415 sessions and 15,031 actual user messages, excluding tool results, system injections, and fork mirrors.
> Method: First, openly code 480 messages to obtain an initial classification; then perform a coarse LLM annotation of the full dataset to obtain the distribution; finally, sample incrementally, reading a small batch in each round and reporting only new findings, stopping after two consecutive rounds with no new findings at the message level.
> Annotations are based on a single LLM judgment and have not been calibrated by humans; private source text and annotations are outside Git, and this document provides only summaries and relays.

## 1. Problems with the Original 4 Categories

Of the original four categories—query and research, task description, behavior guidance, and discussion—73% could be assigned to a single category in open coding,
16% were mixed, and 11% could not be assigned. There were three main gaps:

- **Status verification and correction are two major independent behaviors**, not subsets of “query” or “guidance”;
- **Short control messages** (“continue,” “make the change,” “don't push yet”) change authorization and lifecycle and need separate handling;
- **User feedback from the scene** (pasting logs, reporting the results of their own actions) serves to refresh the state, not to assign a task.

## 2. Message Level: 9 Main Categories (Full-Dataset Distribution)

| Main category | Share | Median length (characters) | Relationship to original 4 categories | Share followed by a correction |
|---|---:|---:|---|---:|
| Delivery execution | 25.4% | 39 | ≈ task description | 16.7% |
| Seeking knowledge and explanation | 19.4% | 35 | ≈ query and research | 12.3% |
| **Status and evidence verification** | 17.4% | 31 | New | 14.3% |
| **Correction and repair** | 16.4% | 41 | New (part of the original “guidance”) | **25.6%** |
| **Flow control** | 9.5% | 11 | New (another part of the original “guidance”) | 15.1% |
| Solution co-creation | 6.0% | 45 | ≈ discussion | **19.5%** |
| **Scene feedback** | 4.3% | 108 | New | 14.8% |
| Context routing | 1.2% | 58 | New | 14.0% |
| **Acknowledgment and closure** | 0.4% | 3 | New | — |

Another 225 messages were automated or templated. Mixed intents accounted for 13.9%, expressed through secondary categories.

Incremental sampling added 4 subtypes:
- **Clarification response／slot filling**: Answering the agent's clarification questions item by item;
- **Social opening**: Only a greeting or re-establishing contact, not closure;
- **Review-gated conditional execution**: Verify first, then implement; subsequent actions depend on the review results;
- **Pause plus rollback**: In addition to stopping, undo changes that have already occurred.

## 3. Orthogonal Labels: Determine “How to Do It, How Long to Remember It, and Where to Get It”

| Label | Values | Key data |
|---|---|---|
| Action boundary | Understanding only／scoped authorization／prohibition or restriction／undecided | More than 90% of seeking knowledge, verification, and co-creation is “understanding only” and cannot be treated as authorization to modify; 28% of flow control is prohibition |
| Validity period | This instance／task duration／long-term | 64% of correction, 55% of flow control, and 40% of delivery execution are valid for the task duration: these constraints must persist until the task ends |
| Context source | Self-contained／adjacent／distant／external scene | Adjacent 65–97%; about 70% of seeking knowledge, delivery, and verification require the **external scene**; distant accounts for only 9.7%, concentrated mainly in delivery, co-creation, and verification |

Conclusion: Most messages are short and depend on immediately adjacent turns and the real-time scene; demand for “distant history” is small, but when it is needed,
it mostly concerns constraints, old decisions, and old tasks, and the cost is high.

## 4. Work Level: The Real Units Within a Session

When reading session excerpts incrementally, new patterns continued to appear over 8 rounds, indicating that session-level forms are varied,
but they reduce to 5 types of work units. This is the concrete meaning of “organizing by session is too coarse”:

| Work unit | Typical patterns | What context should preserve |
|---|---|---|
| Artifact lifecycle | Multistage evolution around the same document or code; old and new implementations coexist until retirement; user edits create a new baseline; cross-file rules require checking each location | The artifact's current baseline, version, stage, and covered and uncovered locations |
| Investigation／verification cycle | Recurrence after a fix is claimed requires reopening the investigation; evidence-gathering methods escalate step by step; reconstructed evaluation criteria invalidate old conclusions; verification advances through delivery levels; an observation period follows release | A ledger of hypotheses and evidence, with time windows and “generations”; the criteria under which conclusions apply and invalidation markers |
| Constraint and role binding | Constraints have scopes, override one another, and act as execution gates; reference objects and modification objects are easily confused; identifiers and statistical units need calibration | The set of active constraints, including scope and duration; object role table (reference／modification／upstream／downstream) |
| Task stack and suspended obligations | The main task is blocked by an observed problem, then returns after a repair branch; long-running background operations are suspended; an explanation branch cannot offset outstanding delivery obligations | Unfinished obligations, in-flight operations, return points |
| Decisions and consolidation | A solution is recalculated after a premise is corrected; experience from exploration is distilled into an operating protocol; abandoned proposals leave negative conclusions | Decisions and their premises, rejected proposals and reasons, reusable processes |

## 5. How CTM Handles Each Category of Message

| Main category | What it is in CTM | Handling points |
|---|---|---|
| Seeking knowledge and explanation | Query | Do not create a node; answer directly if memory can answer, otherwise use read-only execution; make no changes |
| Status and evidence verification | Query | Check execution traces and observation records; distinguish verified, inferred, and unknown; do not repair automatically |
| Delivery execution | Task (new or continuing an existing task) | Dispatch as soon as the scope is clear; include constraints on the path and object constraints with the contract; report artifacts, verification, and what remains |
| Solution co-creation | Query, or a task to produce a design document | A query when only discussing trade-offs; a task when a solution document is to be produced; record the resulting choice as a decision |
| Correction and repair | Rejection of existing content and new constraints | Record rejected content as a rejected proposal; determine whether new requirements are task constraints or object constraints; affected ongoing executions receive updates |
| Flow control | Control over pending items and executors | Bind approval to a numbered pending item; pause and stop through the execution control layer |
| Scene feedback | Material and observations | Store long material as documents; link results to in-flight execution or investigation |
| Context routing | Locating | Retrieve nodes by references to objects, work names, or time; exclude recent but unrelated work |
| Acknowledgment and closure | Acknowledgment of presented content | Respond briefly; do not start a new action |

## 6. Initial content as “understanding of the user”

1. **Messages are short and depend on nearby turns**: Most messages are short, and 65–97% depend on immediately preceding turns; in CTM, the recent part of the conversation and displayed artifacts handle this.
2. **Long-range dependencies are rare but costly**: Only 9.7% of messages depend on distant history, mainly constraints, old decisions, and old tasks. These must be written into the tree and object constraints, rather than left in the conversation.
3. **Corrections can cascade**: After a correction, the next message is still a correction 25.6% of the time; after collaborative solution design, the figure is 19.5%. Rejected content and affected artifacts must be explicitly recorded and handed to the executor.
4. **Scope is often narrowed**: About half of corrections concern scope errors. When CTM writes an execution contract, it should specify the scope accurately and err on the narrow side when uncertain.
5. **Authorization depends on specific actions**: More than 90% of requests for knowledge, verification, or co-creation are only cognitive needs, not authorization to modify; short authorizations (“okay,” “continue”) apply only to explicitly proposed pending items.
6. **Most constraints last for the task**: 64% of constraints from corrections, 55% from process control, and 40% from delivery execution must persist until the task ends.
7. **The scene takes precedence over history**: About 70% of requests for knowledge, delivery, or verification depend on the external scene; memory preserves “where to read, what was read last time, and when it was observed,” rather than the scene content itself.
8. **Work units** (Section 4) correspond to structures in CTM: artifact lifecycle → documents and file versions; investigation and verification cycle → query records and report documents; constraint and role binding → two types of constraints;
   task stack and suspension → task relationships, pending items, and in-flight execution; decisions and consolidation → decisions and knowledge documents.

## 7. Limitations

- A single LLM annotation pass, with no human calibration; claude accounts for 62% of the sources; session-level patterns have not yet reached saturation.
- The data comes from within sessions, where users speak differently than they do with a sessionless assistant; “how users specify work when there is no session context” requires separate research (the first message in a session, messages after a long interval, etc.).
