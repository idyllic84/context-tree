# Evolution of Technology Choices and Processing Logic: Difficulties and Decisions (2026-04 to 2026-11-23)

This document records **what blocked the project at each step, what options existed, why a particular choice was made, and how its costs later became apparent**. It was written before the historical archives were cleaned up; the archives were deleted at the user's request on 2026-11-23,
and this document has been the reference since then. For the current design, the authoritative sources remain the [CTM Concept Model](ctm-concept-model.md), [Goals and Method](goals-and-method.md), and [Implementation Plan](ctm-implementation-plan.md).

Sources: Section 1 and the beginning of Section 2 are taken from the original research and development log and development log preserved in the 10-01 commit (`git show b3d83e1:docs/history/companion-v2-research-log.md`,
`docs/development-log.md`); the rest of Section 2 is taken from records of direction corrections, for which the original turn records have been deleted and only the conclusions retained; Sections 4–6 are taken from the current documents and the execution records in Section 7 of the implementation plan.

## 0. Six Recurring Decisions

The project has always sought to do the same thing: **organize conversations with agents around the evolution of work, give each execution a small but sufficient context, and enable work to continue across sessions.**
The approach changed several times because the following six questions had to be answered again at every stage, and each answer was overturned or revised by later facts.

| Decision | Initial answer | Intermediate answer | Current answer | What drove the change |
|---|---|---|---|---|
| Unit of memory | Knowledge entities (decisions, questions, solutions, terms) | Atomic propositions → Goal/Task subtrees → semantic work memory with field-level provenance | "Work" defined by purpose (Goal/Task), preserving the user's exact words, with details in documents and original exchanges | Entities and propositions fragmented and duplicated the same thing; semantic subdivisions grew finer without improving context |
| Who makes judgments | Code rules and state machines (recognize only explicit approval, filter temporary wording, scoring formulas) | LLM judgment, but prompts are lists of rules and examples | The LLM analyzes before judging; prompts describe purpose and the cost of errors; code handles only storage, delivery, execution signals, and safety limits | Rules failed on the next example; rules added for individual errors were "code disguised as prompts" |
| Retrieval or structure | Vector retrieval, n-hop graph traversal | Vector recall followed by branching according to tree structure | Get candidates by "pointing method" (object → work that has touched it, most recent, running, time), then use a delivery judgment; no vectors for whole messages | Vectors grouped things with similar topics but different work; the tree structure itself encoded "whether this is the same thing" |
| What to measure | Extraction coverage, purity, hallucination | Public memory benchmarks → whether semantics are completely correct and how much history was read | Context size, localization, and cost at equal quality; use blocks by judgment type and evaluate independently with reference inputs | Public benchmarks were not a fit; easily measured things replaced the goal |
| Division of responsibilities between user and system | The user states requirements, and the system decides the design on its own | The user spot-checks and sets standards | The user sets goals and principles; design and evaluation questions are decided by reasoning and experiments; standards come from independent annotation and subsequent behavior | Every architecture rewrite stemmed from a misunderstanding of the user's intent; the user's spot-checks depended on the situation at the time, so the questions could not serve as standards |
| How far offline work can go | Demonstrations and manual observation | Replay real records | After taking block-based offline evaluation as far as possible, conduct a real pilot trial | Whether executors follow constraints and how much the user must correct can only be seen in real use |

## 1. Stage One: Yanmo Companion (around 2026-04)

### 1.1 Understanding at the Time

Yanmo was originally a macOS voice dictation tool. After a "voice → text → Agent" workflow took shape, the user found that decisions made, pitfalls encountered, and solutions agreed on in each session did not carry over across sessions,
and had to be explained from scratch when a new window was opened. The idea was therefore to use Claude Code session records (JSONL) as raw material and distill them into a knowledge graph spanning sessions, agents, and projects, prompting "X was decided the last time this topic came up" when the user entered text.

### 1.2 Difficulties and Decisions

**V1: Local GraphRAG, embedded in Rust＋Tauri.** Markdown was the source of facts (people could read and edit it, and it could go into git), while SQLite served only as an index; entity types were taken from academic GraphRAG: decisions, topics, questions, solutions, and terms;
retrieval progressed from full-text search to vectors, then to having an LLM decide which nodes to expand; it borrowed Graphiti's dual time model (valid time and write time, invalidating rather than deleting).

- **Difficulty one: Iteration was too slow.** Every change to a prompt or extraction logic required waiting 3–5 minutes for Rust compilation and an end-to-end build. Engineering held back algorithm evolution.
  → **Decision**: Freeze V1 and create a separate Python sandbox, reducing the time from "changing a prompt to end-to-end validation" from minutes to seconds. Cost: the embedded product form was abandoned, and it has remained a research prototype ever since.
- **Difficulty two: Flat message extraction lost task structure.** The user's "good" could not be linked to the agent's specific proposal; the reference in "use the second proposal" could not be resolved; a single decision process was split into several independent entities;
  "good" and "ok" were filtered out as noise, losing signals of approval; intent classification mixed two dimensions, "conversation behavior" and "task state change"; academic entity types had to be translated again before they could be used by agents.
  → **Decision**: Change entity types to constraints, background, experience, and terms that agents actually need; replace fixed n-hop traversal with LLM decisions on expansion; stop filtering short replies.
  This set of problems—**references, approval, and a single process being split apart**—reappeared in new forms at every subsequent stage, until CTM v2 resolved them conceptually with "numbered items shown to the user" and "organization by work"—numbered pending items were not completed in the implementation until 2026-11-20 (Section 6.1).

**V2: Conversation units.** People had 7 conversation behaviors (assigning tasks, adding constraints, setting rules, approving, rejecting, ...), and agents had 3 (proposing, explaining, asking); each utterance was split into atomic propositions that could be approved or rejected individually;
changes in time interval, working directory, and git branch were computed as signals by the parser, not left to the model.

- **Difficulty three: A state machine that recognized only explicit approval severely underfit.** In an exploratory session, the user assigned tasks 23 times, and the agent provided 405 pieces of decision-relevant content, but there was only 1 explicit "yes" or "no".
  Recognizing only explicit approval would lose all 405. → **Decision**: Introduce "soft completion": when the user moves to a new task, previous proposals that were not rejected count as low-confidence outcomes.
  The understanding established at the time—**"moving on means approval" is a real interaction pattern; a state machine cannot rely only on explicit signals**—later evolved into the current principle that "the user's reaction to a relay determines what a pending item becomes".
- **Difficulty four: Temporary statements were treated as long-term decisions.** "Don't change the code yet" was judged to supersede "implement a deduplication mechanism". → **Decision**: Filter short text containing temporary wording, and emphasize in the prompt that only long-term policies can supersede.
  This was a typical case of "using a rule to fix one error", later deemed undesirable; the same kind of problem (a change to be made this time being recorded as a long-term rule for the object) appeared again in the real pilot trial on 2026-11-23.
- **Difficulty five: Large sessions did not fit into a single call.** A session of about 700 turns and 300,000 characters caused gpt-5.4 to time out. → **Decision**: Process in batches and switch to gemini-3-flash, with a context of 1 million.
  From then on, model choice was constrained first by "how much fits in one call", until CTM switched to processing messages one by one and this ceased to be a bottleneck.

**V2-B: Decision-centered.** Tests showed that one agent reply was split into multiple proposals and explanations, each becoming a separate unit and entering a separate entity. **The same idea was repeated in multiple entities**, and the retention rate was only 46–66%.
- **Difficulty six: Extract the agent's knowledge content or traces of the user's decisions?** Option A (extract everything, enabling retrieval in one hit) and option B (extract only user decisions and task evolution for the main structure, attaching agent content to tasks as evidence).
  → **Decision B**, because users retrieve using their own wording ("why not use SwiftData"), which aligns with their decisions, and because it produces fewer entities.
  This choice continues to this day: executors receive the user's exact words, CTM records the user's requirements and decisions, and executors' replies serve only as progress and evidence.
  But when B was run on a large session, "user system" and "frontend UI optimization" were merged into the same goal—extraction after reading the entire conversation at once tends to merge greedily, with no opportunity for reflection.

**V3 (Option C): The tree is the basic unit of retrieval.**
- **Difficulty seven: Both A and B treated the tree as a "byproduct of extraction".** After extraction, it was written to storage, but retrieval still searched text fragments; the tree itself was not used for retrieval.
  → **Decision**: Change the basic unit of memory to a Goal → Task subtree. Reason: conversations with coding agents are essentially about "what to do—how to do it—whether it worked"; only matching a subtree can provide the complete work context;
  the tree is both the extraction output and the retrieval unit, with no loss from translation; cross-session work does not start from zero, but attaches the new session to the existing forest. Extraction was split into two layers:
  the first produced only atomic units, and the second decided how the tree should change, with additional multi-turn review—when a single layer did both, the model often referenced IDs that did not yet exist.
  The related work compared at the time (MemTree inserts into a tree at write time but flattens it at retrieval, RAPTOR flattens at retrieval, A-MEM operates on flat notes, Confucius Code Agent has no goal forest, etc.) did not have the combination of
  "iterative correction of goal boundaries ＋ retrieval by tree structure ＋ cross-session grafting".
- **Difficulty eight: Where exactly is the value?** The user clarified that a session's own context window can solve many needs to "continue from earlier". There were only two narrow, irreplaceable scenarios:
  **cross-session injection** (other projects, sessions from weeks ago) and **compensation for compression loss** (decisions lost when an agent automatically compresses history).
  → **Decision**: Penalize same-session hits and reward cross-session hits during retrieval. CTM v2 later took this to its logical conclusion: there are no longer sessions, and all executions get context from CTM's memory.
- **Difficulty nine: The retrieval architecture was rewritten three times in quick succession.** Each time was due to a misunderstanding of the user's intent: first, the assumption was that the LLM loop was on the caller's side; the user corrected this to "the LLM makes its own decisions over multiple turns inside retrieval, and the caller makes only one call";
  then vectors were used to cluster nodes into groups, and the user pointed out that "similar nodes in different contexts may represent completely different things and cannot be clustered this way".
  → **Decision**: Form branches according to tree structure (a hit node plus its parent, siblings, and children, with natural merging when they share a parent), **hits concentrated in the same subtree ＝ high confidence**;
  different branches are genuinely different work, each presented as a candidate, not merged into one answer. This was the first explicit statement of "structure before similarity", which later reappeared in CTM's candidate selection (Section 4.4) and
  its rejection of "supplementing related work by similarity" (Section 5.3).
- **Difficulty ten: There was no suitable benchmark.** LoCoMo, LongMemEval, and MemoryAgentBench all test fact recall from long casual conversations; a trial run on LoCoMo scored 10% (GPT-4 with full context scored about 68%),
  because the system absorbed specific events and dates into higher-level tasks, losing "what was done when". SWE-Bench-Pro consists of isolated cross-repository tasks, obscuring the value of cross-session work.
  → **Decision**: Do not force the use of public benchmarks; build evaluations from real sessions. This choice continued, but it also made "what to compare against" a long-term problem, until the later decision to "compare against full history and a flat baseline".
- **Difficulty eleven: Fragmentation.** One agent reply was split into multiple parts by activity label, each becoming an entity. The same task scattered into many similar nodes in the graph, competing with one another during retrieval;
  reading 30 files at once produced 30 edges, flooding the graph. → **Decision**: Use "between two user messages" as the minimum unit; have the parser determine how to truncate long replies (the beginning plus an ending excerpt that grows with length), rather than leaving it to the model.
  The judgment that "conclusions are usually at the end" is still used today (the executor's reply in context includes the final 1500 characters), and analysis on 2026-11-20 found that it was precisely the cause of some missing details.

### 1.3 What remained

The task tree and the distinction between Goal and Task, valid time and replacement, meta-signals computed by code, using the user’s decisions as the backbone, self-built evaluation, and “structure before similarity.”
Also remaining were problems unresolved at the time: how to merge the same Goal across sessions, how to mark tasks unfinished at the end of a session, and how to express partial expiration after a constraint is lifted from the project level to the global level—
these later became merging during maintenance, task status and lifecycle, and constraint placement levels and replacement, respectively.

Some rules from that time were later overturned: “write all prompts in English” (current prompts are in Chinese); “do not run tasks involving LLMs in parallel” (now they run in parallel within limits); “do not write unit tests” (now every mechanism has offline tests).

## 2. Stage two: Independent research project (from 2026-10-01)

### 2.1 Two corrections at the start (10-01)

- **Research focus.** The user clarified: the most useful thing is **tree-structured context organization and fast branch location**, so that an agent does not have to carry and reprocess all history; overlap with the features of general-purpose memory products is not a reason to stop.
  Closer existing work was listed again: dynamic discourse trees, evidence hierarchies, subgoal working memory, context folding, and programmatic access to external context.
- **Evaluation.** Early model screening looked only at final retrieval results and simple format and keyword checks. The user required **each step to be evaluated separately, because each step has different goals and error costs**.
  The screening at the time used 15 controlled cases covering 7 model steps and 120 serial requests. This was the precursor to “block-by-block evaluation,” but it was then set aside for several months, until it returned in a stricter form in November.
- **Structure.** When it became an independent repository, it was split at the user’s request: one directory for each algorithm step (with separate processing logic, execution entry points, and evaluation), with shared model calls, storage, and paths placed elsewhere;
  the original retrieval process was split into indexing, recall, branch formation, selection, and assembly. Reading conversation records was made into a read-only source layer (Claude, Copilot CLI, VS Code).

### 2.2 How the deviation happened

The goal was clearly stated: reduce the history the execution agent needs to read and reconstruct at a fixed level of quality; the three layers are organization, selection, and runtime use; it must be compared with a strong flat baseline, and “the tree is a hypothesis, not an axiom.”
But the research that followed gradually moved away from it:

| Stage | What was actually done | Relation to the goal |
|---|---|---|
| Research rounds 0001–0042 | Replay experiments, unified controller, typed context, time and source fidelity, requested work, incremental organization, resource references, location and context methods | Largely aligned, small in scale |
| 0043–0109 | Minimal working memory, time, fulfillment scope, address compilation, shared memory index; 0108–0109 merged into a single mainline process | Gradually shifted from “select accurately, use less” to “whether semantic expression is completely correct” |
| Research loops 05–23 | Each round added a semantic mechanism (objects, materials, requests, constraints, evidence reinterpretation, fulfillment……), with tests growing from 410 to 632 | Each round used only 2–7 conversations to show that the mechanism worked; never tested whether context became smaller or continuation became better |
| Concept phase | Paused coding and supplemented definitions for historical excerpts one by one: bridging, dependencies, premises, impact, use rebinding…… | Every historical detail became a new distinction or formula |
| Macro phase | Reorganized into three responsibilities, progressing by “number of archives read and covered,” with thousands of interpretations per batch and about 3500 calls | Measured breadth of reading; the last five batches all found “no new structural counterexamples” |

**Why this happened.** Each step looked reasonable in isolation: when a counterexample appeared, add a distinction to explain it; as distinctions accumulated, more history was needed to test them; the more they were tested, the more complete they seemed.
But “whether the semantics are completely correct” and “how much was read” are easy to measure, while “whether context is smaller at equal quality” requires execution and comparison and is hard to measure—so the former quietly replaced the latter,
efficiency and cost were explicitly downgraded to “not a threshold,” and were no longer measured. The selection layer was neglected instead: global navigation consisted only of the first 32 items under root, only the full text of the first 4 candidates was read, and there were no subtree overviews or metrics for branch recall and rejection.

### 2.3 Direction correction (2026-10-12)

The user pointed out that many recent rounds of fine-grained improvements had seriously deviated from the initial goal. The corrected positioning was **a task tree context manager running in real time**: its value must be demonstrated by smaller context, more accurate location, acceptable cost, and continuation across sessions,
without reducing execution quality. Measurement returned to four items: Q quality, C tokens, S location and selection, and M maintenance cost, with comparison against a flat baseline.
With HiAgent as a reference (organizing working memory by goals and subgoals, summarizing upon completion, and restoring on demand), our extension was global location across sessions, multiple Goals, and multiple Tasks.

**Lesson retained** (written into section 4 of the goals and methods): research loops without measurable goals turn every counterexample into a new qualification, appearing to make progress while actually deviating from the goal.
This lesson later took concrete form as several work rules: improvements must show benefits on data not used to find errors, and must be explainable in terms of use and cost; adding a rule for a single error case does not count as an improvement;
a prompt is not a list of rules.

## 3. Stage three: CTM concept model v1—the invisible assistant (mid-October)

### 3.1 Understanding at the time

After the correction, the first question was “where does this manager sit at runtime?” The v1 answer: **CTM is like an assistant helping the user control agents**, with memory as a work–knowledge graph stored in a vector-searchable database;
there are only two inputs—the user’s message and CTM’s own memory, **no session, no client clues**; “what we just discussed,” “that file,” and “the previous plan” all rely on memory for resolution.
The flow is: extract → locate in memory → understand again → assemble the entire context in sections → dispatch → write back. Value ranked by confidence: deliver the interaction mode for this turn → recover long-term state → compress context.

### 3.2 Facts from the pilots

- **Most course-correction errors are immediate behavior judgments, not memory failures**; long-term state, however, clearly depends on memory (pilot 01). This means a memory system can improve only some errors; it cannot be expected to solve the executor’s own judgment problems.
- **Time weighting significantly improved location without sessions**; explicitly determining “continuation, switch, new work, unrelated” improved identification of new work (validation 01). These two points carried forward into current delivery inputs (work from recent exchanges, time references) and destination categories.
- **Feeding all memory to the executor causes disruption**, especially when expired or overly broad constraints lead to excessive restriction; supplementing strictly as needed can avoid disruption (validation 02). This directly determined the later organization of context:
  assemble it by tree paths, siblings, and references, rather than hand over whole passages of memory by relevance.
- Testing directly with history within a session produces conclusions biased toward the recent window (a limitation of validation 02, pointed out by the user). This meant later test data had to match the target scenario of “one assistant, parallel work, no session.”

### 3.3 Why It Did Not Stop at v1

There is no dedicated discussion in the original records; the following is inferred backward from what was added in v2. v1 placed CTM where the user could not see it: the user did not know where messages were sent or what CTM recorded, and thus had no way to correct it; nobody took over the executor's round-trips (stopping mid-way to ask questions, saying it was done, exceeding authorization);
when the user wanted to ask "what was decided before", there was no entity to answer. Furthermore, "no sessions, relying entirely on memory" was too idealistic in real work: the user's words heavily depended on content that had just been displayed.

## 4. Phase 4: CTM Concept Model v2 and ctm2 Implementation (Late October to Mid-November)

### 4.1 Core Choices of v2

**CTM is the single assistant between the user and the executors.** The user only talks to CTM; CTM uses the task tree and versioned documents as long-term memory, answers queries, dispatches and drives executors via the execution control layer,
and prepares a small and sufficient context for each execution. This choice brings out several interdependent rules, each aimed at solving a difficulty from earlier phases:

| Rule | Difficulty Solved |
|---|---|
| Only Goals under the root; Task and subtask are containment, sequential steps are siblings; organized by work and purpose, same object or topic does not equal same work | Tree mounted haphazardly by topic, greedy merging of goals (1.2 Difficulties 6, 9) |
| User's words and UI edits rank higher than CTM's inferences, inferences rank higher than maintenance; each item records time and replacer, only current ones are delivered | User has no way to correct (3.3); expired content still handed over |
| Executor gets the user's exact words, without relay, adding requirements, or tightening; unknown is neither completion nor failure; self-report is separated from verification | Distortion in relay; over-tightening (3.2); "completed" treated as fact |
| Long-term rules about an object stay with the object (`ctm.md` under the directory or constraint comments), not with the task | Work modifying the same module under another Goal cannot see this rule |
| Every message from CTM to the user can be referenced: numbered, indicating the work it belongs to | References like "use the second plan" or "okay" (1.2 Difficulty 2) |
| Decide whether to ask first or act first based on reversibility; irreversible actions require explicit authorization | Executor pushing or deploying without permission |

### 4.2 Component-by-Component Implementation Failed, Changed to Mechanism-Chain Implementation

The first version of ctm2 was implemented component by component. Individual components seemed usable, but failed when combined: placement only "optionally" gave a parent node, CTM could not build upper levels, so the tree was flat, and passing constraints along the tree and folding results upward both lost their foundation;
replacement was only done for constraints, so outdated decisions, states, and environments were still handed over as current content; without displayed items and pending items, short approvals and "the second one" had nothing to land on.
→ **Choice**: Implement by mechanism chains (S0 memory storage → S1 understanding and write → S2 locating and placement → S3 lifecycle → S4 maintenance → S5 execution context → S6 execution round-trip and control → S7 documents → S8 query → S9 root layer and UI),
completing the interdependent parts on a chain in one step; at each step, evaluate the step's metrics, downstream impact, cost, and non-regression of previous steps. The implementation checklist was also changed from "writing the function counts as implemented" to "wiring it into the runtime flow counts as implemented".

The choice of storage layer continued from Phase 1: SQLite items, relations, and events, each with write time, occurrence time, validity interval and replacement, observation time, and source, allowing queries for the state "as of a certain time".

### 4.3 Several Revisions Brought by User Spot-Checks

- **Turn 3**: Tree mounting, constraint boundaries, and the relationship between sessions and queries had their standards set by user spot-checks—model annotations for such standards are unreliable (work granularity, parent-child edges, and replacement relations are inherently ambiguous).
- **Turns 4 and 5**: Research separated out (only collecting external information counts as research; asking about the project itself is a query, answered by forking the relevant task session); Agent behavior guidance separated out as documents, handed to the executor as an index to read on its own when needed;
  whether a subtask reuses the parent task's session or opens a new one—the trade-off is continuity of the scene versus context bloat.
- **Turn 6: Rewriting the prompts.** The user pointed out that spot-check questions cannot be put into prompts as examples: when answering the spot-checks, he recalled the situation at the time, and a single sentence by itself cannot determine the answer; moreover, these examples were taken from the same week's replay data,
  which previous turns had tuned on, amounting to training on the test set. → **Choice**: Prompts were changed to an analytical style—explaining who this judgment is for, the cost of each kind of mistake, and what to ask oneself, letting the model analyze relationships before deciding;
  no longer a checklist of rules. This was later written into the development rules: a rule added for a single error case will fail on the next example.

### 4.4 Turn 7: Fetching Candidates by "Pointing Method"

The original flow used multi-stage calls for understanding and locating, retrieving candidates via vector search of the entire message.
- **Difficulty**: The vector of the entire message mixed in phrasing and materials, often finding work that was merely similar in topic. On 339 messages (97 agreed items pointing to old work), the top 3/5/8 hit rates of whole-message vectors were 46%/50%/57%,
  while "object → work that touched it" achieved 86%/86%/93%.
- **Choice**: For each message, decide only two things—where the words are delivered and how, and what to record. One lightweight call finds the pointing method and objects → code fetches candidates from several routes according to the pointing method
  (recently visited work, current and running executors and pending items, object → objects in memory → work that touched it, time) → one delivery call decides → code assembles context → memory write is placed after dispatch.
  Semantic judgment uses only LLMs or vectors; when identifiers like paths, PR numbers, or branches are identical or differ only by a typo, they can be proposed as candidates—this is the only allowed literal matching, and the decision is still left to the model.
- **The few-steps principle** was established from this: mechanisms are put into the inputs and prompts of existing calls; judgments that are not needed every time serve as signals in the main call's output, making an extra call only when needed.

### 4.5 Model Selection

Measured and selected by role: pointing and objects, memory write, and the control layer use `gemini-3.8-flash`; delivery, progress summaries, and other tasks requiring comprehensive judgment use `gemini-4-argon`.
On 2026-11-03 the user decided not to use the sol series at all (the code rejects its model names). Evaluation annotators and judges must be independent of the tested models: `pi:loki/claude-opus-5.5` and `gpt-6.1-terra`, counting only agreed items between the two.

## 5. Phase 5: Pilot and Evaluation Methods (November)

### 5.1 Pilot

Local web page: task tree on the left, conversation with CTM in the middle, work page, queries, and execution on the right; the executor is a pi session driven via RPC (windowless child process).
So that the pilot trial has the user's work from the start, `bootstrap` batch-imports from recent months of session logs: collection → segmentation by session → cross-session merging of the same work → writing.
**Choice**: Import uses a batch method to produce the same structure as the real-time flow, rather than replaying item by item (which would take days). Cost (inferred, not specifically tested): the tree produced by import may not match the tree built by the real-time flow, which must be distinguished during evaluation.

### 5.2 Evaluation method: from spot checks to independent block evaluation

- **Difficulty one: spot checks cannot serve as the standard.** The user's answers during spot checks depended on the scene at the time; the same week's data was used for both tuning and testing. → The standard was changed to annotation for CTM scenes, with only agreed items between two independent judges counted;
  data rotation (one portion for diagnosis, unused data for testing); running the same configuration twice to estimate variation. Re-evaluating the same text showed variation of about 6 items, so smaller differences did not count.
- **Difficulty two: end-to-end replay cannot distinguish which block is at fault.** The first round of automatic evaluation on 2026-11-18 replayed real records, but a single metric was affected by multiple blocks, including delivery, memory, and context.
  → **Choice**: divide into 9 blocks by **judgment**, rather than by call or code (delivery, work relationships, memory write, execution context, result write-back, execution control, status, answering queries, relay),
  and evaluate each block independently using upstream reference inputs (annotations or frozen outputs); “If a block's evaluation must pass through other blocks to obtain a result, there is a problem with the block division.” End-to-end checks are used only to find problems.
- **Difficulty three: what counts as an improvement.** The user required that improvements show benefits on data not used to find errors, and that they be explainable in terms of use and cost; the content of the prompts came from “who reads the output, what they use it for, and how costly each kind of error is.”
  This ruled out many changes that were “effective on the diagnostic set.”
- An earlier approach was layered annotation evaluation (starting 10-28: three layers of material were organized from history, and the annotation rules were frozen after three rounds of spot checks by the user), later replaced by the independent block evaluation above;
  its plan, progress, annotation instructions, and the evaluation summary after block-by-block optimization across eight blocks on 11-10 were deleted on 2026-11-25. The conclusions for each block are in section 7 of the [implementation plan](ctm-implementation-plan.md) and in this section.

### 5.3 Several representative choices

- **Execution context: retrieval or tree.** Much of the information a new executor lacks comes from “other work.” One direct approach is to supplement it with related work based on similarity. The user rejected this: “If we are going to use retrieval, why are we building a tree at all?”—
  it bypassed the tree's relationships and also concealed missed judgments in the work relationships block. → The approach was changed to filling in relationships that should already be in the tree (new work specifies which work's conclusions it needs), with the rest handled by the executor asking CTM.
  Later analysis found that most omitted references were in fact siblings of the new work and would have been given to the executor anyway, so the real gap was much smaller than the apparent number.
- **Delivery instructions: make the use and cost clear.** If delivery incorrectly specifies the “previous step,” the executor treats an unrelated scene as the previous step and also waits for unrelated work; the cost of omitting it is small.
  After this use and these costs were written into the instructions, incorrect “previous step” entries fell from 15 to 1; likewise, after the two costs concerning “whose conclusions are needed” were made clear, correctly written references rose from 43 to 57.
- **Progress summaries: who they are written for.** Summaries are long-term records for later executors and the user. After the use and the costs of the two kinds of errors were specified, the proportion of information actually used later that was included in summaries rose from about 40% to 65–70%;
  in several subsequent versions, some filled in content absent from the reply (requiring completion), and some were no better (requiring evidence for every sentence). None were adopted.
- **Control layer: an analytical approach is not necessarily better.** Changing stop classification to an analytical approach made test results worse, so the original was retained—“analytical” is a principle, not something every prompt must be changed to follow.

## 6. Phase six: assembly walkthrough and real pilot trials (2026-11-20 to 11-23)

### 6.1 Meeting the standard for individual blocks does not mean the assembly is correct

After offline evaluation approached its limits, each of the 15 scenes in the concept model was walked through to check which blocks each scene passed through and whether interfaces between blocks were disconnected. Two disconnections were found:
- Items left for the user in executor replies never became numbered pending items—they were only displayed in the interface, and CTM itself did not know what “the second item” referred to. Delivery evaluation had always passed an empty display list, so this was never tested.
- Starting with V9, delivery instructions no longer selected “the most recent turns that this message follows.” From then on, an executor returning to the original session could not see what the user had just said in other work—when V6 was rejected, only new executors were evaluated; the reuse path was not evaluated.
**Lesson**: The blind spots in block evaluation are at the interfaces; when changing a block's output format, check every block that reads it.

### 6.2 Performance: what the user is waiting for

The time the user actually had to wait was measured item by item before deciding whether to switch models: after switching query routing and answering from memory to flash, accuracy stayed the same and waits were more than ten seconds shorter; after switching progress summaries to flash, coverage and credibility fell noticeably, so argon was retained;
delivery candidates carried only the latest result, with quality unchanged and input reduced by about 6.5%. There were also two sources of waste unrelated to the model: streaming reads were closed before completion, requiring a new handshake on every call (about 2 seconds per message);
vectors for answering from memory existed only in memory, so the first query after a restart had to recompute the entire Goal (about 100 seconds of extra waiting in a real pilot trial).

### 6.3 Real pilot trials exposed things offline evaluation could not see

A task to “add an available region to a service's configuration” went through end to end: creating work, executor questions, user answers, and, after authorization, committing and creating a PR. But:
- Memory recorded “add one region this time and reuse existing endpoints” as a **long-term object constraint** on the configuration file. The executor wrote `ctm.md` on that basis and committed it into the PR along with the other changes, forcing the user to correct it.
  This was a new form of “temporary statements treated as long-term decisions” from phase one (1.2 difficulty four): distinguishing “changes to be made this time” from “rules the object must follow from now on” remains a difficulty for memory write;
  and the design of placing `ctm.md` in the project directory allowed this error to enter the public repository directly.
- The user told CTM “remember globally: do not commit ctm.md.” This was delivered to the executor for the work in progress, and the executor went and changed its own global configuration file.
- The two issues had the same root: CTM had no action channel of its own (“CTM does not directly modify files”), so writing object rules was smuggled into the executor's input, and things said to CTM could only be delivered to the executor—
  CTM's own business and the user's work were mixed together. The correction was to separate their respective business: executors do only the user's work and receive only the user's original words; `ctm.md` is written by CTM itself and kept only on the local machine;
  comments that go into code are proposed by CTM and decided by the user; things said to CTM are recorded by CTM (concept 1.1, 3.5, 5.1).
- The second pilot trial after the above corrections (the afternoon of 11-24, a configuration task) produced the correct result, but added three rounds of back-and-forth and exposed two design problems:
  First, “adjust in url order this time” was mistakenly recorded as an object rule and immediately written into `ctm.md`; the next sentence limited it to adjusting only the newly added part, but memory write happened after dispatch, so the executor still read the old entry, judged it a conflict, and stopped. The file and the conversation are two separate paths, and an immediately following refinement within the same work always gets ahead of the file—the change was to write it only before an executor that needs to read it from the file starts.
  Second, “what it said is wrong, delete it” was a withdrawal, but memory could only add and replace: it was recorded as “rejected: delete this rule,” and then replaced a user requirement that was still valid. CTM subsequently answered on the user's behalf based on this, and what it relayed to the executor contradicted itself. A separate “withdrawal” category was tried for memory, but it was never used in evaluation (the extraction step cannot see entries already recorded), so it was not adopted; the prematurely written entry at the source was eliminated by delaying the write. When incorrectly matched replacements were retested in block 3, their general form was measured: when the user reiterated a misunderstood rule, the recorded “rejected: misunderstanding” replaced the rule, because the replacement step could see that the old entry was rejected but could not see that the new entry was rejected; after this was added, losses fell from 10→3.
- The execution view errored as soon as it had a real executor for the first time—the data used in offline tests and browser checks had never contained an executor.

## 7. Patterns in Decision-Making

1. **Structure takes priority over similarity.** This appeared three times (V3 branching by tree, selecting candidates by pointing method in the seventh turn, and vetoing the addition of related work based on similarity). Each time, it was because similar things do not necessarily belong to the same matter.
2. **The user's intent determines the design; misunderstanding is the main cause of rework.** The three rewrites of retrieval and the deviation in phase two all went far in locally reasonable directions without returning to the user's goal.
3. **Metrics that are easy to measure replace the goal.** Extraction coverage, semantic completeness, history read, and metrics for individual blocks were all at one point easier to measure than “whether context is smaller and execution is better.”
4. **Rules fix wrong cases; models make judgments.** Temporary word filtering, scoring formulas, and examples drawn from spot-check questions all failed on the next example; explaining the purpose and cost clearly and letting the model analyze first transferred better.
5. **The same difficulty returns in a different form.** Reference and acknowledgment (V1 → soft completion → numbered displayed items), temporary and long-term (temporary word filtering → incorrectly recorded object constraints), cross-session merging (entity merging → maintenance merging).
6. **When judgment is unreliable, change the cost of a wrong judgment, not the judgment.** Two versions of stricter instructions did not improve the distinction between object rules and the current change; changing its consequences to a local record plus a proposal for the user to decide made a wrong judgment cheaper. But the cost must be calculated according to when the error actually occurs: an incorrect record most often becomes apparent immediately when the user continues to refine the same change, so the write should be delayed until it is truly needed, letting later words correct it first.
7. **Each party does its own work.** Having the executor do CTM's own work along the way saved an action channel, but mixed CTM's records into the user's results and turned words addressed to CTM into work for the executor.

## 8. What Remains Unresolved

- How memory writes distinguish one-off changes from long-term rules: on 2026-11-24, two versions of revised instructions only reduced object constraints overall and did not improve the ability to distinguish them; the original version was retained because the costs of the two kinds of error are asymmetric.
  After the design correction, the cost of a wrong judgment is lower: `ctm.md` is written by CTM and kept only on the local machine; when a rule is replaced, CTM rewrites it directly. Comments that go into code require the user to respond to CTM's proposal.
  Too many proposals will become a burden on the user; the response rate must be observed in the pilot trial (`pilot.report`).
- When several steps of the same matter are spread across several items of work, who organizes the structure and when (maintenance has splitting and merging, which were rarely triggered in replay).
- Whether the executor follows constraints and writes back to documents, and the burden of user corrections—all can only be tested in real use. What the executor will do after receiving CTM's context (the loop of asking questions and filling gaps)
  cannot be tested by replay; a simulation environment was designed for this, with a real executor redoing historical tasks in a sandbox and a model playing the user (2026-11-20), but it was not run: the current phase has switched to block-by-block evaluation plus real use.
- Evaluation data was cleaned up along with the archive; subsequent evaluations must be prepared anew from records of real use.

## 9. What Is Retained After Cleanup

- Code: `src/context_tree/ctm2/` (mainline), `src/context_tree/pilot/` (pilot and import), `src/context_tree/common/` (model calls, credentials, data directory), `tools/auth.py`;
  tests `tests/test_ctm2_*.py`, `tests/test_pilot*.py`, `tests/test_auth.py`, `tests/browser_pilot_ui.py`.
- Design and method: [CTM Concept Model](ctm-concept-model.md), [Goals and Method](goals-and-method.md), [Implementation Plan](ctm-implementation-plan.md),
  [Block Interfaces](block-interfaces.md), [Block Plan and Results](blocks-3-6-plan.md), this document; see the [Documentation Index](README.md) for the other current documents.
- The original design and research and development logs from before 10-01 can still be retrieved from git commit `b3d83e1` (`docs/history/`).
