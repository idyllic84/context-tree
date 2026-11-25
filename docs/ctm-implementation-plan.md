# CTM Implementation Plan: Complete Implementation and Evaluation Against the Concept Model

> Based on: [CTM Concept Model](ctm-concept-model.md) (authoritative), [Goals and Method](goals-and-method.md).
> This document precedes the code: each step specifies which concept items it covers, what it depends on, what it affects, how it is evaluated (including its impact on subsequent steps), and what is explicitly deferred.
> See [CTM Implementation](ctm-implementation.md) for implementation status.

## Current Configuration (2026-11-12)

- Message flow: seventh round (pointing and objects → candidates → delivery → dispatch → memory). The first version of the flow (understanding→locating→placement→write-back), old versions of the module descriptions, and approaches that were not adopted were removed from the code on 2026-11-25. Evaluation records remain in this document and the block evaluation documents.
- English conversion (2026-11-25): Code, prompts, and pages were changed to English. Content written by the model for the user (titles, summaries, answers, memory entries) follows the user’s language. Regression checks (research/blk-en, original Chinese version versus English version, same input): for 112 messages in the delivery chain, the delivery method matched in 109, and both method and target matched in 108; two runs of the Chinese version itself matched in 105 (within the range of variation). For 80 memory extraction and replacement cases, both judges agreed that English was better in 13, Chinese was better in 12, and they were comparable in 37. For 40 stop classification cases, the handling matched in all 40. Progress summaries became worse after literal translation (both agreed Chinese was better in 12 and English in 3: the English version put unfinished things in done, and open was often empty). After rewriting the descriptions of open and verified according to the purpose of the two columns, on 40 unused cases Chinese was better in 5, English in 4, and they were comparable in 3; open was nonempty in 21 versus 22. Adopted. Maintenance, structure judgment, Goal organization, query routing, answering, and scope judgment were not tested separately; they are examined through records of actual use.
- Models (selected after measurement by role; see section 7, seventh round, for the basis): pointing and objects `gemini-3.8-flash`, delivery and all other calls `gemini-4-argon`, memory `gemini-3.8-flash` (extraction prompt V6—V5 plus what carries object constraints; object rules without a project directory stay on the work they belong to; replacement uses flash for focused comparison, comparison instructions V5: replace only when the old entry as a whole no longer holds), execution control layer `gemini-3.8-flash` (stop classification V2), memory-based answers to user questions and query routing `gemini-3.8-flash` (2026-11-20: equal answer accuracy and routing appropriateness, shorter wait), delivery candidates carry only the most recent result (`deliver.CAND_RESULTS`, 2026-11-20: equal quality, 6.5% less input), progress summary `gemini-4-argon` (instructions V4: state the purpose of the summary and the cost of the two kinds of errors, and analyze what to select from the reply; when waiting on a conditional dependency, also judge the condition), maintenance instructions V11 (analytical; state the purpose, cost, and basis of status judgments, and separately list work that has been inactive for a long time but is still in progress), delivery instructions V17 (V15 plus the `memory` destination: memory operations on CTM and adjustments to CTM’s own practices are not delivered to the executor, 11-24; V15 is V13 plus: the purpose of the previous step’s `after` and the cost of writing it incorrectly or omitting it; state the cost of the two kinds of errors in referencing `uses` as they are; V13 is V11 plus the meaning of the current task: selecting it on the tree switches to it, and selection is more reliable than inference from the most recent turn; V11 is V5’s analytical approach plus: new work references recent queries it will use; new work specifies work or research elsewhere that it will use (`uses`, cross-task references); the consequences of side questions and sending into work, and the cost of judging incorrectly for each; when unsure, treat it as a side question; the most recent results of candidate work include failures and verification status), Goal judgment V5 (argon, analytical; work at the root that is not under a Goal), structure judgment V6 (argon, analytical; group under a Goal or Task by containment, triggered by a delivery signal and by a level where ≥2 items of work have been added during maintenance), new executor context includes the original text of the last 6 turns of conversation, with the resolution of more distant parts reduced according to budget when exceeding 32,000 characters (formerly 24,000); turns whose original text is included in full no longer repeat their progress summaries (concept 3.2); siblings are provided according to concept 5.2 (original text of the last 4 turns for the most recent sibling, 2 turns for the rest, with environment and questions asked); when new work is created, it references sibling constraints that CTM judges also apply to it. Query: retrieve the top 20 records from the entire work line containing the work that raised the question; when a replaced entry is retrieved, include the current entry that replaced it (`recall`).
- CTM does not use the sol series (`common.llm.chat` and `ctm2.model` reject its model names); when sol is used as a judge in an evaluation at the user’s request, set `CONTEXT_TREE_ALLOW_SOL_JUDGE=1` only for that run.
  Models callable only through a pi provider are written as `pi:<provider>/<model>` (windowless subprocess, without tools, session, or context files).
- Evaluation: test every change on unused data (`rotate.py`); annotators and judges are independent of the model under test; no single run exceeds 30 minutes.

## 0. Why This Plan Is Needed

Previously, components were implemented one by one, splitting mechanisms that cooperate in the concept model. Individual components appeared usable, but failed when combined:

| Missing cooperation | Consequence |
|---|---|
| Placement only “optionally” assigns a parent node; CTM cannot create a higher-level node; maintenance only looks at the node list | The tree is flat or nodes are attached haphazardly by topic → task constraints passing along the tree, recent exchanges along the work line, and results folding upward all lose their foundation |
| Replacement applies only to constraints, not decisions, status, or environment; rejected approaches are not linked to replacement approaches | Outdated statements are still provided as current content |
| Understanding excludes environmental facts from constraints, with no task environment, progress markers, or knowledge documents to store them | The most common gap in execution context is missing facts |
| No task status or lifecycle | The positioning signal of a “running executor,” passing prerequisite results to successors, and folding on completion cannot be implemented |
| No artifacts or pending items | References in “Yes, start” and “Change it according to the second point,” and approvals becoming decisions, cannot be put into practice |

**Rules**:
1. Implement by mechanism chain. Complete the interdependent parts of one chain in a single step; do not leave half a mechanism to “fill in later.” Where deferral is truly necessary, specify what is deferred, which mechanisms will fail without it, and how its effects will be isolated in evaluation.
2. Each step’s evaluation includes four items: metrics for this step; impact on downstream steps (measured with fixed downstream probes); cost; and no regression in previous steps.
3. Where reference answers are unreliable (work granularity, parent-child edges, replacement relationships), the user sets the standard through spot checks, rather than relying solely on model annotation.

## 1. Mechanism chains: what affects what

| Chain | Mechanisms involved | Downstream consequences of an error at one point |
|---|---|---|
| L1 Placement and propagation | Understanding → pointing → placement (service relationship) → task constraints propagate along the path → constraints and work thread in execution context → execution | Incorrect attachment: constraints from elsewhere propagate in and cause over-restriction, or required constraints, prerequisite results, or original exchange text are missing |
| L2 Writes and currency | Understanding → writes of constraints / decisions / rejected approaches / environment / progress → comparison and replacement at write time → execution context and queries use only current entries | Outdated entries are treated as current; rejected approaches are repeated |
| L3 Lifecycle | Task status events → signals from the current task and running executors → pointing; completion → fold upward → parent task progress → context for successors | Completed tasks are still treated as in progress; successors cannot obtain prerequisite results |
| L4 Execution round trip | Execution contract → executor → execution control layer stop classification → CTM answers using memory or turns the matter into a pending item → user | All stops are escalated to the user, creating a heavy burden; or CTM answers with outdated content |
| L5 Queries and tasks | Understanding's query / task determination → whether to create a node → tree noise and granularity; query record → later references | Creating nodes for queries fragments the tree; query results are lost, leaving no basis when turning to a task |
| L6 Display and reference | Numbered items and pending items in relay → user's short references → write (approval becomes a decision, rejection becomes a rejected approach) | Approval cannot be attached to a specific item, so the decision is missing |
| L7 Maintenance | Written message segments and progress → maintenance reattaches, creates parents, and merges → constraint propagation and work threads change accordingly | Changes in the scope of constraint propagation after reattachment are not checked, causing new over-restriction |
| L8 Knowledge | Executors' long-form content and approaches → documents (purpose descriptions, verified and unverified content, versions) → document index in execution context and query answers | Approaches and facts exist only in old sessions, so new executors lack facts |
| L9 Root level | Understanding of the user, global preferences and constraints, common environments → understanding, pointing, execution | Ambiguous messages are misunderstood; global constraints are omitted or propagated incorrectly |

## 2. User requirements, concept entries, and implementation comparison

Rewritten on 2026-11-12 (the previous version was removed during archive cleanup; see [evolution](evolution.md): it counted mechanisms written only as functions and not connected to the runtime flow as implemented,
and did not have an item for “reviewing the existing structure”). Each item lists: the concept provision, requirements stated by the user (date), code connected to the runtime flow (functions that are written but not called do not count), and evaluation.
Status: ✓ connected and evaluated; ◐ connected but not fully evaluated or only partly implemented (specified); not applicable = a design trade-off. Evaluation: T = offline tests (`tests/`); A–G = respective blocks (Section 7); smoke test = checks of the pilot interface on copies of real data.

| Concept entry | User requirements | Implementation (in runtime flow) | Evaluation | Status |
|---|---|---|---|---|
| 1.2 Conversation: recent window, numbered display and pending items, @ references, current task | 10-28: one conversation between the user and CTM | `pipeline`, `relay`; conversation area on the pilot page; matters left to the user in replies become numbered pending items (`OPEN_ITEMS`, added 11-20: previously only stops escalated by the execution control layer had them) | T; `blk3pending` (memory of decisions on items listed in responses 62→66/75) | ✓ |
| 1.2 Task tree: on the left, collapsed by default, expanding only tasks being executed and current work; rename, move, merge, split, create, change status, stop, reattach and redirect messages, approve proposals | 11-12: tree on the left, collapsed by default; 11-13: no floating toolbar on the tree, design interactions according to UI best practices | `pilot/static/index.html`, `Pilot._ui`, `ctm2.ui` | T (`test_pilot`, `test_pilot_dirs`); browser check `tests/browser_pilot_ui.py` (24 items, Edge) | ◐ |
| 1.2 Execution view, query panel, document browsing (node pages, exchange records, documents and versions, editing; entries on the root) | 10-28: display the task tree, execution, and query results separately | `Pilot._view`, `views`, `query.panel`, `execution.execution_view`, `ui.edit_document`, `ui.edit_root_item` | Smoke test | ◐ (document↔task links are only one-way) |
| 1.1 Each handles its own affairs: executors do only the user's work and receive only the user's original words and context; CTM handles its own affairs and words addressed to CTM | 11-24 | CTM's affairs are no longer included in executor input (`_object_writes`, `_retract_replaced_object_rules`, `_ctm_md_draft` have been deleted); for `ctm.md` see 3.5; for words addressed to CTM see the “remember” destination in 5.1 | T; block 1 (none of 99 work messages misclassified) | ◐ (imported old object constraints are not backfilled; proposal burden remains to be examined in the pilot trial) |
| 3.1 Nodes and edges | — | `store` | T | ◐ (no Resource or “object→contains→file”) |
| 3.2 Select resolution by budget | — | `context.initial_context`: when exceeding 32,000 characters (since 11-19, originally 24,000; after progress summary V4 grew longer, 24,000 would first cut original sibling exchange text, see [blocks 3–6 plan](blocks-3-6-plan.md)), successively reduce sibling exchanges, recent conversation turns, this task's exchanges, siblings to titles, and the number of recent turns | Block D (w2/w3/t1: no loss at 24,000, decline on t1 at 16,000) | ◐ (few labeled large contexts) |
| 3.3 Root: persona, understanding of the user, overall goal, preferences, environment | — | `root`, `writeback`, `maintain_store`; editable on the page | T | ✓ |
| 3.4 Criteria, research entries, attach new work under the work it belongs to | 10-31: research, queries, subtasks | `deliver`, `pipeline` | Block A | ✓ |
| 3.4 Only Goals under the root (long-term goals, with sources marked for those summarized by CTM); Tasks under Goals, subtasks by containment; wrapping up is continuation | 11-12: the top level is Goals; cleanup is not a goal; Goals are long-term goals, and future tasks for the same purpose continue to be attached under them; split subtasks as appropriate | Delivery `PROMPT_V4` provides Goals; `maintain_store.assign_goals` (`GOALS_V4`) handles work under the root but not under a Goal (delivery did not provide one, maintenance, imports); imports repartition work according to “wrapping up counts as continuation, parent＝containment” | goals_eval (three monthly windows, agreement with the annotation's partitioning is for reference only), block A earlyg | ◐ (evaluation of structure by consequences not done, see Section 7) |
| 3.4 Group under the same parent: consider when creating, periodically review the existing structure | 10-27: the tree structure needs periodic correction; 10-30: every time a new task is created, consider whether the last few tasks are subtasks of one task; the tree is dynamic | Delivery `PROMPT_V3`'s `same_work_as` signal and “next step of work under the root”→`maintain_store.structure` (V5); maintenance calls the same judgment for levels with ≥2 newly added work items (`changed_levels`); post-import organization uses the same judgment | blockS (two datasets), block A early, block C w4/w5 | ✓ |
| 3.4 Task source: planner (proposals, approval, authorized direct execution, gating) | 10-27: subtasks may also be split by an agent called by CTM | `planner`, `pipeline.planned_steps`; planner enabled in the pilot, approval available in the conversation and tree | T (`test_ctm2_planner_flow`) | ◐ (planning explanations not evaluated) |
| 3.4 Branches opened by executors | 10-27 | The execution control layer passes “steps or options outside the contract” to CTM as pending items; after the user agrees, delivery creates them as new work (no proposal node is created first) | Block E (stop classification) | ◐ (path differs from the concept, see 5.2) |
| 3.4 Status and relationships; prerequisites→executable; conditional dependencies judged together by the progress summary | 10-30: sequential items are siblings, parent-child means containment | `lifecycle`, `progress.CONDITIONS`, `pipeline._conditions_waiting` | T; automatic evaluation; reference input | ◐ (conditional judgments not evaluated. Completion judgment: changed to maintenance V11 on 11-18; on 11-20, 63 of 73 items on which two people agreed in the reference input were judged correctly (86%), see [blocks 3–6 plan](blocks-3-6-plan.md); the meaning of “reported complete” changed to “complete (based only on the executor's report)”) |
| 3.4 Judge parent task completion as needed | 10-30: judge whether all subtasks are complete only when explicitly needed | `lifecycle.is_done` (dependencies), maintenance status correction, parents created by structure judgment inferred from child work | R | ◐ (the model judgment in `parent_completion` is not connected: across all replays, there were 0 cases where “all subtasks had ended but the parent remained open,” so it is not needed now) |
| 3.4 Inform executors of changes to inherited constraints after tree adjustments | — | UI: `ui._notify_runs`; maintenance and structure judgment: `maintain_store._notify_inheritance` | T | ✓ |
| 3.5 Task constraints: placement, deeper and newer take precedence, exceptions, lift and fallback | 10-28: the tree structure is for propagating constraints at each level; 10-30: move shared constraints up to higher levels, up to the top level | `remember`, `scope`, `maintain_store`; `scope.inherit_for_new_work` when new work is created | Blocks B and C; automatic evaluation (`cons`, `cover`) | ◐ (`scope.check`, which lifts “the same requirement as elsewhere,” has not been called since it changed to v2, so maintenance rarely lifts constraints; requirements for the whole matter are recorded on the item where they were stated, and siblings added later do not receive them—on 11-18, judgment of whether sibling constraints also apply when new work is created, with applicable ones referenced to it, was made the default) |
| 3.5 Object constraints: CTM writes `ctm.md` itself (kept local only), before an executor that needs to read it from a file starts; source comments are proposed by CTM and handed to the executor after the user responds; when a rule is replaced or withdrawn, CTM deletes the entry, withdraws unanswered proposals, and proposes updating comments when necessary | 10-28: object constraints apply to that object; 11-23: `ctm.md` is not committed; 11-24: CTM does its own work, comments are proposed by CTM; 11-24: writing happens too early (real pilot trial) | `documents.index_object_constraint` (only creates an object index)→`objectfiles.sync`: before dispatch (`pipeline.dispatch`, `need`), writes entries due for this executor (another work item or new session enters the directory; entries whose owning work has ended or which belong to no work are written at every sync), `keep_local` adds to `.git/info/exclude`, generates `propose_annotation` pending items; after every message and reply, deletes replaced or withdrawn entries (deletes the file if only the header remains), withdraws unanswered proposals (page marks them “withdrawn”); forwarding includes replacements and withdrawals of object rules for that directory (`context._gone`); `pipeline._answered_proposal`/`_proposal_section` attach proposals the user has responded to for the executor of that work; pilot uses `write_object_files=True`, offline does not write; `Pilot._keep_ctm_md_local` is a fallback for `ctm.md` still written by an executor | T (`test_rules_reach_ctm_md_when_another_executor_needs_them`, `test_a_rule_refined_in_its_own_work_never_reaches_the_file`, `test_answered_proposals_reach_the_executor_and_replaced_entries_leave`, `test_a_rule_the_user_drops_leaves_ctm_md`, `test_ctm_md_written_by_an_executor_stays_local`) | ◐ (proposal response rate and burden need to be examined in the pilot trial; imported old object constraints are not backfilled) |
| 3.5 Draft `ctm.md` entries | — | Removed (previously included with the project's first executor, violating “each handles its own affairs”); if implemented, CTM should read the project description itself | — | Not done |
| 3.5 Escalate when constraint comments are deleted or changed; migrate them when objects are refactored | — | `execution.constraint_tamper`＋`Pilot._removed_lines` (lines before and after changes by the edit tool); migration is written into fixed clauses | T | ◐ (cannot see whole-file rewrites or command changes; migration not evaluated) |
| 3.6 Decisions: replacement, cross-task references, pending revalidation | — | `remember`, `lifecycle`; delivery V9's `uses` | Block B | ◐ (cross-task references were previously established only by queries and time references, never when new work built on research or conclusions elsewhere; delivery V9 adds this, evaluation in progress) |
| 3.6 Documents: types, versions, by section, outdated | — | `documents`, `writeback` | T | ✓ |
| 3.6 Behavior guidance: documents with “when to use,” indexed for executors to read themselves when needed | — | Memory extracts behavior in one step, `file_behavior` files it as a document; documents are exported to `behavior/<id>.md` under the CTM directory, with paths in the index; also extracted on import | T (`test_ctm2_behavior`); classification (behavior guidance / guidance / global constraints) not evaluated | ◐ |
| 3.6 Executors update knowledge documents, one writer per document | — | CTM now writes to documents from replies in a single work thread (long content saved as documents, research conclusions appended); executors do not directly modify CTM's documents, so no writer lock is needed | T | ◐ (differs from concept 3.6, “executor selects documents to update”) |
| 3.6 One modifier per working directory | — | `Pilot._busy_in`: modification requests for the same directory are queued and explained in the conversation; read-only requests are not queued | T | ✓ |
| 4 Resolve references to a specific attempt | — | Pointing calls provide time references→`context.attempts_text` lists previous executions of this work, and the executor judges from the original words | T | ◐ (executor's judgment not evaluated) |
| 4 Recording, replacement, time weighting | — | `store`, `remember`, `candidates`; in the replacement step, new entries as well as old entries are marked as rejected or questioned (`remember.POLARITY`, 11-24) | Block B; block 3 retest (`research/blk3rep`, `blk3pol`: lost 10→3, missed judgments 5→8) | ◐ (replacing a whole entry when only part changes, and replacement rules for questioned entries, still occur) |
| 4 Retraction: the user says a recorded entry is wrong or no longer needed, without providing a new one | 11-24 (real pilot trial: recorded as “rejected: delete this rule” and replaced a valid requirement) | Record it as a rejection, and invalidate the old entry in the replacement step (default `PROMPT_V6`＋`REPLACE_V5`); `PROMPT_V12`＋`REPLACE_V6`, which makes withdrawal a separate category, was not adopted and is retained for comparison (the `withdrawal` path in `remember.write` is used only when V12 is selected); `ctm.md` entries are deleted upon replacement | T (`test_a_rule_the_user_drops_leaves_ctm_md`); block 3 (`research/blk3wd`): on 22 retraction-type messages, 0 new entries distorted the original meaning and 0 invalidations were missed (two people agreed) | ◐ (the replacement step has been retested and corrected: new entries are marked as rejected, see the previous row and blocks 3–6 plan) |
| 5.1 Pointing and objects→candidates→delivery→dispatch→memory | — | `pipeline.on_message2` | Blocks A and B | ✓ |
| 5.1 Delivery: words addressed only to CTM (remembering, adjusting future approaches) are not delivered to executors | 11-24: “remember globally” should not be handed to the executor | `deliver.PROMPT_V17` (`memory` destination); `pipeline` attaches the segment to the work it concerns or to the root, does not dispatch it, and records it in step 5; the pilot routing line says “CTM records it itself, does not hand it to the executor” | T (`test_words_to_ctm_itself_are_recorded_not_dispatched`); block 1: 0 of 99 unused work messages misclassified as “remember” (also 0 with V15); real memory operations are extremely rare (only the sentence that triggered the issue in all historical messages, judged correctly by V17, delivered to the executor by V15) | ◐ (benefits can only be seen in the pilot trial: destinations and redirections in the report) |
| 5.2 Lifecycle, initial context (path, siblings, last 6 conversation turns), content forwarded to a session | 11-18: splitting into new work is fine, but both parent and siblings must be included when assembling context | `execution`, `context` | Block D; automatic evaluation (paired reconstruction) | ◐ (previously siblings were given only 2 turns, replies were truncated to 800 characters, and all were removed when the budget was tight; siblings' environments and questions asked were not provided—this did not match the concept, and was completed according to the concept and made the default on 11-18; subsequently, when using the original session, the recent turns named by delivery were forwarded, but this was not adopted along with V6; 11-20: starting with delivery V9, turns are no longer named, and reused sessions instead receive, through code, turns from other work since their previous turn (`FORWARD_BETWEEN`); relevant queries answered using memory are also forwarded (concept S3)) |
| 5.2 Execution control layer: stop classification, formal completion | — | `control`, `pipeline.on_reply` | Block E | ✓ |
| 5.2 Execution control layer: consecutive continuations without progress, total count, repeated errors | — | `execution.budget_check`: no tool call between two continuations is recorded as no progress (observation, not judgment), stop after 3; stop after 10 since the user last spoke | T | ✓ (the previous check was reset by the progress summary each time and never triggered) |
| 5.2 Milestones | — | Pilot: when a turn exceeds 10 minutes, the executor's earlier original words are recorded as interim progress (no separate model call) | T | ◐ |
| 5.3 Queries: read-only execution, memory answers only what has been recorded | 10-31: fork session for queries | `query`, `pipeline` | Block G | ✓ |
| 5.4 Only matters requiring a decision, blockers, completion, and deviations from expectations enter the conversation | — | Pilot branches according to execution control layer results: automatic continuations are not relayed, interim progress appears only on the tree | Block E | ✓ |
| 5.5 Propagation of UI changes in four aspects | — | `ui` | T | ✓ |
| 5.6 Maintenance: merge, parent-child and sequence, reattach messages, split, lift constraints, status, rename, attach research to the tree, understanding entries | — | `maintain_store` (V6) | Block C | ✓ (9/23 status changes by V6 itself were judged unreasonable in one run, pending investigation) |
| 5.6 Organize documents, migrate comments when objects are refactored | — | Maintenance only provides organization suggestions; migration is handed to the executor | — | ◐ |
| 5.2 Working directory determined by CTM | 11-11: do not use `--workdir` | `pipeline._workdir_for_new` | Real model pilot trial | ✓ |
| S10 External changes | — | `Pilot._observe_outside_changes`: when a known file is changed and no executor is working in that directory at the time, record it as the user's version and notify relevant executors | T | ◐ (only looks at files known to CTM) |

Judgments still made in code (all bookkeeping or mechanical rules, not semantic judgments; change them if errors arise during the pilot trial): For a new work item's working directory, first look at paths stated in the message, then at the parent or previous step's directory, and only then have the model decide; perform another structure judgment only when ≥2 work items have been added to a level; attribute external changes according to whether an executor was working in that directory at the time; the order of budget degradation; maintenance once every 12 hours.
Not yet covered by evaluation: executor behavior (whether constraints are written correctly, whether the right execution is found from the exact words, proposed `ctm.md` entries, migration comments), planning explanations, and actual use of the interface—these depend on the pilot trial.

## 3. Implementation Steps

For each step, specify: coverage, output, dependencies, downstream impact, evaluation (this step / downstream / cost / user spot checks), and deferrals.
The downstream probes are fixed as three groups, run at the end of every step (only the affected parts):
- **P-loc**: The checked cross-task, stay, and new work decision points from three weeks of material (E2), plus pairwise precision and recall for work threads (E4).
- **P-exec**: 80 execution decision points (50 from E5 + 30 from repeatedly evolving work threads), with the executor writing only a plan, followed by two anonymous reviews; record the number correct and error categories (over-tightening, retaining an overturned understanding, missing facts, etc.).
- **P-cost**: Number of calls and tokens per message, dispatch, and maintenance run.

### S0 Memory Storage

- **Coverage**: All nodes and edges in 3.1 (Turn, Segment, Display, Query, Run, Document, object, FileVersion, Resource; dep, about, serves, produced, involves, uses, supersedes),
  times for all nodes and edges (occurrence, learning, validity interval, observation time) and their sources; the working directory field in 3.6; the “task exchange record” needed by the page in 3.7 can be generated from Segment.
- **Output**: Replayable storage (SQLite), with versioning; all tree operations go through storage, and the in-memory tree is only a view.
- **Downstream impact**: The data foundation for all steps. Without Segment storage, maintenance (S4) can only see node summaries; without Run, progress, trace priority, and file versions have nowhere to attach.
- **Evaluation**: Replay three weeks of material with writes only, without judgments (using existing understanding outputs); check that every message and reply has a corresponding record and can be retrieved by node, time, and source; no model calls are needed.
- **Deferred**: Derivation at L0–L3 resolution (S5 makes the selection at delivery).

### S1 Understanding and Writing

- **Coverage**: The understanding portion of step 1 and all of step 2 in 5.1; the types and **placement levels** of the two kinds of constraints in 3.5 (“from now on” and “all” go higher; when unsure, place lower), and signals that a local constraint should trigger splitting into subtasks;
  decisions in 3.6 (approved, selected, rejected); attitudes toward displayed entries and execution results are attached to specific entries (requires the displayed items from S6; before S6, handle only attitudes toward the previous reply);
  store long material as documents; **facts stated by the user**: environment and location → task scope, those spanning projects → common environments at the root (facts in executor replies are not extracted individually: store the original reply as execution evidence, write a brief progress entry, store long content as a document, and read the details when needed; see S6 and S7);
  reference resolution in Section 4 (“last time”, “before the fix” → specific instances); **replacement during writing**: compare constraints, decisions, rejected approaches, environment, and state with current entries in the same scope, and record replacement relationships;
  link rejected approaches to alternative approaches; understanding of the user goes only to CTM.
- **Dependencies**: S0; the placement result (S2) determines “the same scope”—the two steps run in sequence when processing the same message: first understand, then locate, and finally write and replace.
- **Downstream impact**: Constraints placed too high → over-tightening in P-exec; missed replacement judgments → retaining an overturned understanding, false judgments → losing constraints that are still valid; facts not placed → missing facts; too many decisions extracted (currently about 3 times the standard) → noise in execution context.
- **Evaluation**:
  - This step: E1, E3 (existing standards); add accuracy of constraint placement levels, precision and recall of replacement judgments, and accuracy of fact classification—these three have no reliable standards, so the user spot-checks about 20 items for each to establish standards.
  - Downstream: The number of errors in P-exec in the three categories “over-tightening”, “retaining an overturned understanding”, and “missing facts” must be no higher than the current level; the goal is a clear reduction in missing facts.
  - Cost: Understanding calls per message; replacement comparison is called only when there is a new entry and a current entry in the same scope.
- **Deferred**: Writing object constraints to file comments and `ctm.md` (requires a real working directory; do this during runtime integration); in replay, object constraints are recorded in the object index; see S5 for delivery rules.

### S2 Location and Placement

- **Coverage**: The complete order of location signals in 5.1 (interface selection and @references, message content, current task, recent conversation and the displayed items and pending items in it, running executors, memory retrieval + edge expansion + time weighting);
  placement rules in 3.4 (must state the service relationship; how it serves; sibling + sequential; create the common parent at the Task level; create a Goal when the user states the purpose; place under the root if the relationship cannot be stated);
  local constraint basis for splitting into subtasks (signals from S1); ask first or act first (reversibility); bounded summaries for large trees.
- **Dependencies**: S1 (understanding and local constraint signals), S0, S3 (running executors and status; before S3, approximate with recent activity and note this in evaluation).
- **Downstream impact**: The entire L1 chain; incorrect attachment causes incorrect constraint propagation (over-tightening or missed constraints); original work-thread text (the most effective part of P-exec) depends on correct work threads; incorrectly attaching new work to an old node brings in old progress.
- **Evaluation**:
  - This step: All of P-loc; **user spot-checks of about 20 parent-child edges and 10 nodes under the root** as the standard for subordination relationships; the proportion of newly created nodes for which “the service relationship cannot be stated, so the node is placed under the root”.
  - Downstream: Run P-exec on the self-built tree (no longer using the annotated tree), and compare the results with those on the annotated tree; count how often incorrect attachment causes constraints to be passed into unrelated tasks.
  - Cost: Location call input remains bounded as the tree grows.
- **Deferred**: Pages and paragraphs in document browsing as signals (no interface); simulate interface selection in replay as already done (select the target task for messages that only advance work).

### S3 Task Lifecycle

- **Coverage**: Status events in 3.4 (proposed, pending execution, executable, in execution, blocked, paused, reported complete, verified, abandoned, replaced, reopened) and their times, reasons, and sources;
  relationships (sequential, parallel, convergence, conditional, either-or); predecessor completed → successor executable; predecessor result overturned → successor pending recheck; parent task status; **fold upward on completion**;
  stages and timing in Section 4 (event-triggered, suspended while in flight); a decision referenced across tasks changes → the referencing task is pending recheck (3.6).
- **Dependencies**: S0, S1 (the user's statements of approval, abandonment, and completion), S6 (execution result events; before S6, infer from historical replies and user reactions).
- **Downstream impact**: The “running executor” signal (S2); the default for the current task; folded content enters the execution context of the parent task and successors (S5); maintenance corrects status (S4).
- **Evaluation**:
  - This step: Retrospective standards for status (the user's subsequent words and actions: acceptance, abandonment, reopening), annotated by two annotators and spot-checked by the user; whether folded content includes conclusions and “not feasible”.
  - Downstream: Points in P-loc that depend on the “running” signal; points in P-exec that require predecessor results (new annotation: whether execution requires the result of a predecessor task).
- **Deferred**: Planner-generated plans and gates (require real execution); replay handles only user-driven status changes.

### S4 Maintenance

- **Coverage**: All of 5.6: read the message segments and progress written since the last maintenance; merge duplicates, fix parent-child and ordering relationships, create missing parent nodes (create a Goal for a stated purpose, otherwise a Task-level node), fix statuses, rename;
  review nodes under the root after new records are added; **check constraint propagation after reparenting** (moving a node changes the task constraints it inherits; list the changes and notify the user when necessary); respect user modifications (S9 provides modification records);
  document organization (merge, split, mark as outdated, depends on S7); object constraint migration (deferred).
- **Dependencies**: S0 (Segment), S2, S3, S7.
- **Downstream impact**: L7; reparenting changes constraint propagation and work lines; excessive maintenance changes increase the user's correction burden.
- **Evaluation**:
  - This step: P-loc work-line precision and recall before and after maintenance; the user spot-checks about 10 parent nodes created by maintenance and about 10 reparentings.
  - Downstream: differences in P-exec before and after maintenance; list each constraint propagation change caused by reparenting and spot-check them.
  - Cost: input for each maintenance run (only records since the last run and the nodes involved) and frequency.

### S5 Execution context

- **Coverage**: All of item 3 in 5.2: contract (user's original words, authorization governed by those words, fixed clauses); current task state (purpose, working directory and runtime environment, stage, progress and validation, pending items, prerequisite results);
  current task constraints and decisions on the path (including preferences and global constraints at the root; subtree exceptions are marked); rejected or replaced approaches in the same work line listed separately; observation times marked for progress; original text of recent exchanges in the work line;
  paths and purposes of relevant documents (S7); content the user pointed to this time; items that can be asked about; fixed order; resolution selection from 3.2; object constraints are read by the executor as required by fixed clauses (not handed over in bulk by directory in the context).
- **Dependencies**: S1–S4, S7.
- **Downstream impact**: L4 (whether the executor has fewer questions and whether CTM can answer them); P-cost.
- **Evaluation**: All of P-exec; attribute errors by category to changes in the respective upstream steps; compare with the full history of the original session; executor input tokens.
- **Deferred**: None.

### S6 Execution round trips, control layer, and relay

- **Coverage**: Items 1, 2, 4, 5, and 6 of 5.2 (when a response arrives: save the original text and traces as evidence, write one brief progress entry, save long content as a document, and let the user's reaction determine what to remember; do not extract facts individually): execution form; lifecycle (create, reuse an active session, forward new messages and new constraints, termination conditions); control layer (stop classification, formal completion, errors and budget,
  boundary violations and modified constraint annotations, milestones, report only six categories); CTM answers executor questions from memory (providing only current content); turn requests into pending items; write completion and failure back; control commands;
  result handling (Run evidence, progress, file versions, traces take priority, and when the user is in the loop, the user's reaction determines what to remember); 5.4 relay and notification (numbered items, tasks identified for pending items); 5.1 response.
- **Dependencies**: S0, S1, S3, S5.
- **Downstream impact**: Displayed items and pending items are inputs to S1 and S2 reference resolution (L6); execution results are sources for S3 status and S1 progress.
- **Evaluation**:
  - E7 (existing); add E7b: for “ask the user to decide” and “need information” stops handed to CTM, whether CTM can answer correctly from memory and when it should pass the question to the user (the standard comes from the user's answer at the time).
  - Displayed items: generate numbered items from historical responses in replay, and test reference resolution for “change it according to the second item” and “OK, start” (signals for S2).
  - Downstream: estimated user burden (number of stops requiring a user answer).
- **Deferred**: Real execution and traces (runtime integration); the executor does not take action during replay.

### S7 Knowledge and documents

- **Coverage**: All of the documents section in 3.6: types, purpose descriptions, verified and unverified, references to decision numbers, single writer, incremental updates by section, outdated markers; save executor long content as documents; long materials pasted by the user;
  write facts about approaches into knowledge documents; document indexes enter execution context and queries.
- **Dependencies**: S0, S1, S6.
- **Downstream impact**: Missing facts in P-exec; E8 query responses; document organization in maintenance.
- **Evaluation**: Change in the missing-facts category of P-exec; proportion of E8 questions that memory can answer and the accuracy of those answers.
- **Replay limitation**: The history contains only file paths, not file contents; use long content from executor responses and approaches organized by CTM from those responses as document contents, and note this in the evaluation conclusions.

### S8 Query

- **Coverage**: All of 5.3: classification (when uncertain, treat as a query and state “answering as a query”), do not create a node, link the record to a node or the root, memory or read-only execution, observed state with time, numbered display, carry query results over when turning a query into a task.
- **Dependencies**: S1, S5 (memory reading), S6 (read-only execution and displayed items), S7.
- **Downstream impact**: Query records are inputs for later references (“change it according to the second item”) and conversion to tasks; misclassifying queries as tasks fragments the tree (L5).
- **Evaluation**: E8 (existing); add resolution accuracy when query records are referenced by later messages; proportion of queries classified as tasks (E1) and the impact on the tree (P-loc).

### S9 Root layer, understanding of the user, and interface modifications

- **Coverage**: All of 3.3 (persona, understanding of the user and its basis and confidence, overall goal, preferences and global constraints, commonly used environments, root exchange records, separate sources, length limits, stability);
  propagation of interface modifications in four respects in 5.5 (memory relationships, running executors, pending items, reference); authority order in the rules in 6.
- **Dependencies**: S0–S6.
- **Downstream impact**: Understanding of the user affects S1 (E9); global constraints affect S5; interface modifications affect S2 and S4 (as reference, not as hard rules).
- **Evaluation**: E9 (existing); simulate interface modifications in replay (for example, inject parent-child edges corrected by the user during spot-checks as interface modifications), and test whether subsequent location and maintenance respect them and whether constraints are reparented accordingly.

### S10 Overall replay

- Use the complete S0–S9 implementation for causal replay on three weeks of material (simulate purely advancing messages through the interface), obtain E1–E10 in one run, compare with the results of each step individually, and confirm that the combination does not fail; then proceed to the pilot trial plan for runtime integration.

## 4. Order, dependencies, and checkpoints

| Order | Step | Prerequisites | Checkpoint |
|---|---|---|---|
| 1 | S0 | — | Records complete and replayable |
| 2 | S1＋S2 (processing chain for the same message) | S0 | User spot-checks: constraint placement level, replacement, fact classification, parent-child edges; no regression in P-loc or P-exec |
| 3 | S3 | S1, S2 | Status and folding; points in P-exec that require prerequisite results |
| 4 | S4 | S0–S3 | Comparison before and after maintenance; constraint changes after reparenting |
| 5 | S7 | S0, S1 | Fewer missing facts |
| 6 | S5 | S1–S4, S7 | P-exec |
| 7 | S6 | S5 | E7, E7b, references to displayed items |
| 8 | S8 | S5–S7 | E8 and query records |
| 9 | S9 | S0–S6 | E9, interface modifications |
| 10 | S10 | All | Overall replay |

S1 and S2 are combined into one step because the “same scope” replacement judgment depends on placement, while the basis for splitting placement into subtasks comes from the local constraints written to memory; evaluated separately, each would appear to pass, but together they would miss cases.

## 5. Disposition of Existing Code

The disposition record at the time. The `understand`, `localize`, `placement`, `maintain`, `validity`, `constraints`, and `contract` in the table were deleted on 2026-11-25 along with the first version of the message flow.

| Existing | Disposition |
|---|---|
| `ctm2/understand.py` | Keep as the basis for S1; add placement level, fact classification, reference resolution, and attitude toward presented artifacts |
| `ctm2/localize.py` versions one through four, `placement.py` | Use version four as the starting point for S2; version three (defaulting to remaining on the current work line) is no longer used |
| `ctm2/tree.py` | Change to a view over S0 storage |
| `ctm2/maintain.py` window maintenance | Starting point for S4; add status, constraint checks after reparenting, and review of nodes under the root |
| `ctm2/validity.py`, `constraints.py` | Merge into replacement at write time in S1 |
| `ctm2/progress.py` (including facts) | Result processing for S1／S6; place facts according to 3.4 |
| `ctm2/control.py` | Starting point for S6 |
| `ctm2/contract.py` | No longer used (LLM rewriting of contracts is harmful); keep for comparison |
| Execution context assembly in evaluation scripts | Move to S5 |

## 6. Limitations of Replay Evaluation

- Interface selection and modification are simulated; the executor does not actually perform the work, so there are no execution traces or file versions. The history contains only file paths, not contents, so the document mechanism can only be partially evaluated.
- Model annotation is unreliable as a standard for work granularity, parent-child edges, replacement relationships, and constraint placement levels; user spot checks are authoritative.
- All of these are noted in the evaluation conclusions; only a runtime pilot trial can answer questions about correction burden, latency, and caching.

## 7. Execution Record

### S0 Memory Storage (complete)

`ctm2/store.py` (SQLite; entries, edges, events; write time, occurrence time, validity interval and replacement, observation time; sources; “as of a given time” queries) and `StoreTree` in `ctm2/tree.py` (tree view; structural changes go through storage and leave events).
Offline test `tests/test_ctm2_store.py`. Using existing understanding, progress and facts, and replacement relationships, three weeks of material were written to storage (without calling a model): all 1,497 turns and 2,047 message segments could be read back by node, time, and source;
at 80 execution decision points, the “current task constraints as of that moment” matched the evaluation code's calculation (80/80); writing took 53 seconds, 10.6MB.
Finding: Many facts were extracted using the second version of the progress summary (about 5.7 per reply, with approaches accounting for four tenths); S1 needs to control the quantity at write time and delivery.

### S1＋S2 Understanding, Writing and Localization, Placement (implementation complete, awaiting user spot checks)

Implementation: `understand.py` version four (constraint placement levels and local constraints, facts stated by the user, temporal references), `localize.py` version four (service relationships, siblings and common parents, Goal, constraint placement, temporal reference resolution,
segments providing background within the same message assigned to the node of the request segment they serve), `placement.py`, `writeback.py` (writing messages and replies, fact placement, replacement at write time), `pipeline.py`.
Causal replay from empty storage on 10-05 through 10-08 (tuning segment) and 10-09 through 10-11 (held-out segment), without maintenance (S4).

| Metric | Version one tuning／held-out | Version two tuning／held-out | S1＋S2 tuning／held-out |
|---|---:|---:|---:|
| Work line pairwise precision (against coarse annotation) | 0.71／0.56 | 0.63／0.53 | 0.66／0.69 |
| Work line pairwise recall (against coarse annotation) | 0.89／0.85 | 0.87／0.75 | 0.75／0.64 |
| Node purity (against coarse annotation) | 0.78／0.78 | 0.87／0.88 | 0.93／0.83 |
| New work created a new node (against fine annotation) | 12%／17% | 30%／48% | 41%／55% |
| References to existing work landed within its work line (including siblings, against coarse annotation) | 89%／92% | 85%／79% | 86%／72% |

- Cases where different purposes were grouped together (precision) decreased noticeably in the held-out segment; but more work remained under the root or was assigned elsewhere (recall decreased). This is the expected result of “place it under the root if no service relationship can be identified” without maintenance, and S4 needs to address it;
  in the held-out segment, the proportion of follow-up messages about existing work landing outside the work line was relatively high (72%), a risk that requires joint judgment through S4 and spot checks.
- Understanding version four on the held-out window: type 91.6% (version three 92.0%), action boundaries 86.3% (88.7%), attitude toward the previous reply 79.9% (83.2%), constraint recall 92.3% (89.7%), decision recall 95.1% (92.7%). Boundaries and attitude declined slightly, near the noise level of a single run; keep an eye on them.
- Downstream P-exec (50 points, two reviews): full history of the original session correct 35–36, work line context on the annotated tree 29, context from storage built by S1＋S2 26. Missing facts decreased (8–9 versus 11–12),
  while over-tightening (8–10 versus 5–6) and missed constraints (4–6 versus 1–2) increased; the differences are near review noise. One identified mechanism issue: a constraint is placed on the node for a particular step according to “when unsure, place it lower”; the next step for the same purpose is a sibling,
  so it is not on the path and cannot access it. This is precisely an issue of coordination between placement and constraint propagation, to be handled in S4 (when creating a common parent, lift constraints belonging to the common purpose) and S5, with standards set through spot checks of constraint placement.
- The spot-check list of 136 items (36 parent-child edges, 16 nodes under the root, 28 constraint placements, 28 replacements, 28 fact classifications) is in the private directory `research/eval-corpus/l3/S1/s12/spotcheck.md`.

**Correction (pointed out by the user)**: In the first S1＋S2 replay, CTM extracted facts item by item from every executor reply (about 5.7 per reply, about 3,800 across the two segments), and let them participate in replacement,
even resulting in executor reports “replacing” user constraints and decisions (about 40 cases across the two segments). This did not conform to item 6 of concept model 5.2 and the conclusions of [Agent Reply Analysis](agent-reply-analysis.md):
the original reply is execution evidence; CTM writes only one brief progress entry, stores long content as a document, and reads details when needed. What to remember is determined by the user's reaction. This has been changed to:
replies write only brief progress and evidence (long replies are stored in full as documents); replacement occurs only between items stated by the user. The wording in concept model 3.4 and section 4 now makes this explicit.
Both replay segments were rerun with the corrected implementation; A (parent-child edges), B (nodes under the root), and C (constraint placement) in the spot-check list are unaffected and remain valid, while D (replacement) and E (fact classification) are invalidated and regenerated using the rerun results.

**Rerun corrected to match the design (s12b)**: Replies write only brief progress and evidence (29 long replies across the two segments were stored as documents), replacement occurs only between items stated by the user (62 cases across the two segments), and there are 164 facts stated by the user.
Structural metrics are similar to the first replay (work line precision 0.58／0.62, recall 0.72／0.62, against coarse annotation); the difference between the two replays is about 0.05–0.07, and can be regarded as run-to-run variation of the same mechanism.

Downstream P-exec (50 points, two reviews of five contexts in the same session, agreement rate 0.86):

| context | Correct | Missing facts | Over-tightening | Executor input tokens |
|---|---:|---:|---:|---:|
| Reference: full history of the original session | 34–35 | 6–7 | 3–4 | 24.4k |
| Work line context on the annotated tree (previously best) | 22–26 | 15–17 | 3 | 4.5k |
| Self-built storage, facts extracted item by item (not in accordance with the design) | 22–24 | 12 | 8–9 | 5.8k |
| Self-built storage, according to the design (brief progress＋documents＋evidence) | 14–17 | 16–17 | 9 | 4.0k |
| Same as above, plus one turn of “executor asks questions, CTM answers from memory” | 18–19 | 14–15 | 14–15 | 4.2k |

- The implementation according to the design is currently clearly worse than item-by-item extraction: the design relies on “the executor asks for what is missing,” but the executor asked questions at only 23/50 points (33 in total), and CTM found answers from memory for only 15;
  the executor in the history also did not write approaches into documents according to the output convention, so the documents in the replay are merely the original text of long replies. After one turn of questions, the correct count recovered by 3–4, but over-tightening increased (old restrictions brought up in the answers and “unverified” notices made the executor more cautious).
- Over-tightening and missed constraints on self-built storage are still higher than on the annotated tree (a constraint placed on the node for one step cannot be accessed by the next step as a sibling), pending resolution through S4 and spot checks.
- This shows that the design of “remember only brief progress, retrieve details as needed” loses facts when the executor does not actively ask questions; whether CTM should proactively retrieve relevant excerpts of execution evidence for the current request at dispatch time is a design question to discuss with the user.

### S3–S9 implementation (complete) and evaluation of the parts that can be evaluated

As arranged by the user: first implement all remaining mechanisms according to the design, repeatedly checking against the concept model for omissions; evaluate only the convenient parts, leaving those requiring extensive simulation until runtime.

**Implementation**: See [CTM implementation](ctm-implementation.md) for the modules and Section 2 for the item-by-item comparison (every item in the concept model is implemented, except for three categories of runtime content: the interface, real executors, and writing files).
All 23 offline tests in 6 files pass (`tests/test_ctm2_*.py`, without calling a model). Among them, `test_ctm2_pipeline.py` walks through the entire chain by scene: dispatch new work → executor stops and asks the user to decide → user gives brief approval, and the reply is passed back to the session →
correction (object constraint + rejected approach, relayed to the active session) → session ends after 5 hours, and the new executor created on reactivation receives the files, rejected approach, and decision → pause and abandon → interface modifications and maintenance (constraint lift, inheritance change records, and proposals only for nodes the user has modified) →
subtree exceptions, cross-task references and pending rechecks, external file modifications ending a session, escalation when constraint comments are deleted or altered and when there is continued lack of progress, document paragraph selection → queries handed to an active session or a new read-only executor.

**Full replay** (one week of material from 10-05 to 10-11, 698 turns, causal replay from empty storage; maintenance every 12 hours; prolonged inactivity set to 3 hours; understanding, progress summaries, and execution control layer judgments are independent of the tree and were computed in parallel beforehand).
The historical user could not see CTM's displays or questions, so references to displayed items, answers to CTM's questions, and the planner's proposals cannot be tested in the replay and are only recorded.

| Item | Result |
|---|---|
| Understanding, fifth version (held-out window, compared with fourth version) | Category 91.6% (91.6%), role 84.8% (82.3%), boundary 87.3% (86.3%), attitude toward the previous reply 80.4% (79.9%), constraint recall 94.9% (92.3%), constraint category 97.3% (92.3%), decision recall 90.2% (95.1%), extra decisions reduced from 113 to 94: on par |
| Work line structure (pairwise precision / recall, compared with coarse annotation A; C is similar) | 10-05 to 10-08: S1＋S2 at 0.44／0.77, full implementation at 0.50–0.56／0.83–0.84; 10-09 to 10-11: 0.56／0.61 → 0.59–0.60／0.84–0.87 (variation between two replays about 0.05) |
| Dispatch and executor lifecycle | 709 dispatches: reused active session 231, read-only query handed to the active session of the relevant task 193, new executor created for new task 135, new executor created on reactivation 49, new read-only executor created for read-only query 101; sessions ended: prolonged inactivity 109, involved files modified elsewhere 76 |
| User burden | CTM first asked the user in 8 turns (object constraint conflicts 4, unclear destination and irreversible 4); executors escalated to CTM 10 times (all concerned information, choices, or authorization only the user could provide), and CTM relayed all of them to the user; a subsequent check confirmed that all 10 did require the user (E7b) |
| Memory content | 89 replacement pairs, 1 subtree exception; 188 object constraints (181 objects, proposals to write them to files are all pending); 144 cross-task references; 13 items of understanding of the user; maintenance made 9 reattachments, 8 additions of ordering, 8 renames, 3 status fixes, 1 constraint lift, and 1 Goal creation |
| Cost (per user message) | About 4.7 calls, about 16.8k input tokens: locating 12.1k (bounded), understanding 3.8k, progress summaries 1.3k, execution control layer 0.75k, with the rest for replacement comparisons and conflict checks; maintenance about 22k input tokens per run |

**Downstream P-exec** (the same 50 execution decision points, five contexts reviewed twice in the same setting, agreement rate 0.90):

| context | Correct | Main errors | Executor input tokens |
|---|---:|---|---:|
| Reference: full history of the original session | 33–35 | Missing facts 7–8 | 24.4k |
| S1＋S2 self-built storage (previously) | 17 | Missing facts 21–22, unnecessary questions 17 | 4.0k |
| Full implementation, always creating a new executor (initial context) | 26–27 | Fabricated obligations 7–9, treating reports as facts 6–7, missing facts 5–6 | 5.7k |
| Full implementation, lifecycle as designed (active session reused at 34 points, new session at 15 points) | 26 | Missing facts 11–14, overly restrictive 8–9 | 6.7k |
| Same as above, including changes to the work line elsewhere when relaying to the session | 24–27 | Same as above | 6.7k |

- The full implementation raised the number of correct execution contexts from 17 to 26–27, and reduced missing facts from 21–22 to 5–6: the file list, referenced decisions and query results from elsewhere, simulated reads of `ctm.md`, and progress and document indexes as designed all contributed.
- Under the lifecycle, the gap with the original session was small at the 34 points where a session was reused (40 versus 45 across the two reviews); the gap was concentrated at the 15 points where an executor was created or reactivated (12–14 versus 23, out of 30).
- Including changes to the work line elsewhere when relaying to the session had no measurable effect; the design remains unchanged.
- Sessions in the replay could only be reconstructed from the ends of replies (without full replies and tool outputs), providing a lower bound for real sessions; how well session reuse can perform must be evaluated at runtime.

**Problems found and fixed during replay**:
1. Sessions no one returned to were always counted as “running,” contaminating the locating signal and causing locating input to rise from 12k to 20k → before each message, clear executors that have met the termination conditions.
2. When an executor needed information “only the user has,” CTM treated a memory record that “this information had been requested before” as the answer (5 of 10 escalations) → information counts as found only if the information itself is in memory.
3. An explicit user change to an object constraint (“change to …”) was also treated as a conflict and asked about first (19 turns) → what the user explicitly says to change is the user's decision, handled as a replacement at write time (reduced to 8 turns).
4. The user's follow-up questions were never closed; the “all subtasks have ended” event was written repeatedly → fixed.
5. Two errors in the evaluation script itself (duplicate executor IDs across two replays caused session reconstruction to mix in data from the other replay; “user's original words” appeared twice in the reconstruction format) caused the session reuse result to be underestimated at 11–18 correct; the table above shows the corrected results.

**Interpretations made based on the concept model (require user confirmation, then to be written into the concept model)**:
1. When a query that memory cannot answer is dispatched for read-only execution, if the relevant task has an active session, hand the query (marked read-only) to that session; otherwise create a new read-only executor—the basis is item 2 of 5.2, “subsequent user messages about it are relayed to this session.”
2. An executor reporting completion does not immediately end the session: the user's immediate follow-up questions and modifications are still handled within the session; the session ends when the user confirms completion, abandons it, it is replaced, there is prolonged inactivity, or involved files are modified elsewhere.
3. Ask about an object constraint conflict only when the user has not indicated that they are changing the rule; if the user's words themselves change the rule, treat it as a decision.
4. CTM answers a “decision” escalated by an executor on the user's behalf only when the user's original words, current constraints and decisions, and understanding of the user already clearly provide the answer; no cases that could be answered on the user's behalf occurred in this replay.

**Deferred until runtime**: interface and references to displayed items; writing object constraints to files and migration; whether executors write documents as agreed and follow constraint comments; formal completion, budgets, and milestones in the execution control layer; planner proposals and approvals; user correction burden and latency.
Spot-check list: `research/eval-corpus/l3/S1/full/spotcheck-f2.md` (39 items: maintenance changes, questions asked during object constraint conflicts, understanding of the user), awaiting the user's answers together with the previous S1＋S2 spot-check list.

### Revisions After the Third Round of Spot Checks (Tree Attachment, Constraint Boundaries, Sessions and Queries)

**User's answers and conclusions from the discussion** (written into concept model 3.4, 3.5, 5.2, 5.3, 5.5 and 5.6, and the fifth edition of the annotation instructions):
- The tree reflects the composition of the work itself: parent-child relationships are generally compositional, and siblings are parallel parts or sequential steps of the same work; this is not applied mechanically, and CTM judges based on context. It may also be the same work simply continuing;
  when creating a task, consider grouping the same work proposed step by step under one parent. One role of branches is to isolate and inherit constraints, which helps check attachment, but constraints do not determine structure. Whether a parent task is complete is judged when needed.
- Constraints are restrictions or rules that must be followed; guidance on approaches and plans is listed separately as “guidance” (inherited downward, not a hard restriction); wrap-up actions are work content; corrections to previous approaches are decisions.
  When the same requirement appears in several branches, lift it if it applies to all work under the common parent. Submit requirements resembling object rules or personal habits to the user as suggestions for approval; an incorrect lift can be rolled back.
- A session normally does not end (it ends only when context is full and the user does not compress it); abandoning work only stops the executor. Queries are answered in a fork session, and the conclusions are passed to the session with the next transfer. Ask about conflicts only when the user has not indicated an intention to change the rules;
  CTM answers the executor's multiple-choice questions on the user's behalf only when the answer is already clear.
- Spot-check results: 7 of 10 constraint placements were correct, and 3 were not actually constraints (guidance, work content, corrections); 9 of 10 replacements were correct (a similar but different approach was treated as a replacement).

**Implementation**: Understanding V6 (guidance listed separately; record only guidance that remains effective afterward), positioning V6, maintenance V4 (the same attachment principles; constraint lifting and rollback; parents describe specific work rather than a domain),
`scope.py` (where the same requirement goes), judging parent task completion when needed, sessions and forks, changes during the interval before transfer to a session (replaced approaches, notifications, conclusions of queries answered in forks). All 25 offline tests passed.
The first replay (f3) exposed two problems: understanding also recorded what the message asked to be done as “guidance” (60 items in one week); positioning used a broad parent (“investigate and improve the operational performance of an access path”) to draw several different pieces of work in the same domain together.
Changed to recording only guidance that remains effective afterward (down to 25 items), and required parents to describe specific work and its output, with the same domain being insufficient reason to attach items together. Reran as f4.

**Results** (one-week replay; work-line metrics compared against the fourth-edition coarse annotations, considering only whether the top level is the same work):

| | f2 (previous) | f4 (this round) |
|---|---|---|
| Number of nodes／deepest level／parents with only one child node | 161／6／21 | 95／3／4 |
| Work-line pairwise precision／recall (10-05 to 10-08) | 0.50／0.83 | 0.57／0.93 |
| Work-line pairwise precision／recall (10-09 to 10-11) | 0.59／0.84 | 0.55／0.82 |
| Understanding (held-out window) category／constraint recall／constraint precision | 91.6%／94.9%／0.85 | 91.2%／92.3%／0.86 |
| Input tokens per message (excluding understanding) | 11.0k | 10.5k |

Execution context (50 points, five types of context reviewed side by side twice, agreement rate 0.86):

| context | Correct | Main errors | Input tokens |
|---|---:|---|---:|
| Full original session history (reference) | 32–36 | Unnecessary questions 6–7, missing facts 4–6 | 24.4k |
| S1＋S2 (previous) | 17–18 | Missing facts 16–17, unnecessary questions 17–18 | 4.0k |
| Always create a new executor (initial context) | 25–27 | Treating reports as facts 7–8, unnecessary questions 7–8 | 5.8k |
| As designed: always reuse the session (reused at 43 points, created at 6 points) | 28–30 | Missing facts 11, unnecessary questions 7–10 | 9.0k |
| Same as above, with new exchanges elsewhere in the work line included when transferring to the session | 30–32 | Missing facts 9 | 11.2k |

- After always reusing the session, the execution context as designed (28–30) outperformed always creating a new executor (25–27) and approached the original session (32–36); at the 43 points where the session was reused, including new exchanges elsewhere in the work line brought it level with the original session (56 correct versus 56 across the two reviews combined).
- Including new exchanges elsewhere in the work line: in the previous round, session intervals were all very short, so no effect was visible; in this round, sessions spanned several days, yielding 2 more correct and 2 fewer missing facts, at a cost of about 2k more tokens per transfer. The difference is near review noise. Whether to include this in the design is for the user to decide.
- Sessions in the replay are still a lower bound (only the ends of responses are available, not complete responses and tool output).
- Spot-check list (20 items: attachment judgments, continue or new node, maintenance changes, where the same requirement goes, guidance): `research/eval-corpus/l3/S1/full/spotcheck-tree-f4.md`.

### Fourth Round: Research Work, Behavior Guidance, Context Scope and Session Trade-offs

**Implemented as discussed** (concept model 3.4, 3.6, 5.2, S3 and AGENTS.md updated): understanding V7 (research listed separately as research, Agent behavior guidance listed separately as behavior), positioning V7 (continuation and association of research entries;
whether “continue” means the original task or a new task depends on the situation, with the consequences of both kinds of misjudgment stated), research entries (in the query list, with their own sessions and conclusion documents, can be referenced by tasks, and can be attached to the tree during maintenance), behavior guidance documents (index given to the executor, session notified on updates),
the executor's report that “this request is complete” recorded only in the execution record, initial context scope changed to the path plus recently executed siblings (take results, decisions and exchanges from siblings, but not constraints or guidance), and exchanges elsewhere in the work line no longer included when transferring to the session. All 26 offline tests passed.

**Results** (one-week replay f5; understanding V7 on the held-out window: category 91.2%, effect 88.9%, action boundary 90.1%, attitude 83.8%, unchanged):

| | f4 | f5 |
|---|---|---|
| Work-line pairwise precision／recall (10-05 to 10-08) | 0.57／0.93 | 0.60／0.92 |
| Work-line pairwise precision／recall (10-09 to 10-11) | 0.55／0.82 | 0.75／0.82 |
| Research entries／of which attached to the tree during maintenance／behavior guidance documents | — | 26／9／4 |
| Input tokens per message (excluding understanding) | 10.5k | 11.9k |

Execution context (the same 50 points; an “old scope” comparison was added on the same f5 storage, agreement rate 0.83 across two reviews):

| context | Correct (two reviews) |
|---|---:|
| Full original session history (reference) | 31、27 |
| New executor, old scope (most recent 6 turns of exchanges across the whole work line) | 28、25 |
| New executor, new scope (path plus recently executed siblings) | 26、22 |
| Lifecycle as designed (new scope) | 22、22 |

- The tree structure was better than f4, with precision in the later segment rising from 0.55 to 0.75.
- Execution context became worse: on the same tree, the new scope had 2–3 fewer correct and more unnecessary questions than the old scope; the lifecycle as designed (28–30 in f4) fell to 22. Points with a new executor were most affected (among 7 points, the new scope had 1 correct across the two reviews combined, the old scope 5, and the original session 12).
- Checked the hypothesis that “separating research caused task sessions to lack research conclusions”: points with related research actually had a lower failure rate (48%) than those without (61%), so this was not the main cause.
- Possible reason: the tree is still not entirely accurate, and needed prior context is often in other branches of a parent or earlier siblings; the new scope selects by structure, while the old scope selects recent exchanges by time, and the latter happens to cover “what just happened.” The gap is near review noise, but both reviews point in the same direction. The scope trade-off needs to be discussed with the user.
- Spot-check list (26 items: attachment, continue or new node, research, behavior guidance, maintenance, guidance): `research/eval-corpus/l3/S1/full/spotcheck-tree-f5.md`.

**Adjusted the scope based on the user's feedback**: take about 7 recently executed siblings, plus about 3 recently executed siblings of the parent task (the numbers roughly correspond to the range of surrounding work a person can remember; tasks attached directly under the root have no such siblings).
Regenerated contexts for comparison on the same f5 storage (two reviews, agreement rate 0.82):

| context | Correct (two reviews) | Executor input tokens |
|---|---:|---:|
| Full original session history (reference) | 25、27 | 24.4k |
| New executor, old scope (most recent 6 turns of exchanges across the whole work line) | 30、32 | 5.6k |
| New executor, path plus 3 siblings | 25、29 | 6.3k |
| New executor, path plus 7 siblings and 3 siblings of the parent (current) | 30、31 | 7.2k |
| Lifecycle as designed (reuse the session; use the current scope at the start of the session) | 23、22 | 8.5k |

- The current scope caught up with the old scope, with 3–5 more correct and fewer unnecessary questions than taking only 3 siblings; adopted.
- Reconstruction of reused sessions (the initial context plus transfers and response endings for each subsequent turn) was clearly below the new executor in this round, and the full history of the original session was similarly low: long sessions reconstructed with truncated responses are only a lower bound in replay,
  the actual effect of session reuse must be evaluated at runtime; the design does not change as a result (reuse when continuing, as judged by CTM).

### Round Five: Boundary Between Research and Queries, Discovered Problems, Subtask Session Reuse

**Implemented according to the spot-check feedback** (concept model 3.4, 3.6, and 5.3 have been changed): Research entries only cover research that collects external information; questions about the project itself are queries, handed to the most relevant task and answered using a fork of its session; “continue the research” continues the preceding item;
when a problem is discovered while performing this work and belongs to the work itself, asking to continue solving it is a continuation of that work. It becomes a subtask only when the problem has its own requirements, needs separate acceptance, or needs to be advanced separately; when a subtask is a direct continuation of the parent task’s current execution, it reuses the parent task’s session;
B2 (how to use subagent for this research) is guidance for the task, and B3 (launch sub-agent without a window) is behavior guidance. Also fixed the problem where localization dispatched work to Goal when it placed Goal in a separate segment (it now dispatches to a newly created task under Goal).

**An intermediate regression (f6, retained)**: Work-stream precision for the first 4 days fell from 0.60 to 0.28. There were two reasons: first, “discovered problems are continuations by default” was stated too broadly. After an analysis query found a bug, “fix it” was also treated as a continuation of the same work.
The “submit the latency guide” task went on to absorb production data analysis, fixes, PR review, unit test cleanup, and incident alignment (171 turns); second, when a query was attached to a relevant task, the query content and the response from read-only execution were written into that task’s current state and progress.
The task also appeared to be doing these analyses, and its title grew broader with each maintenance update. Fix: only problems discovered while performing the work and belonging to the work itself count as continuations. Fixes delivered after a problem is found through investigation, a query, or a review are new work;
a query is only linked to the task it asks about, and the answer is recorded as the query’s result, not as the task’s current state or progress; the new executor’s context separately lists “queries the user has asked about this work (conclusions).”

**Results (f7)**:

| | f5 | f6 | f7 |
|---|---|---|---|
| Work-stream pairwise precision／recall (10-05 to 10-08) | 0.60／0.92 | 0.28／0.98 | 0.60／0.94 |
| Work-stream pairwise precision／recall (10-09 to 10-11) | 0.75／0.82 | 0.53／0.83 | 0.52／0.86 |
| Number of nodes | 132 | 92 | 100 |
| Research entries | 26 | 9 | 10 |
| Subtasks performed in the parent task’s session | — | 11 | 9 |

Understanding V8 on the held-out window: category 93.4% (V7 91.2%), function 84.8% (88.9%), action boundary 90.1% (unchanged), attitude 79.3% (83.8%); queries misclassified as research fell from 4 cases to 2.
Precision in the latter part of the three replays was 0.55, 0.75, and 0.52 respectively (f4, f5, f7), a large fluctuation; the main merges in the latter part of f7 were “verify deployment in a certain region” absorbing the fix for a routing regression it discovered (42 turns), and batch transcription absorbing its Web console (40 turns).
Both are reasonable in terms of their composition, but the annotation split them into different top-level work items. They were put on the spot-check list for the user to judge.

Execution context (50 points, agreement between two reviews 0.85):

| context | Correct (two reviews) | Executor input tokens |
|---|---:|---:|
| Full original session history (reference) | 33, 35 | 24.4k |
| Lifecycle as designed (reuse session for continuations, create a new one for new tasks) | 32, 33 | 10.3k |
| Always create a new executor | 25, 29 | 6.7k |

At the 42 points where the lifecycle as designed reused the session, it was correct 59 times across the two reviews combined, versus 56 for the original session and 48 for always creating a new executor. Spot-check list: `research/eval-corpus/l3/S1/full/spotcheck-tree-f7.md` (25 items).

### Round Six: Rewriting the Prompts

The user pointed out: spot-check questions cannot be put into prompts as examples—when answering the spot checks, he recalled the scene at the time, and a sentence alone cannot determine the answer; moreover, these examples came from the replay data for the same week, inflating the scores of the previous rounds on that week’s data.
Simply deleting the examples was not enough, so the prompts were rewritten in the following ways (understanding, localization, maintenance, replacement judgment, control layer, executor working agreement):

- Add the scene needed for judgment: include recent results and unresolved problems with candidate work, as well as queries the user has asked about it and their conclusions; mark which work each turn in the conversation and the preceding response belong to; also provide CTM’s understanding of the user to localization.
- For each judgment, explain what CTM will use it for, the costs of each kind of error, which way to lean when the costs are asymmetric, and what to ask oneself when making the judgment; do not use sentences from the evaluation data as examples.
- State the scene before the conclusion: understanding first writes situation, and localization first writes work for each segment, then gives the classification and location.
- Split overloaded calls: understanding has two steps. First judge intent and decisions, then extract constraints, guidance, behavior guidance, and facts if the message has content that remains in effect; understanding is now called in real time during replay, based on the state at that moment.
- The executor working agreement makes clear that asking questions interrupts the user, that the executor should not ask about things it can find out itself, and that it should not add deliverables, steps, or obligations on its own.
- Method: have gpt-6.1-sol and gemini-4-argon each make judgments on the development window, find concepts that were not clearly explained from disagreements and errors, and revise the explanations of those concepts; use the held-out window only for testing.

Three concepts found to be unclear and corrected on the development window: the distinction between constraints and decisions (what the user specifies the deliverable should be like is an object constraint, even if expressed as a chosen approach);
the judgment of “whether there is persistent content” excluded approval of the current approach (changed to record decisions in the first step); the distinction between the user refuting or correcting the agent and merely wanting to understand (clarified in terms of the consequences of the two kinds of error).

Understanding (gpt-6.1-sol; category／category set／function／action boundary／attitude; constraint and decision recall; “recorded” means recorded as either a constraint or a decision):

| | Development window V8 | Development window new version | Held-out window V8 | Held-out window new version |
|---|---|---|---|---|
| Category | 0.948 | 0.951 | 0.934 | 0.916 |
| Category set | 0.935 | 0.949 | 0.929 | 0.915 |
| Function | 0.829 | 0.875 | 0.848 | 0.833 |
| Action boundary | 0.900 | 0.879 | 0.901 | 0.882 |
| Attitude | 0.810 | 0.819 | 0.793 | 0.804 |
| Constraint recall (by category／recorded) | 0.93／— | 0.83／— | 0.92／0.97 | 0.74／1.00 |
| Decision recall (by category／recorded) | 0.90／— | 0.94／— | 0.95／0.95 | 0.90／0.88 |

The two models’ category agreement on the development window was 0.88 (0.88 on the held-out window). The main disagreements remained “correction or merely wanting to understand” and “control or a task with new requirements.”
The new version was broadly on par with V8 on the held-out window (the window has only 226 turns and 39 constraints, and most differences are within one or two items), while V8’s examples came from the spot-check list and annotation materials.

One-week replay f8 (new prompts; understanding called in real time during replay):

| | f7 | f8 |
|---|---|---|
| Work-stream pairwise precision／recall (10-05 to 10-08) | 0.60／0.94 | 0.56／0.87 |
| Work-stream pairwise precision／recall (10-09 to 10-11) | 0.52／0.86 | 0.55／0.74 |
| Task constraints／object constraints／decisions (number written by understanding) | 75／158／333 | 22／181／461 |
| Input tokens per message (including understanding) | approx. 15.1k | 21.4k |

Execution context (50 points, agreement between two reviews 0.91): full original session history 28, 29; lifecycle as designed 32, 33; always create a new executor 34, 34.
Unnecessary questions from executors that were always newly created fell from 6–10 cases to 0 (the executor working agreement made the cost of asking clear).

- Recall fell: some work was split into two streams. For example, batch transcription and its channel terminology prompt configuration became two top-level work items.
- Understanding recorded more requirements as object constraints and decisions, and markedly fewer as task constraints. Spot checks are needed to judge which is right.
- Cost rose by about 40%: localization input rose from 12.1k to 16.8k (candidate work included the current state and query conclusions), understanding was split into two steps, and maintenance input rose from 18.8k to 25.9k.
- Research entries still had misclassifications: checking a PR build failure, querying production data by region, and looking for configuration in the wiki were recorded as external research; “external” should be clarified as information unrelated to the scene of existing work. Checking the project’s own systems, data, and configuration belongs to that work.
- Spot-check list: `research/eval-corpus/l3/S1/full/spotcheck-tree-f8.md`.

### Round Seven: Retrieve Candidates by “Pointing Method,” with Objects as the Main Thread

The process after discussion (concept model 5.1 has been rewritten): For each message, CTM decides only two things: where and how to deliver the user's words, and what to record. One lightweight call determines the message's pointing method and extracts objects;
code retrieves candidates from several sources according to the pointing method (recently visited work, current work and running executors and pending items, object→objects in memory→work that has touched them, time); one delivery call makes the decision (if necessary, it expands to the full tree for another call);
code assembles context; memory gets a separate call after dispatch. No vector retrieval on the whole message: it mixes in wording and material, and often finds work that is merely on a similar topic. Identifiers (paths, PR numbers, branches, areas)
can be used to propose candidates when they are identical or differ only by a spelling error (this exception has been added to AGENTS.md).

Implementation: `ctm2/ref.py` (pointing method and objects), `ctm2/candidates.py` (object index, exact identifier matches and spelling tolerance, union with quotas by method); fixed the problem of file paths not being normalized
(VS Code Chat's tool records stored paths as raw JSON strings, and relative paths were not joined with the working directory). The same file now has the same identity across clients. Not yet integrated into the pipeline.

Test (new examples: use memory built from 10-05 to 10-08 to test raw messages from 10-09 to 10-11, 1–6 days apart; sol and argon each annotated afterward, and agreed items were retained):
Of 339 messages, 97 were agreed to point to old work, 148 were agreed not to, and 94 were disagreements (there is often a family of work on the same object, and the annotation itself is ambiguous); there were 28 entry points returning to old work.

| Candidate source | Top 3 | Top 5 | Top 8 |
|---|---:|---:|---:|
| Whole-message vectors | 46% | 50% | 57% |
| Object→work | 86% | 86% | 93% |
| Union with quotas by method (6.5 candidates on average) | 89% | | |

All 3 missed by the union had no object (“continue,” “push and create pr,” “why does it look like two started”). In actual use, they are covered by the recent work and running work sources (in this test, memory and messages came from two separate periods, so these two sources were empty).
Identifier spelling errors: Only 2 messages could hit an exact identifier match in memory. After one character was deleted, both still retrieved the original work; using vectors alone lost both—consistent with the expected direction, but the sample is too small.
The first call averaged 1.3k input and 0.12k output tokens. Another finding: The object index included only modified files. Files read during research work were not included, and the files users name are often ones that were read but not modified.
(A previous test on 534 new messages from 10-12 to 10-26 had only 13 entry points and noisy annotations, so no conclusion was drawn.)

After integration into the pipeline (`flow='v2'`), the old and new processes were each replayed twice on the same week's data (new: g1, g2; old: f8, f8b):

| | Old f8 / f8b | New g1 / g2 |
|---|---|---|
| Work thread precision/recall 10-05..08 (A) | 0.558/0.872, 0.497/0.892 | 0.605/0.896, 0.564/0.873 |
| Work thread precision/recall 10-09..11 (A) | 0.545/0.735, 0.546/0.733 | 0.637/0.730, 0.413/0.615 |
| P-exec ic7 correct (50 points, two judgments) | 35, 34; 33, 34 (average 34.0) | 36, 30; 31, 31 (average 32.0) |
| P-exec lc7 correct | 30, 30; 31, 28 (29.75) | 32, 29; 28, 28 (29.25) |
| Calls per message／input tokens | 3.23／21.1k, 3.24／21.6k | 3.01／15.8k, 3.01／16.0k |
| Critical-path latency median／p90 | 12.4s／21.5s, 10.7s／19.4s | 5.6s／8.4s, 5.6s／8.5s |
| Second delivery call | — | 4, 9 times (about 1%) |
| Writes: task constraints／object constraints／decisions／guidance | 22/181/461/22, 29/178/453/20 | 65/173/361/56, 67/167/356/57 |

- The decline in g2 on 10-09..11 came from an early misjudgment being locked in by the replay's simulated interface selection: several very short progress questions (with several items of work in parallel, and the previous turn in the message stream being a reply from another session) were delivered to the wrong work.
  The simulated selection then chose the wrong node based on “the node CTM used most for this work,” and dozens of turns followed it there. The two replays diverged starting with short messages of this kind; individual replays vary greatly.
- Points where the new process was clearly worse in P-exec: It delivered to another, recently active item among a family of work on the same object; g2 created “batch download channel audio” as a research entry (read-only, unable to do the download).
  The delivery prompt now states explicitly: Research is only for obtaining information or conclusions; downloading, fetching, and archiving external content are output-producing work. When choosing research, it must specify the entry to continue or new.
- Memory (E1/E3 holdout set, 250 messages): When memory was called for every message, constraints were 1.00 and decisions 0.927 (sol; argon 0.974/0.78), versus 1.00/0.878 for the old understanding v9d and 0.974/0.951 for v8.
  The delivery call was once made to also judge “is there anything to remember,” calling memory only when true: decisions fell to 0.805 (0.829 after rewriting the instructions)—what it missed was the user choosing one of several approaches or changing the original plan.
  This judgment has been removed; memory is called for every message (not on the critical path).

### Round Seven (Continued): No Longer Using sol; Object Families Ranked by the Delivery Call

User decision (2026-11-03): Do not use sol series models anywhere in the project; CTM and evaluation use only `gemini-3.8-flash` and `gemini-4-argon`; `common.llm.chat` rejects sol model names.
Annotations previously made with sol are retained as data. CTM defaults: flash for the first step (pointing and objects), argon for delivery, memory, and other calls. In evaluation, flash is used for execution plans and argon for judging.
Memory capture matching has also been changed to argon (therefore slightly favoring argon).

Design: The quota for the object source is counted by object. Each object brings in the entire family of work that has touched it (up to 8 items per object, 30 total). The delivery call sees them grouped by object,
and ranks and selects them after comparing each item's purpose, current state, and what the user recently said to it. Scores or time are not used to pick for the LLM; alternatives are output (one or two less likely items), and the reply displays “it could also be...”; if delivered incorrectly, click once to redirect it.
Advancement, control, and status inquiries without pointing are delivered to the current work (the one the user last exchanged messages with). Object vector similarity is now computed and cached using numpy matrices (pure Python was too slow with more than a thousand objects).

Test (memory from 10-05..08, raw messages from 10-09..11; 28 entry points returning to old work, 148 messages both annotations considered not to point to old work):

| First step → delivery | Candidate recall | Selected | Selected or alternative (top 3) | Incorrectly attached to old work | Requested a second call |
|---|---:|---:|---:|---:|---:|
| flash → argon (first call only) | 23/28 | 16/28 | 17/28 | 13/148 | 273/339 |
| flash → argon (including second call) | 23/28 | 20/28 | 26/28 | 39/148 | |
| flash → flash (including second call) | 23/28 | 23/28 | 24/28 | 58/148 | 27/339 |
| argon → argon (first call only) | 23/28 | 16/28 | 19/28 | 16/148 | 269/339 |

- This test set lacks “recent work”: The first two turns of the session containing the messages discussed work newly created that day, which was not in memory. Argon saw that the work being discussed in the context was not among the candidates and requested the full tree about 80% of the time;
  still unable to find it after seeing the full tree, it picked an item from old work, increasing incorrect attachments. In real operation, recent work is among the candidates, so both second calls and incorrect attachments will be far less frequent; replays are needed to measure them accurately.
- Flash tends to reconnect to old work (more selected, but also more incorrect attachments); argon is conservative. The cost of an incorrect attachment (that work absorbs content that does not belong to it, and the executor carries an unrelated scene) is greater than a missed reconnection (create new, still with context from the path and siblings), so delivery uses argon.
- All 5 missed by the candidates had no usable object (“continue,” “still not decided?” and so on); in practice they are covered by recent and current work. Only 2 had a target in an object family with multiple items of work, so this data set cannot test ranking within families.
- Memory (E1/E3 holdout set, matching with argon): sol 1.00/0.927, argon 0.974/0.805, flash 0.974/0.829 (constraints/decisions). Argon and flash recorded only a little over 60% as many decisions as sol.
  The memory prompt needs to be modified for these two models on the development set.

claude-opus-5.5 (user requested testing): The project's own Copilot license has no Claude models; it can only be called through pi's `loki` provider (a pi extension from another project).
`ctm2.model` added `pi:<provider>/<model>` routing: run pi CLI as a windowless subprocess (JSON mode, no tools, no session, no skills or context files, replace the system prompt, input via stdin).
Reasoning effort is set to low as with the other models. Same set of tests:

| | Constraints | Decisions (number of decisions recorded) |
|---|---:|---:|
| sol (reference, existing data) | 1.00 | 0.927 (116) |
| claude-opus-5.5 | 0.923 | 0.902 (106) |
| argon | 0.974 | 0.805 (76) |
| flash | 0.974 | 0.829 (71) |

| Delivery model (first step uses flash for all, including second call) | Selected | Selected or alternative (top 3) | Incorrectly attached to old work | Requested a second call | Average input | Per call |
|---|---:|---:|---:|---:|---:|---:|
| claude-opus-5.5 | 21/28 | 24/28 | 49/148 | 194/339 | 8.4k | Median 7.2s (including 2–3s pi startup) |
| argon | 20/28 | 26/28 | 39/148 | 273/339 | 5.7k | |
| flash | 23/28 | 24/28 | 58/148 | 27/339 | 5.8k | |

- For memory, opus is clearly better than argon and flash (7–10 points higher on decisions, close to sol), matching 2 fewer constraints. For delivery, opus is between flash and argon, no better than argon;
  this delivery test set lacks the day's new work. The 22 “incorrect attachments” shared by all three models were mostly caused by the setup; delivery differences need replays to determine.
- Opus tokens are counted using Claude's tokenization; the same input is about 1.5 times the Gemini count. Each call through pi adds 2–3 seconds of startup overhead; a persistent pi RPC process is needed at runtime.

Memory prompt modifications for argon and flash (user chose option 2: do not depend on opus, modify the prompt first):
- Test data rotation: After each modification, switch to a batch of unused windows (`rotate.py`: select 5 windows from unused sessions, no more than 50 turns per window, mixing different sources where possible;
  two annotators unrelated to the system under test, claude-opus-5.5 and grok-4.7, each annotate constraints and decisions, and agreed items are used as the gold standard; constraints valid only for that message are not counted); no single run exceeds 30 minutes.
- Two scoring changes: Guidance also counts as remembered (conceptually it is also passed to the executor; most “missed” constraints on the development set were recorded as guidance); each gold-standard item is matched only against system entries within a few turns before and after it
  (previously, all entries in a window were given to the matching model at once, and even clear synonyms were missed, so the old numbers were low). Matching model: grok-4.7 (low).
- prompt V2: The decisions section was rewritten to cover purpose, the cost of missing and over-recording, and questions to ask oneself, and to describe common forms of user statements (rhetorical questions and challenges, item-by-item disposition, acceptance, specifying objects and locations);
  V3: When the user only questions the basis for an agent's conclusion without saying what to do, also record it as a rejected conclusion (future executors should verify it before use). Old versions are retained as `PROMPT_V1`, `PROMPT_V2`.

| Data | Model | V1 constraints/decisions | V2 constraints/decisions | V3 constraints/decisions |
|---|---|---|---|---|
| c (new, 221 messages) | argon | 0.952/0.855 | 0.952/0.909 | |
| c | flash | 0.905/0.764 | 0.905/0.873 | |
| c | opus | | | 1.00/0.964 |
| d (new, 250 messages) | argon | | 1.00/0.986 | 1.00/1.00 |
| d | flash | | 0.971/0.973 | 0.941/0.973 |
| d | opus | | | 1.00/1.00 |
| b (original holdout set) | argon | 0.974/0.805 | | 0.974/0.878 |
| b | flash | 0.949/0.829 | | 0.974/0.902 |
| b | opus | 0.949/0.878 | | 0.949/0.976 |

- The new prompt raises decision recall for argon and flash by 5–11 points; opus also improves under the same prompt and remains 7–10 points ahead (b, c). The agreed gold labels in group d are mostly explicit decisions. All three are close to a perfect score, so they cannot be distinguished.
- The amount recorded differs greatly (decisions recorded from 250 messages in group d: opus 275, argon 202, flash 131). Precision has not yet been measured.
- Most remaining omissions are in gray areas: replying with a single word to narrow the scope, stating a file location (recorded as a fact), and the work content of the current request.

Memory precision (V3 prompt; the new group e with 201 messages and group d; 60 messages with records randomly sampled from each group, with entries from the three models for the same message submitted together to grok-4.7 for blind evaluation,
with models concealed and entries grouped by source; evaluation criteria follow the concept model’s definitions of constraints, guidance, and decisions, and the decision type (rejected) is also provided):

| Group e / group d | Entries | Faithful | Of which, same content recorded in two categories | Not durable | Errors | Decision recall (e) |
|---|---:|---:|---:|---:|---:|---:|
| argon | 86 / 110 | 0.76 / 0.76 | 0.20 / 0.18 | 0.13 / 0.13 | 0.12 / 0.11 | 0.897 |
| flash | 67 / 87 | 0.75 / 0.76 | 0.15 / 0.13 | 0.18 / 0.20 | 0.07 / 0.05 | 0.974 |
| opus | 121 / 127 | 0.57 / 0.59 | 0.07 / 0.06 | 0.19 / 0.16 | 0.23 / 0.24 | 1.00 |

- opus has the highest recall, but about a quarter of its entries are wrong: it adds details, reasons, and scope the user did not state, and records the user’s clarification of their own meaning as rejection. Part of its lead in recall comes from writing more in this way;
  considering precision, there is no need to switch memory to opus. flash has the fewest errors (5–7%); its recall is no lower than argon’s in groups b and e, and slightly lower in group c.
- Problems shared by all three models: about 15% is content of the current request itself (not durable); 13–31% of decisions say the same thing as constraints from the same source—the prompt requires “record product rules stated in the language of choice as object constraints,
  and record the chosen approach separately as a decision,” which is redundant when passed to the executor; the new V3 instruction “also record questioning as rejected” is written more strongly than the user intended (“must not be relied on,” “not adopted for now”).
- The first evaluation instructions were inconsistent with the concept model (treating approval of a proposal and judgments about causes as request content), and did not provide the decision type (rejected entries were treated as adopted). These were corrected and the evaluation repeated; grok is the only judge, so the user needs to spot-check and calibrate it.

The user decided to switch memory calls to flash (`CTM(memory_model='gemini-3.8-flash')`; delivery still uses argon, and the first step uses flash). grok-4.7 was also added as a memory model, and gpt-6.1-sol was used as the judge at the user’s request
(sol serves only as a judge in the evaluation, and `CONTEXT_TREE_ALLOW_SOL_JUDGE=1` was set only for that run; CTM still rejects sol). Precision used the same 60 messages as the grok evaluation, and the recall comparison also switched to sol:

| Model | Faithful e / d | Errors e / d | Decision recall b / e / d | Constraint recall b / e / d |
|---|---|---|---|---|
| argon | 0.90 / 0.84 | 0.07 / 0.10 | 0.902 / 0.923 / 1.00 | 0.974 / 1.00 / 1.00 |
| flash | 0.91 / 0.87 | 0.06 / 0.01 | 0.902 / 0.974 / 0.959 | 0.949 / 1.00 / 0.941 |
| opus | 0.72 / 0.70 | 0.19 / 0.19 | 0.976 / 1.00 / 1.00 | 0.949 / 1.00 / 1.00 |
| grok | 0.82 / 0.83 | 0.10 / 0.11 | 0.927 / 0.949 / 0.986 | 0.974 / 1.00 / 1.00 |

(Half of the gold labels in groups e and d were annotated by grok, so grok’s recall on these two groups is biased upward; use group b as the reference.)
- grok as a memory model: decision recall in group b is 1 item higher than flash (out of 41), and its error rate is comparable to argon’s, but it records the most and records the same content in two categories most often (41–50% of decisions). It does not outperform flash.
- Judges: on the same set of 598 entries, grok and sol agree on 74% of judgments and 80% of “faithful or not” judgments; when they disagree, grok is stricter (53 entries judged not durable by grok and valid by sol, 35 judged erroneous by grok and valid by sol).
  The two judges give the same model ranking (flash≈argon＞grok＞opus). Which is closer to the user’s standard requires the user to spot-check entries on which they disagree.

### Block A (delivery): Measurement with reference memory

Method (`research/eval-corpus/blockA.py`): S2 message stream (10-04..10-26, 21 sessions). Before each test message, reference memory is built according to the annotated work structure and written through the production write function:
one node per annotated work item (named by flash using only its first message, without hindsight), previous messages as exchange records, objects extracted in the first step as mentions, files modified in tool records, and the end of the agent’s reply as the latest result.
Candidates and delivery inputs are generated by production code, so only delivery itself is measured. The current work is the work of the preceding message; only when a message points to nothing and the previous work item in its session is not the current work, the user is simulated as first selecting that work item on the tree.
Data split: development set 10-12..10-18 (389 messages), test set 10-19..10-26 (362 messages).

Labels: the original annotations were made by session (a message was often assigned to the work underway in its session), which did not match the target scene; messages switching work or starting new work were reannotated by opus and grok according to the concept model (belonging to existing work, a side question and the work it asks about,
new work and its parent work or preceding step), and their agreed items were used as labels. The first version of the annotation instructions had no “side question” category, so queries and follow-up actions were labeled as new work. This was corrected and the messages reannotated.

| argon, delivery instructions V1 (development set / test set) | Delivered to correct work | Relaxed to parent or child | Top 3 | Other |
|---|---|---|---|---|
| Continue current work | 0.97 / 0.97 | 0.98 / 0.97 | 0.99 / 0.99 | |
| Return to other old work | 0.66 / 0.76 | 0.83 / 0.88 | 0.95 / 0.98 | New work created in error 0.07 / 0.10 |
| New work | Recognized 0.86 / 0.72 | | | Attached to old work in error 0.14 / 0.28; attachment reasonable 0.68 / 0.75 |
| Side question about another work item | 0.66 / 0.77 | | | Treated as a side question rather than work content 0.52 / 0.57 |

- A second delivery call occurs about 0.5% of the time; each call uses about 13–15k input tokens, with a median of 6 seconds.
- Delivery instructions V2 (adding a criterion for “whether to create a node”: the next action in the same work is a continuation) reduced erroneous creation of new work, but on the test set erroneous attachment of new work rose from 0.28 to 0.34 and delivery of side questions to the correct work fell from 0.77 to 0.67.
  There were slightly more total errors, with the increase consisting of more costly erroneous attachments, so V2 was not adopted (retained as `deliver.PROMPT_V2`). With the same instructions, new-work recognition differed by 0.14 between the two data sets; tuning instructions on only one data set can be misleading.
- Nature of the errors: of about 46 messages delivered incorrectly when switching, 17 landed on the parent or child of the labeled work (a difference in granularity), 14 were created as new subtasks under the labeled work, 12 involved a choice between adjacent work items, and 3 had no target among the candidates;
  when new work was attached to old work, it was almost always attached to the parent or preceding step specified by the label (development set 6/8, test set 12/13), treating a new subtask or next step as a continuation of its parent—still a choice of granularity, with the content entering precisely that work item’s session.
  Only 3 were actually attached to unrelated work (all related to the simulated interface selection).
- **Reannotation according to the CTM scene (replacing the above labels affected by source sessions)**: The above two rounds of labels had information from source sessions—the reference memory and messages marked “continue current work” reused the original session-based annotations,
  and hindsight evidence for reannotation came from later messages in the same source session. Annotation was changed to follow the CTM scene (goals-and-method 3.2): annotators see only earlier messages in this conversation and the work each was delivered to, the memory at the time,
  and the interface state (current work and simulated selection); hindsight evidence comes from subsequent messages in this conversation. All test messages were reannotated. The two annotators agreed on 310/389 and 301/362, of which about 75–79% matched the original session labels.

| argon, V1 (development set / test set, CTM scene labels) | Delivered to correct work | Relaxed to parent or child | Top 3 | Other |
|---|---|---|---|---|
| Belongs to current (or selected) work | 0.97 / 0.94 | 0.98 / 0.94 | 1.00 / 1.00 | New work created in error 0.02 / 0.06 |
| Belongs to another old work item | 0.79 / 0.85 | 0.88 / 0.92 | 0.97 / 1.00 | New work created in error 0.12 / 0.06 |
| New work | Recognized 0.83 / 0.78 | | | Attached to old work 0.17 / 0.22; attachment reasonable 0.76 / 0.70 |
| Side question about current work | 0.98 / 1.00 | | | Treated as a side question 0.82 / 0.71 |
| Side question about another work item | 0.83 / 0.87 | 0.87 / 0.91 | 0.91 / 1.00 | Treated as a side question 0.70 / 0.57 |

  V2 on the test set: 0.90 for belonging to another old work item, but 0.63 for new-work recognition, 0.78 for correct delivery of side questions, and 0.43 for treating them as side questions, so it is still not adopted. The reference memory itself retains the originally annotated work structure (with session bias); it is an input to the system under test, not a label.
  Main weaknesses: new work is merged into old work (about 20%) and side questions are treated as work content (0.57–0.82 treated as side questions).
- Conclusion: argon with delivery instructions V1 is already at a reasonable level in block A; the remaining differences are mainly choices of granularity and between adjacent work items, and alternatives (top 3 at 0.95–0.98) make the cost of redirecting delivery very low.
  Variation between data sets is greater than the potential gain from further changes to the instructions. Block A is paused, and work moves on to block B.

### Block B (memory write): measurements of item-by-item runs and replacement

Method (`research/eval-corpus/blockB.py`): Run memory on each item in sequence within each window of the rotating data. Current items accumulate gradually, so replacement can be measured. The replacement labels are pairs in the gold-standard items that two independent annotators
(opus, grok) both identified as “a later item replaced or revoked an earlier one.” Replacement judgment is also measured separately using reference input: the gold-standard items before a given turn are used as current items, and the gold-standard items in that turn as new items.

- Extraction (group f, flash): V4 has higher recall than V3 (constraints 0.92 vs. 0.88, decisions 0.933 vs. 0.889), but most of the additional “guidance” consists of approaches for this request only (not durable); V5 states that “approaches specific to this request only are passed to the executor with the original wording, not recorded as guidance.”
- Replacement (V4, replacement judged within the memory call, five groups b–f): Of the 25 gold-standard pairs, both items were recorded for 21 pairs, but only 10 pairs were recognized; the system made 98 replacements in total, of which grok judged 40 wrong (25 wrong out of 40 in group c).
  An erroneous replacement can mark a still-valid requirement as “do not use again,” which costs more than a missed replacement (when missed, both items are passed to the executor, and the execution context follows “newer takes priority”).
- Cause: A single call both extracts items and compares them against all current items, making pairings casually. Changed to V5: the memory call does not include current items or judge replacements; afterward, each new item is compared only with the 5 current items closest in vector similarity (`check_replacements`).
- Comparison with reference input (development groups b, c, d: 17 pairs; test groups e, f, g: 12 pairs): flash with V1 instructions recognized 10–12 / 10, with 3 / 5 erroneous replacements that discarded valid requirements; argon V1 recognized 12 / 9, with 8 / 5;
  V2, which adds “partial replacement” (retaining the unchanged parts of the old item): argon recognized more (14–15 / 11) but also made more erroneous replacements (12–14 / 5); flash V2 was indistinguishable from V1 (7 / 2). Use flash with V1 instructions for comparison.
- Full process (group g): V5＋flash comparison vs. V4: faithful 0.66 vs. 0.56, not durable 0.33 vs. 0.42, decision recall 0.903 vs. 0.968 (about 2 items), erroneous replacements 2/8 vs. 4/18; memory input 2.7k (plus one comparison of about 0.7k for 45% of messages) vs. 3.5k. Adopt V5＋flash comparison.
- One window in group g was blocked by the organization’s data loss prevention policy (it contained sensitive content). It has been removed from group g and will not be sent out.
- Attachment location and constraint type (reference memory from Block A development groups, 352 messages delivered to their work according to the annotations, flash V5 recorded 122 constraints and 22 guidance items; opus and grok each judged where each item should be attached):
  The two annotators disagreed on type in 37% of cases (the boundary between object constraints and task constraints is itself unclear); of the 65 constraints they agreed on, 48 were classified correctly (0.74), task constraints were attached at the correct level 23/24, and guidance 10/11.
  Almost all type disagreements were “annotated as a task constraint, recorded by the system as an object constraint” (15 items): most were specifications of the artifact itself (tables in a report, output format, interface behavior). The system was following the rule established in the sixth round:
  “When the user specifies what the artifact should be like, it is an object constraint, even if expressed as a choice.” The annotation instructions had not included this design rule. The genuinely incorrect judgments were requirements limiting the scope or approach of this work
  (what not to do this time, keeping the original logic unchanged, preserving the original structure during this update), about 4–5 items (7–8%). Attachment is not a major problem.
- **Retest in the CTM scenario (replaces the single-session window results above as the primary basis)**: The group c–g windows above came from individual sessions, and both the annotators and the memory call saw the context of that session.
  Instead, windows were taken from an interleaved message stream (`blockB2.py`: development dev1, dev2, test test1, test3, each about 80 turns, interleaving 4–6 sessions; test2 contained sensitive content and was blocked by the data loss prevention policy, so it was excluded).
  Each message was delivered to its work in the reference memory. The memory call saw the last few turns of that conversation and the previous reply (the same as in the pipeline). The annotators saw that conversation and the work to which each message was sent; subsequent evidence was taken only from later messages in that conversation.

| Four windows | V5 (focused comparison after extraction, current) | V4 (replacement judged within the memory call) |
|---|---|---|
| Constraint recall | 31/32 | 31/32 |
| Decision recall | 70/71 | 68/71 |
| Faithful (30 messages per window, grok) | 0.56 / 0.72 / 0.82 / 0.83 | 0.61 / 0.52 / 0.69 / 0.76 |
| Incorrect items | 0.05 / 0.03 / 0.11 / 0.00 | 0.03 / 0.12 / 0.19 / 0.06 |
| Replacements made by the system (correct／incorrect) | 16（11／5） | 37（20／17） |
| Gold-standard replacement pairs recognized | 4/11 | 7/11 |

  The conclusion remains unchanged: V5 maintains recall, makes fewer errors and far fewer erroneous replacements, at the cost of recognizing fewer replacements; retain V5. During the retest, the comparison call was found to sometimes return repeats as a list; `check_replacements` now handles this. This concludes Block B.

### Block E (control layer): retest after changing models

E7 test set (agreed gold standard for 190 executor stops, including the user’s actual subsequent replies). Previously only sol had been tested, and the test script used the default V1 instructions, while the pipeline actually uses V2 (actions already authorized by the user’s original wording are allowed through directly); this time the retest used V2:

| Model | Stop type | User gave a substantive response but the executor was allowed to continue on its own (harmful) | User replied only “continue” but it was reported |
|---|---:|---:|---:|
| sol (V1, previous) | 0.90 | 2/151 | 15/19 |
| argon (V2) | 0.84 | 5/151 | 14/19 |
| flash (V2) | 0.82 | 4/151 | 15/19 |

- All harmful cases of continuing on its own are a cost of the policy for allowing actions through: the executor asked “Should I start?／Should I commit and push?”, the user’s original wording had already authorized it, and the control layer allowed it through, but the user actually replied with a correction or addition (about 2.6%).
- The main confusion in type classification is judging a question as “no question.” In that case, the control layer forwards it to the user as a completion report, and the user can still answer, so the cost is small.
- Most cases where a reply of only “continue” was still reported were requests for permission or for the user to choose, which by design should be passed to the user.
- The control layer switches to flash (no more harmful cases of continuing on its own than argon, cheaper and faster); the instructions remain unchanged. One of the gold-standard annotators was argon, which favors argon; the conclusion is unaffected.

### Block F (result writeback): progress summaries

After each execution, CTM writes a brief progress summary. A new executor cannot see the old session and will treat it as fact. Executor responses were sampled from rotation windows (including requests and tool records), each model wrote summaries, and grok judged them against the responses and tool records:
fabrication (content supported by neither the response nor the records), omissions (points needed for taking over but missing from the summary), and whether verification status was labeled correctly (“trace” if there was a tool trace, otherwise “self-reported”).

- 80 responses from groups e, f, and g (problems found): about 30% of summaries by both flash and argon contained fabrication—speculating about reasons not stated in the response, describing something for which the executor had already made a recommendation as “requires a user decision,” and labeling details supported by only one call as “trace”;
  omissions were mostly specific details (which by design remain in execution records and documents), but research work lost the conclusions themselves.
- Instructions V3: write only what is in the response and tool records, do not speculate, and leave out anything uncertain; include the conclusions reached in “what was done”; list only pending items explicitly left in the response. 80 responses from groups c and d (unused):

| Configuration | Summaries containing fabrication | Summaries with omissions | Verification labeled correctly |
|---|---:|---:|---:|
| flash original instructions / V3 | 0.34 / 0.15 | 0.92 / 0.80 | 0.77 / 0.82 |
| argon original instructions / V3 | 0.23 / 0.11 | 0.78 / 0.68 | 0.94 / 0.88 |

- Adopt argon＋V3 (written after the response, not on the critical path; retained long-term for future executors, so quality takes priority).

### Block C (tree maintenance): on a tree built by CTM itself

Maintenance organizes a tree built by CTM itself, so the complete process was first run (flash＋argon, progress summaries with argon V3, executors using historical responses) on the S2 message stream from 10-13 to 10-14 (148 messages), with maintenance every 12 hours (message time).
The tree was saved before and after each maintenance run (`blockC.py`, resumable). The standard was based on the CTM scenario: opus and grok each read the 148 messages in this exchange and annotated what work there was, which work each message belonged to, and which work was part of which;
scoring used only message pairs on which both agreed (same work／same work line), with an agreement rate of 0.96. The parent-child relationships in the reference memory came from the original session-based annotations and were no longer used as the standard here.

- Cold start (starting from empty memory): precision for same work was only 0.26—work already in progress before 10-13 had no nodes, so subsequent messages about it could only be merged into the work at the time; this was an artifact of the test setup.
  Changed to start from the state of the reference memory at 10-13 (warm start).
- The real problem exposed: when a series of inquiries later developed into a work item, the inquiries remained under the work alongside them at the time (as side questions), and the background was not present under the new work once it was created; maintenance could only move nodes, not messages within nodes.
  → Maintenance instructions V6 added move_messages (reattach to existing work) and split (split off a new node). Constraints, decisions, mentions, and execution summaries for the turn written from these messages move with them; messages reattached by the user in the interface are not moved (concept 5.6).

| Warm start | Same work (precision／recall) | Same work line (precision／recall) |
|---|---|---|
| w1 first maintenance (V5: create parent, rename) | 0.81／0.98 → unchanged | 1.00／0.77 → 1.00／0.97 |
| w1 last maintenance (V6: reattach 4, create parent, attach research, change status) | 0.73／0.88 → 0.81／0.93 | 0.93／0.94 → 1.00／0.98 |
| w2 first maintenance (V6: create 2 parents, reattach 1) | 0.81／0.98 → 0.82／1.00 | 1.00／0.75 → 1.00／0.96 |
| w2 last maintenance (V6: reattach 3, create 2 parents, attach research, change status) | 0.76／0.90 → 0.80／0.91 | 0.93／0.94 → 0.99／0.96 |

- grok judged each change: 7/8 message reattachments were reasonable (all were background that began as inquiries and later led to code changes or query work); 5/6 parent creations were reasonable; both cases of attaching research were judged unreasonable (too few cases, so no change for now);
  the same status change received inconsistent judgments in the two runs.
- Conclusion: maintenance brought the tree closer to the actual composition of the work (the first grouping raised same-work-line recall by about 0.2, and reattaching messages raised same-work precision by 0.03–0.08), with no obvious harm observed; adopt V6.
- Held-out data (w3, 10-15 to 10-18, 163 messages; two annotators agreed at 0.94 for same work and 0.71 for same work line): V6 maintenance runs—reattach 1＋create parent＋rename: same-work recall 0.99→1.00; create parent＋split: same-work precision 0.88→1.00; create parent＋attach 2 research items: same-work-line recall 0.91→0.92; final reattachment of 2: same work 0.62／0.95→0.67／0.99; same-work-line precision remained at 1.00 throughout. grok judged reasonable: reattachments 3/3, splits 1/1, research attachments 2/2, parent creations 2/3, renames 1/1.
- In the overall run for the test period (t1, 10-19 to 10-21), each of 4 nodes mixed in 2–4 work items separated by the annotators: the user requested new outputs one after another on one line, delivery treated all of them as continuations of the current work, and V6 maintenance split only once. Instructions V7, which judged splits by output, were tried (`maintain_store.PROMPT_V7`, retained as a negative result): one full-period maintenance run was performed on each of the final memories from development data w2 and w3. V7 did not split these nodes and instead created additional common parents judged unreasonable (all three changes in w3 were judged unreasonable; w2 work-line precision 0.99→0.93). It was worse than V6 and was not run on the test data. V6 remains in use; this problem is left to be measured through user splits in real use.
- Delivery on CTM's own tree: about one quarter of messages labeled “belongs to existing work” were treated as side questions, and about 40% of new work was merged into old work (under cold start, including artifacts); delivery statistics under warm start remain to be examined together after block D.

### Block C (continued): structure judgment—looking back at the existing structure (2026-11-12)

Problem: the tree imported from three months of history had almost only two levels (196 at the top level, 72 sub-work items under the largest parent). According to the code mechanism, hierarchy comes only from delivery (attach under the work it belongs to among the candidates; “next step” is attached alongside the previous step,
so for a large work item starting under the root, all subsequent steps remain under the root), purposes stated by the user, and maintenance—and maintenance looks only at records since the previous run. For parts of the same larger work item that the user proposed over days or weeks,
there was no mechanism to revisit them: the user had repeatedly said “the tree is dynamic and needs regular correction” and “every time a new task is created, consider whether the last few tasks are subtasks of one task,” but when the concept was written, this was narrowed to “common parents are created by maintenance according to the window.”

Implementation (concept 3.4, 5.6): a **structure judgment** (`maintain_store.structure`, argon) looks at all work on one level of the tree (the top level of a project, or under a work item) and creates a parent when several items are parts of the same concrete work item.
It is not a step for every message. It is triggered in two places: when delivery provides a signal (`same_work_as` in `deliver.PROMPT_V3`, or new work is the next step of work under the root), it is called after the executor starts and the memory write is complete;
during maintenance, for levels involved in the batch of records to which at least 2 work items have been added since the last judgment (`changed_levels`, bookkeeping, not a semantic judgment). Working directories are normalized before separating levels (`wd_key`).

Tests (`blockS.py`, annotation: opus and grok each grouped each level and paired items according to “the same larger work item”; cases where the two disagreed were not counted):

| Instructions | Data | Precision | Recall |
|---|---|---|---|
| V1 | Imported flat tree, 8 development levels／8 test levels | 0.39／0.20 | 0.89／0.54 |
| V2 (small groups first), V3 (not classification, write one output) | Development | 0.27、0.26 | 0.95、0.93 |
| V4 (a group is one concrete work item, not grouped by phase) | Development／test | 0.90／0.83 | 0.78／0.51 |
| V4／V5 (create parents only, no attachment) | Tree built by CTM itself on S2 (w4, 12 levels, new data) | 0.92／0.91 | 0.80／0.82 |

- V1–V3 grouped almost every work item on a level into a “phase” (the title had to list several things separated by enumeration commas). This is exactly the kind of grouping that spreads constraints and the scene; starting with V4, only items belonging to the same concrete work item are grouped.
- Attachment (attaching one item under another on the same level, including research and testing “in service of it”): correct for half (8/15) of the pairs on which both agreed in blockS; judged unreasonable in 8 of 9 cases during maintenance. Delivery's parent and maintenance's set_parent already cover this situation. V5 removes attachment.
- Maintenance trigger: when the signal was put into the maintenance instructions (V8: instructions before the output format; V9: appended after V6), maintenance status corrections fell from 6–8 to 0–3 per run (w4, two runs each), direct evidence of “doing too many things in one set of instructions”; V8 and V9 are retained as negative results.
  Changed to leave the maintenance instructions unchanged (V6) and call structure judgment based on “how many work items have been added to this level”: in two runs, maintenance's own changes matched V6, and grok judged 20 of the 25 parents created by structure judgment reasonable.
- The imported tree (`D:/ctm`) was reorganized with V5: the previous unevaluated organization (107 at the top level) was discarded and redone from a backup—top level 196→164, largest parent 72→16, nodes 614→662; V5 is conservative, and the rest will be revisited level by level in future maintenance.
- Delivery signal (`same_work_as`): on new block A data (early, 10-08 to 10-11, 439 messages, annotation RELABEL3 plus same_work_as), the differences between delivery V3 and V1 across all accuracy categories were within noise
  (current work 0.93→0.94, other existing work 0.87→0.87, new-work recognition 0.89→0.93, side questions 0.93→0.90 (n=40)); however, the parents in the reference memory came from retrospective annotation, the larger work items already had nodes, and the two annotators found no cases of same_work_as,
  so this data could not test the signal itself. The signal was tested on a tree built by CTM itself (w5: 10-22 to 10-26, delivery V3＋signal, maintenance V6, compared with w4).
- w5 (10-22 to 10-26, 162 messages, warm start; only delivery changed: V3＋signal, maintenance still V6) compared with w4: same-work-line precision／recall 0.96／0.994 (w4 0.96／0.992); same-work precision 0.36→0.61 (single run, mostly likely because V3 was more willing to recognize new work, not an effect of structure judgment); the signal triggered 2 structure judgments (among 162 messages), and both grok and opus judged the 2 parents created reasonable; structure judgment used about 9,500 input tokens in total.
- Adopt: delivery V3＋signal, structure judgment V5, level-based triggering during maintenance; maintenance instructions V8／V9 (putting the signal into the maintenance instructions) are retained as negative results.

### Block C (continued, part 2): Goal and Attachment (2026-11-12)

The user looked at the reconstructed tree: the top level should be Goal, cleanup and the like are not goals, and parent-child relationships between tasks are not containment relationships. A check (`D:/ctm`): there was not a single Goal in the tree. All 164 top-level nodes were Tasks, 95 of them one-off small tasks or research with no child nodes; during import, parent nodes created from “things done in one session” listed several things separated by enumeration commas, with child nodes mixing wrap-up and incidental investigation; import and structure judgment treated the working directory as a hard boundary
(none of the 498 parent-child pairs crossed directories), while delivery could not see the candidates’ working directories at all. The reason: the concept said “one-off tasks that do not yet belong to a Goal can be attached under the root first” and “create a Task-level parent for an inferred purpose; promotion to Goal requires user approval,”
so in practice there were no Goals; the import instructions for dividing work counted “asking for another deliverable after one deliverable” as another item of work, and wrap-up also became a node.

The concept was changed: only Goals under the root (long-term goals; future work with the same purpose is also attached under them; Goals summarized by CTM have their source marked and can be changed by the user); Tasks under Goals; Tasks and subtasks have a containment relationship, and whether to split depends on the situation; wrap-up is continuation;
the working directory is a reference for judging whether work is the same task or a component, not a boundary; one Goal can cross directories. Implementation:

- **Goal judgment** (`assign_goals`, argon): given existing Goals and work not under a Goal (with working directory, time period, and result), decide the Goal for each item (an existing one or a newly summarized one), and merge Goals with the same goal.
  Annotation: opus and grok each assigned work started in one month to long-term goals (`goals_eval.py`), paired items by “same Goal,” and used B-cubed (each item of work has equal weight and is not dominated by large groups).

| Description | Development month (96 items) B-cubed P／R | Second development month (173 items) | Held-out month (210 items, not used for modifications) |
|---|---|---|---|
| Between two annotators | 0.92／0.79 | 0.71／0.86 | 0.74／0.69 |
| V1 | 0.54／0.98 | 0.58／0.90 | 0.25／0.98 |
| V3 (long-term requirements of the same kind; feature development, refactoring, capacity governance, troubleshooting, and tickets are each a Goal) | 0.87／0.87；0.68／0.90 | 0.58／0.90；0.63／0.80 | — |
| V4 (attach work under an existing Goal only when the goals are of the same kind; if a title needs “and” to join two categories, they are two Goals) | 0.76／0.84；0.73／0.96 | 0.66／0.73；0.69／0.64 | 0.55／0.81；0.55／0.75 |

  Two runs with the same instructions can differ by as much as 0.2, so single runs cannot be compared; the second development month was originally a test month, but after its errors were examined it was changed to development data, and another month in the middle was taken as held-out data. V1 put most of a project’s work into one Goal;
  V4 came close to the annotators’ Goal counts in the held-out month (21–23 versus 23–25), but precision was still lower than between the annotators—during periods when work is concentrated on one project, a broad Goal absorbs later work. V4 was adopted: a Goal that is too broad passes down unrelated constraints and scene and is hard to split,
  while Goals that are too narrow can be merged later.
- **Delivery V4**: give each item of new work a Goal (an existing id, or a newly summarized Goal; `stated` means the user stated the purpose); parent indicates containment only. Block A earlyg (constructed with reference to memory using the Goals that would have existed at the time, with Goals numbered using G to preserve work numbering):

| Description | New work recognized as new／correct placement | Side questions (other work) correct work／correct method | Correct current work |
|---|---|---|---|
| V3 | 0.87／0.65 | 0.76／0.49 | 0.94 |
| V4 (Goal added only) | 0.87／0.86 | 0.73／0.47 | 0.96 |
| ＋“wrap-up is continuation” | 0.80／0.92 | 0.76／0.49 | 0.96 |
| ＋“working directory is an important reference” | 0.85／0.85 | 0.71／0.39 | 0.96 |

  When all three changes were made together, new work recognition was 0.78 and side question method was 0.39. Examining them separately showed that the latter two sentences caused this: V3 already delivered wrap-up to the original work, and this sentence caused genuinely new work to be merged into old work as well; emphasizing the working directory caused incorrect judgments on side questions about other work.
  Only Goal was adopted; the latter two sentences were retained as negative results (`PROMPT_V4_ALL`); candidates still carry the working directory as data. Merely adding Goal and working directory to the input also reduced V3’s new work recognition from 0.93 (early) to 0.87; the cause remains to be investigated.
- **Redo import**: add “wrap-up belongs to that item of work; write parent only when it is part of that item of work” to the work-splitting instructions; cross-session merging merges only the same item of work and no longer creates summary parents; after writing, first perform Goal judgment (across directories, in batches by time),
  then group by containment under each Goal and each parent with many child work items. Three months of history: 501 items of work, 28 Goals, all top-level nodes are Goals, with 28／232／318／40 nodes per level; wrap-up nodes fell from dozens to single digits.
  The largest Goal (a server-side integration project) has 198 items of work (33 direct child nodes)—it was the main task during this period, and its size is not itself a problem; several general items of work in it (document organization, PR review notes) could reasonably be placed either under it or outside it. The agreement with the annotation groupings above (pairing, B-cubed) can only serve as a reference: structure has no unique answer, and scoring against one grouping will count another reasonable approach as wrong (Goals and Methods 3.2); in the future, evaluate by consequences (whether inherited constraints are relevant and whether the executor’s scene is useful). The old `D:/ctm` is backed up at `bootstrap/before-goals-20261112`.

### Instructions Changed to an Analytical Style (2026-11-13)

The user pointed out: instructions such as “the current task is not the default parent for new work” and “before attaching it, confirm that it is part of that item of work” are no different from writing code—instructions should not be a list of rules; they should get the LLM to analyze the relationships between nodes in depth;
moreover, structure has no unique answer (a task that is both work within a development effort and general work in its own right could reasonably be placed under that development effort or outside it), and the tree can be adjusted at any time. Looking back at the changes made that day, most added a rule to prohibit each class of error as it was observed
(Goal judgment V2–V4, structure judgment V2–V5, and the two sentences in delivery V4). As the user requested, switch directly to analytical instructions without comparing them with rule-based ones:

- Delivery V5, Goal judgment V5, structure judgment V6, and the import work splitting and merging: explain the uses of the judgment (inheritance of constraints, the scene the executor sees, the user finding their own work in the tree) and that there may be several reasonable approaches; provide the information needed for analysis;
  list the questions to think through (what the user is doing now, why this request was raised at this time, what is wanted, how it relates to each item of work, which long-term undertaking it advances); output analysis first, then the decision.
- Record for each item of work what the user was working on when it was raised (`raised_during`: for real-time work, the current work at creation; for import, the previous item of work in the same session). Work cards and Goal summaries include working directories, which are visible to both Goal judgment and structure judgment.
- Spot-check 24 delivery V5 cases on earlyg (12 new work, 6 side questions, 6 existing work): the analysis first makes clear what the user was just doing and what prompted the message, then decides placement (for example, “review all unit tests” prompted by the results of a test run is attached under that item of work);
  the few cases that differed from the annotators were another reasonable approach (external research judged as research, “has it stopped again” judged as delivery to the original work for verification). The analysis is occasionally long, adding about 150–300 output tokens per delivery.
- Evaluation changed to focus on consequences (Goals and Methods 3.2): whether the constraints inherited by a new execution are relevant, whether the long-term requirements that should be passed down are passed down, and whether the scene is useful; the user modifying the tree during a pilot trial is the most direct signal.
- Maintenance V10 was also changed to an analytical style, removing create_goal and create_parent, which overlapped with Goal judgment and structure judgment.
- Reimported three months of history using analytical instructions (`D:/ctm`; the previous version is at `bootstrap/before-analysis-20261113`): work splitting yielded 382 items, and merging reduced them to 231 (501 last time; wrap-up and follow-up questions are no longer separate items); 11,502 of 11,608 messages were assigned to work; 10 Goals (28 last time), 274 nodes, 10／73／147／42／2 nodes per level, at most 16 child nodes at one level; 280 guidance items, with 149 behavior guidance items assigned to 26 documents. During the first archiving, separate new documents with the same name were created within the same batch (71 documents, with as many as 5 of the same kind); this was fixed (only one document with the same name is created in a single call) and archiving was redone.

### Page Interaction (2026-11-13)

The user asked for no floating toolbars on the tree and for interactions to be designed according to UI best practices. Problems with the original page: eight or nine buttons appeared when hovering over each row (the available operations were not apparent, keyboard and touch could not be used, and accidental clicks were easy); clicking a node both opened the page and set it as
“deliver the next message here” (browsing changed the message destination); statuses had to be typed in English, and creation brought up two successive input boxes (native browser prompts); redirecting or reattaching a message required first selecting a node on the tree (which also changed the destination); there was no keyboard navigation, and the 274 nodes could not be searched.
Rewritten according to the WAI-ARIA APG tree view pattern and common file tree practices (page changes only, API unchanged):
- Tree rows have no buttons. They show only the expand symbol, status dot, title, and permanent markers (Goal, current, executing, send here, number of children when collapsed); a filter box (`/`) is at the top of the tree, and “Global” is the first item in the tree.
- A click only opens the page (selection is separate from “where to send”); operations have three entry points with identical contents: a fixed action bar at the top of the page, a context menu (also available with Shift+F10), and keyboard shortcuts (arrow keys, Home/End, Enter, F2 to rename, `*`, jump by first letter).
- Drag and drop to move, with a notification offering “Undo” after dropping; without a mouse, use “Move to…” (a searchable selection box showing paths). Redirecting or reattaching messages and specifying a destination use the same selection box.
- “Send here” is an explicit toggle (on the page and in the menu). Above the input box, “Send to ‘X’ ×” or “Let CTM decide” is displayed. Merging cannot be undone and therefore requires confirmation; moving, renaming, and changing status can be undone; stopping execution and stopping work in progress require confirmation.
- Browser checks (`tests/browser_pilot_ui.py`, run on a copy, headless Edge): no buttons in rows, no toolbar on hover, clicking does not change the destination, context menu and Esc, expanding and collapsing with arrow keys, F2 rename and cancel, filtering, selection box, status menu,
  specifying and canceling a destination, creation form, drag and drop and undo, global page. All 24 checks passed, with no page errors.

### Automated Evaluation: First Round (2026-11-18)

For the method, see Goals and Methods 3.5. Scripts are in the research directory (`eval-corpus/auto_eval.py`, `memorycode_eval.py`), and results are in `l3/auto/` and `l3/public/`. One command checks against new, unused data: `python auto_eval.py daily`—it takes new messages since the last evaluation, continues from the previous memory and replays them with the current default configuration, checks delivery consistency, context for new executors, constraint delivery, and cost, and writes the report to `l3/auto/reports/` (after an interruption, running the same command resumes; `latest.json` remembers where to continue). The judges are opus (via pi) and gpt-6.1-terra
(grok-4.7 takes about 5 minutes per block, terra about 35 seconds, with a similar level of agreement with opus); only items on which both agree are counted. The two agreed on 88% of classifications into the four categories “correction, restatement, change of mind, none.” Data: 351 user messages from 11-12 19:20 to 11-18
(replayed from an imported snapshot of `D:/ctm`), aider conversations in public repositories (tusk-posthog 102 messages, CPSC-370 63 messages, WazuhX 58 messages, replayed from empty memory), MemoryCode.

- **Correction points do not measure CTM**: The user had 73 correction points this week. Of the 59 for which both judges agreed on the cause, 51 were in the executor, 8 were changes of mind, and 0 were in CTM; the two aider users had 16, all in the executor. The user's original practice was to keep one session open for days,
  and corrections almost all occurred during repeated revisions in the same session. Correction points are now used to measure executors; CTM is measured by delivery, context for new executors, and restatement.
- **Delivery**: For adjacent messages in the same session, 231 of 260 pairs from the user this week (through message 275) were delivered to the same work item; among the rest, both judges found 4 pairs delivered incorrectly. For the three aider users, 0 pairs were delivered incorrectly (as agreed by both judges).
  An example error: the first message in the replay, “Update the document with the conclusions,” did not specify the object and was delivered to the current work at the time.
- **Restatement**: Almost all the content aider users restated when restarting sessions was already in CTM's context (tusk: 19 restarts, 30/33 and 28/29 items; CPSC: 9 restarts, 9/9 and 8/10)—with CTM, these things need not be said again.
- **Context for new executors**: How much of the earlier information actually used by executors in sessions is present in the context CTM gives new executors—76%–83% for aider users; only about one third for the user this week (research 12%, new work 37%).
  Reason: The user's sessions are long, and a work item progresses turn by turn in the same session; when CTM splits “continue working” into new work, or switches from research to hands-on work, details from the original session (paths, numbers, rules just decided, intermediate results) must be carried over in the context from siblings and references,
  but the implementation did not fully implement the provisions of concept 5.2 (see “Complete Execution Context According to the Concept” below). Splitting into new work is not itself a problem. In addition, each context has 4–7 irrelevant items, mainly recent turns of conversation from other work and empty sections.
- **MemoryCode**: When the mentor's words were combined into one message per session, CTM scored 0.47, full history 0.82, and no history 0.20—investigation showed that more than half of the problem was due to the adaptation method: the mentor's name had typos in the generated data, and the adapter dropped those messages;
  CTM understood the mentor's long monologues addressed in the third person as “a conversation transcript to process,” so memory did not treat the standards in them as requirements for itself. After changing to delivery by turn (each mentor passage as one message, and the newcomer's replies as executor replies),
  CTM and full history both scored full marks on conversations of 4–5 sessions, with context about 40% of the full history. But it exposed a real problem: when a message delivered outside any work (chitchat, side question) changed a global rule, the replacement check could not retrieve rules at the root,
  so both old and new rules remained in effect (fixed: retrieve current constraints at the root and on objects even when there is no target work; `test_ctm2_recent`).
- **Blocked requests**: Requests blocked by the provider (422) used to be retried 5 times, violating “do not retry blocked data”; changed to no retries.
- **Cost** (two aider repositories): 4.2–4.5 calls and about 10,000 input tokens per message (half on delivery), with a median time of about 21 seconds.

- **MemoryCode long conversations** (20 sessions): CTM 1/8, full history 8/8. The reason was that the coding standards stated by the mentor were recorded as object constraints, but the object (a way of writing code, a class of things without files yet) was not in any project directory,
  and had no writable files, so the constraints could not reach any executor. First, the code was changed to put object constraints without a work directory at the root: on the unused `dialogue_212`, CTM 3/4, full history 3/5, no history 0/5, with context about 7,000 characters versus 45,000 characters.
  But this is inconsistent with concept 3.5 (a specific object without files yet should remain on the work to which it belongs; a statement about how all code should be written is not an object constraint in the first place), and putting such constraints at the root would carry rules for specific objects into all work.
  So memory V6 states in its instructions what carries object constraints, and the code leaves object constraints without a directory on the work where they were stated (`OBJECT_NO_DIR='node'`): on the unused `dialogue_213`, CTM 2/3, full history 3/6, no history 0/3,
  with context about 6,700 characters versus 49,000 characters; memory directly records writing standards as global constraints (in V5, 18 items needed a code fallback; in V6, only 4 remain, all rules for a project without files yet, and leaving them on that work is correct).
  There are few scorable queries, so this only shows that it did not get worse; for whether rules for specific objects in user data were mistakenly recorded as global, see r4.
  On 11-19, two more unused conversations were run with the current defaults: `dialogue_214` CTM 4/4, full history 3/4; `dialogue_215` 6/6, 6/6; context about 8,000–12,000 characters versus 49,000–53,000 characters. Across the four conversations, CTM 15/17, full history 15/21.

**Complete Execution Context According to the Concept** (2026-11-18). The implementation was checked item by item against the initial context in concept 5.2. Three things were missing: siblings provided only 2 turns, executor replies were truncated to 800 characters, and all sibling exchanges were dropped together when the budget was tight
(concept: sibling results, decisions, and the original text of recent exchanges; when the budget is tight, reduce the parts farthest from the current work first); environment and location recorded on siblings, and conclusions to questions asked about siblings, were not provided; delivery never established cross-task references (Task→uses in concept 3.1), so when new work was based on conclusions from research or other work, those conclusions could not enter the context. In addition, research executors received only titles for related work. Changes: give the most recent sibling (the one the new work follows, or otherwise the one most recently
executed) the original text of the latest 4 turns (2,500 characters per reply), and other siblings 2 turns; when the budget is tight, drop exchanges from other siblings first and the most recent sibling last; include siblings' environment and location, and conclusions to questions asked about them; include cards and the last few turns of conversation for related work in research
(`context.SCENE_DETAIL`). Evaluation: on the final replayed memory, reconstruct old and new contexts for each new executor as of its original time (the similarity between time-reconstructed text and the original text at replay time was 0.97–0.99), and submit them to the same two judges:

**Paired Remeasurement (2026-11-19, replaces the original figures)**: The original check had judges list “needed information” while looking at their respective contexts. The two sets of items differed, so they could not be compared in pairs, and the figures were generous. Changed to `fresh_pair`: opus lists needed information using only the messages, actual replies, and content preceding the session; terra confirms each item, and items accepted by both are retained. The two then judge whether each set of context contains each item, counting only agreements ([plan](blocks-3-6-plan.md) task 1).

| Data | Points / items | Old: present / partial / absent | New: present / partial / absent | Median context |
|---|---|---|---|---|
| User this week r1 | 10／37 | 9%／59%／32% | 33%／52%／**15%** | 15.6k → 20.2k characters |
| User this week r4 | 11／41 | 28%／53%／19% | 30%／54%／**16%** | 16.5k → 20.5k characters |
| aider (tusk, todo-app2, pachis, October, VigInt) | 14／28 | Almost the same as new | | 13–19k → 19–22k characters |
| Total (agreed items) | 35／106 | 31%／48%／20% | 43%／45%／**12%** | |

The additions help: “absent” fell from 20% to 12%; the absolute levels of both sets are lower than originally reported. Most of the remainder is “partial” (about half): details are in long replies but not written in progress summaries. Two points were blocked by the anti-leakage policy and have been excluded. The number of irrelevant items is unchanged. Set as default. Cross-task references: delivery V9 (V5 plus `uses`: other work or research that new work needs but that is neither its parent nor the previous step), with the pipeline establishing references accordingly (`test_ctm2_recent`),
evaluated by replaying the user's data from this week (r4).

Delivery V6—specify the latest turns to attach verbatim when handing work to the executor (`uses_recent`; `select_recent` switch), and exclude empty sections from context (`context.COMPACT`)—**not adopted**: comparing r2 with r1 in the replay of the user's week,
308 versus 306 pairs of adjacent messages in the same session were delivered to the same work item, and 6 versus 5 pairs were judged misdelivered; median context for new executors was 10,500 versus 16,000 characters, with needed information “present” at 39–42% versus 39–40% and “absent” at 28–35% versus 23–32%;
irrelevant items did not decrease (the points in the two replays were not exactly the same, so this was not a paired comparison; the two judges agreed on the direction); cost was unchanged (4.72 calls and 17,800 input tokens per message). V8, built on V6, was replaced by V9
(V5 plus cross-task references), and r4 restarted with V9.
The first r4 run was invalidated: memory V6 did not perform a separate replacement check—the pipeline and memory calls branched on “whether the instructions are V5,” so switching to V6 reverted to the old practice of putting current items into the memory call and judging replacements within it (about 40% of replacements were judged incorrectly in the original evaluation). The input to r4 memory calls was therefore 2.5 times that of r1, with no replacement checks. Changed to a version list based on “whether replacements are judged separately” (`remember.separate_replacements`; `test_ctm2_recent`). r4 was rerun from the start with memory kept at V5, and memory V6 was moved to evaluation in block B.
Memory V6 compared with V5 in block B (test1, test3, dev1, dev2): constraint recall 30/32 versus 31/32, decisions 70/71 versus 69/71; replacements made by the system were rejudged by two judges (opus, terra), who agreed that 11 versus 8 were correct and 4 versus 4 were incorrect (the original scoring used only grok as judge and rejudged each time, yielding 9 versus 5 incorrect replacements; this was noise). Block B has no work directories, and V5's current practice put 78 object constraints at the root; V6 rerecorded 8 of them as task constraints and left the rest on their respective work. Zero new global constraints were recorded in the user's data this week. Set as default (`remember.PROMPT=PROMPT_V6`, `OBJECT_NO_DIR='node'`).
Compared with V5 on block A `earlyg` (439 messages, 353 agreed on by both judges), V9 did not harm delivery: continuing current work 0.96→0.97, returning to another old work item 0.92→0.92, new work identification 0.84→0.85, location 0.88→0.85,
side-question handling for current work 0.45→0.47, side questions about other work delivered to the correct work 0.71→0.76, handling 0.37→0.37. Two long-standing weaknesses remain: new work identification 0.84 (section 4, problem 9),
and side-question handling 0.37–0.47—questions about a work item are mostly treated as content of that work (concept 5.3: a query does not become content or progress of that work).
Compared against item 0 of concept 5.3 (when unsure, treat it as a query: treating a query as a task may make changes the user did not request; treating a task as a query requires only one sentence, “I want you to change it”): the delivery instructions only stated what a side question is, not the consequences and costs of the two approaches.
Delivery V10 = V9 plus this explanation: side-question handling for current work 0.47→0.80, for other work 0.37→0.63; the cost is continuing current work 0.97→0.92, returning to another old work item 0.92→0.87,
a total of about 26 more correct and 10 more incorrect. Most additional errors are corrections or checks phrased as questions (“Is it feasible?”, “Isn't it...?”, “It feels incomplete”), which the read-only branch answers, requiring the user to say one more thing before they become work—
this is a cost accepted by the concept. Set as default together after r4 confirms V9.
**r4** (user this week, delivery V9, completed sibling context, delivery sees failures and verification status, maintenance V11; memory V5): 294 pairs of adjacent messages in the same session delivered to the same work item (r1 306); most of the additional cases were side questions, research, and chitchat (26 pairs with no target work, r2 18); 6 pairs judged misdelivered (r1 5); 18 new executors, with needed earlier information complete 46–53%, partial 24–31%, absent 23–24% (r1 reconstructed by time: 40/39%, absent 32/23%), median 20,000 characters; 4.70 calls, 18,400 input tokens, and a median of 27.7 seconds per message, the same as r1. Only 7 cross-task references were established (4 work, 3 research); the case of continuing optimization after research (k=229) was treated in r4 as a continuation of that research and used the research's own session; when r1 created new work, 4 items of information were missing. Default from 2026-11-19: delivery V10 (including V9), delivery sees failures and verification status.
For consistency with the start, r4 fixed the fallback used earlier that day (object rules without a project directory placed at the root), so 49 new global constraints were recorded during replay, 48 of them such object rules; constraint delivery check: 16 new executors received 229 constraints, of which the two judges agreed that 111 were irrelevant (7 executors)—for example, “Do not use ‘five arts’ in external publicity and course websites” was given to unrelated troubleshooting and design work. r1 (mostly run before the fallback) had 0. This is precisely the consequence of putting such rules at the root; the current default (memory V6, leaving them on their respective work) will not do this.
Delivery V7 (V6 plus greater emphasis on the cost of mistakenly creating new work, `session: after` letting an immediate next step continue using the previous step's executor session) **withdrawn**: it bypassed the context prescribed by the concept through a shared session, which was the wrong direction;
the corresponding code has been deleted, and r3 stopped. This week's data has been used for diagnosis; the conclusions must be checked against new data next week.

**Sentence-by-sentence comparison of concept and implementation** (2026-11-18). The comparison table in Section 2 originally looked only at “whether it was integrated into the runtime flow” and did not check behavior sentence by sentence. Several items were rated too broadly. This time, each sentence describing “what CTM does” in Sections 3–6 of the concept was matched to the corresponding code.
Four places were inconsistent: sibling context in 5.2 (completed and set as the default); cross-task references in 3.1 and 3.4 (delivery V9, under evaluation); object constraints without a working directory had no carrier in 3.5 (memory V6 and `OBJECT_NO_DIR`, under evaluation);
status in 3.4—whether a task has ended “depends on the situation: the user’s acceptance, whether the purpose has been achieved, and whether work continued afterward,” whereas maintenance recognizes completion only when the user explicitly says so. Work therefore almost never ends, and folding upward and handing over to successors rarely happen
(maintenance V11, `STATUS_REVIEW_H`, see below). In addition, concept 5.2 did not cover one case: when returning to a work item and continuing its session, the message often builds on something just completed in another work item, which the original session does not know about;
added a switch to the turns named by delivery (only under `select_recent`, not adopted along with V6). The remaining sections are consistent, or have already been marked as partially complete in the table (knowledge documents are written by CTM rather than chosen by the executor, one-way links between documents and tasks, migration comments not evaluated, etc.).

**Judging completion status (maintenance V11, set as the default)**. V11 states in the maintenance instructions where status is used (when work ends, results are handed to the parent and successors; delivery uses it to decide whether to continue or start a new step; the user sees progress on the tree),
the costs of the two kinds of misjudgment and the basis for judgment (the user’s acceptance, whether the purpose has been achieved, and whether work continued after completion). It separates “reported complete,” supported only by the executor’s own statement, from “verified,” supported by traces. The input separately lists work that has not moved for more than 12 hours
but is still in progress (`status_review`, the code lists it only by time). Work cards include failures and verification (the first version lacked these: maintenance could not see failed edits and marked unfinished work as ended).
Evaluation: maintenance was run once 12 hours after each of six replays ended. Work still in progress at the end of each replay was independently annotated by two judges (ended and verified / ended but not verified / abandoned / unfinished). Only cases where the two agreed on “whether it ended” were counted:

| | Correct | Should have ended but was not marked | Unfinished but marked as ended | Verification status of ended work classified correctly |
|---|---|---|---|---|
| V10 | 25/43 | 18 | 0 | — |
| V11 | 36/43 | 2 | 5 | 18/19 |

In aider’s data, the judges disagreed substantially on work where “the changes were provided, but it was unclear whether they made it into the files” (terra judged it unfinished, opus judged it ended). These were not counted. The cost of marking work as ended too early is relatively small
(when the user returns, it is treated as a new step, and the new executor has its results and scene). Delivery also cannot see failures and verification (`tree.DETAIL_FAILURES`); to be evaluated with r4.

**Where the information still missing after completing sibling context is located** (17 points in r1, 65 items in total listed as “absent” and “partial” by the judges; vectors were used to find the most likely source among the previous 8 messages in the same session, then where that message had been delivered at the time was checked): 25 items in other Goals (mostly, after the first message was delivered to the wrong place, all the information needed by the next message in the same session was in that wrong place—the replay starts from a memory snapshot, whose “current work” and recent conversation were not from the user’s session at the time. The first message, “update the conclusions in the document,” did not specify the object. In a real single conversation, CTM could see the preceding follow-up questions; the design will not be changed on this basis), 18 items not delivered to any work (mostly switching from research to hands-on work—cross-task references in delivery V9 target this), 12 items in siblings (mostly “partial,” with details in earlier turns), 8 items in the work served by the research (the research executor receives that work’s card and the last two turns). 0 items in the same work itself.

**Recheck on unused data (2026-11-19)**: 4 unused aider users from public repositories (October 104 messages in 8 sessions, agentic 45 messages in 45 sessions, VigInt 29 messages, Colbeta 25 messages) were replayed separately from empty memory using the configuration before that evening’s changes (old) and the current default (new). Delivery: the two groups were almost identical for agentic, VigInt, and Colbeta; for October, new delivered exploratory questions and aider’s tool commands as side questions and chit-chat (87 of 96 pairs of adjacent messages had no target work, versus 1 pair for old). Under concept 5.3, these are queries. Restatement was changed to a paired check (`restate_pair`: items restated at the start of each session are listed only once from the user’s words, then two judges check whether each group’s context contains them): Colbeta 17/19 versus 17/19, VigInt 5/5 versus 5/5, agentic 237/238 versus 232/238 (the judges disagreed on another 6 items, with no agreed “absent” judgments), and October had no restatements. The previous check, which listed items separately for each group, showed “new is worse” for October; that was variation in the check itself, which is no longer used. Irrelevant constraints: VigInt 12/15→0/1, Colbeta 2/10→0/8 (both came from placing object rules without a directory on the root), October new 4/11 (coding rules for this project were recorded as global constraints). Cost: October 3.22→4.10 calls/message (routing of side questions and delivery expanded to the whole tree); the rest were unchanged.

**New work carries conclusions from relevant queries (delivery V11, 2026-11-19)**: Item 5 of concept 5.3, “Only establish a task when the user asks for an output or change after seeing the results; include relevant query results in the initial context,” was not implemented in the v2 flow (only v1 had `_carry_queries`). V11 provides queries answered within the last 12 turns in the delivery input. New work lists those it needs in `uses`, and “referenced decisions, research and results from elsewhere” in the context provides their conclusions (`pipeline._recent_queries`; `test_ctm2_recent`). For 4 unused aider users: delivery and paired restatement were the same as V10 (agentic 231/238 versus 232, Colbeta 17/19 the same, VigInt 4/5 versus 5/5). Queries were referenced only once in 203 messages—these users rarely ask before starting work. Set as the default; its effect will be checked through daily evaluation on the user’s own new data.

**Classification of behavior guidance, guidance, and constraints (2026-11-19)**: Two judges classified all items recorded when `D:/ctm` was imported according to concepts 3.5 and 3.6 (behavior guidance, guidance for work, constraint, global, one-time only). Of 98 behavior guidance items, the two judges agreed on 51, of which 24 were classified correctly (another 20 were judged one-time only, and the judges disagreed on 47—this boundary is itself unclear, so no change is being made on this basis). Of 280 work guidance items, the judges agreed on 210, of which 121 were classified correctly and 63 were actually constraints (for example, “confirm with the user before deleting other similar redundant checks”)—handing these to the executor as guidance means “consider this, not a hard limit,” and the executor may act without asking first. In runtime memory, few items in block B were recorded as guidance (18 in four V6 windows, of which 3 were constraints; 90% of those recorded as constraints were correct). The problem is mainly in import. Reclassification (`maintain_store.reclassify_guidance`, argon, with instructions stating how the two categories reach the executor and the cost of recording them incorrectly) had accuracy of 0.89 on the 184 items on which the judges agreed. Of those judged constraints, 58/73 were correct, and 58/63 actual constraints were found. It has been run on the 280 items in `D:/ctm`, with 104 changed to constraints (new constraints replace the original guidance, preserving history; backup at `D:/ctm/bootstrap/before-reclass-20261119`). The same cost description was added to import instructions `SEG`.

**Query routing changed to analyze first (ROUTE V2, 2026-11-19)**: On the 40 questions in the answer evaluation that the two judges scored consistently, only routing was redone. Correct answers delivered to the user and incorrect or unfound answers assigned to read-only execution were counted as appropriate routing—36 for current, 35 for analyze-first, a difference within variation. V2 was adopted according to project rules.

**New work inheriting sibling constraints on unused data**: Among 19 new executors in aider’s agentic, the judges considered 6 sibling constraints missing, but the inheritance judgment provided none (offline rerun was also 0/6). On inspection, these “messages” were task instructions assigned to aider by a multi-agent framework, each an independent small project. The judgment’s reasons (a different project, the original text already contained these requirements) hold up; the judges also counted requirements from similar projects as ones that should have been provided. This data cannot establish whether the approach is good or bad; it must be checked on the user’s own new data.

**Delivery V12 (uses and costs of expanding to all work) not adopted**: In aider’s October, aider tool prompts treated as user messages (“Add file to the chat? … skip”) were judged as chit-chat or side questions under V10/V11 and then requested scope expansion (47 times in 104 messages). On block A, V10/V11/V12 expanded scope 6/5/4 times (439 messages in total), with accuracy differing by one or two messages. The user’s data does not have this problem.

**Accuracy of answering from memory (Goal 4, 2026-11-19)**: Questions were generated by category from memory at the end of replay (decisions at the time, replaced decisions, rejected approaches, constraints, progress, whether work was completed, 8 questions each; terra generated the questions, with questions and reference answers taken from the records themselves). CTM’s query path was used to answer, and two judges scored the answers. Of 46 questions from the user’s week: with the original instructions, 26 were answered correctly, 4 incorrectly, and 5 were absent from memory. Of the 5 incorrect questions, 2 had a rejected approach written as the reference answer by the question generation (the question-generation input has been changed), 2 did not retrieve the current decision or new decision, and 1 was ambiguous. It was also found that record labels given to queries did not distinguish rejected and questioned decisions (both displayed as “decision (current)”), contrary to concept 3.6. Query instructions V2 (state the authority and time relationships of each type of record, first analyze which are current and which were replaced or rejected, then answer) + labels per the concept: 28 correct, 3 incorrect, 7 absent from memory; 31 versus 23 answered from memory. Set as the default (`recall.PROMPT_V2`, `LABELS_V2`). Performance was also fixed: each query recalculated vectors for records across the entire work line (without caching), so a query under a large Goal took a long time. Changed to caching by record ID (records do not change after writing).

**Other instructions changed to analytical form (2026-11-18)**: The instructions for progress summaries, query routing, and working directories now state their uses and the costs of misjudgment. Pointing and objects only prepare for finding candidates (the cost of missed selections is stated), so they were not changed. The control layer’s stop judgment was changed to analytical form (V3: first analyze the extent of authorization in the user’s original words and what the agent last asked, and state the costs of the two kinds of misjudgment). Tested with flash on 190 agreed stop annotations from E7: type accuracy 0.77 (0.71 for the first version without V2’s type definitions) versus V2’s 0.82; questions the user should answer were treated as reports 28 times versus 22 (the question would be buried in the relay and go unanswered); it was told to continue on its own despite a substantive response 3 times versus 4; needless interruptions 14 versus 15. The difference was in judging stops that ask the user to do something, such as “please trigger it once more … tell me when the search is done,” as asking for nothing. Not adopted; the control layer remains on V2 (which already states the handling and release conditions for each type).

**Consequences of constraint delivery (structure evaluated by consequences, 2026-11-18)**. Two checks: irrelevant constraints among those received by each new executor, and those attached elsewhere under the same Goal that should have been handed to it (`auto_eval.py cons`);
which work each constraint applies to at a given moment, and which work its location covers (`cover`). The user’s week (r1): 13 new executors received 129 constraints, of which the two judges agreed that 0 were irrelevant;
of 287 elsewhere under the same Goal, the judges agreed that 18 should have been handed over (5 executors). Most were course design requirements recorded on “organize the course outline” that later siblings working on the course website and content could not receive. `cover` (large Goals in batches):
494 of 1607 items applied to work that could not receive them (1349 pairs; reliable because both judges had to list that work). A typical case is periodic work—the process rules set the first time are recorded on that occurrence and not received the next time. For the 559 items that “arrived but did not apply,” judges could not list all cases on large Goals, so the result is unreliable; the per-executor `cons` is authoritative. aider (todo-app2) was similar: 0 irrelevant, 2 missing,
both requirements for the whole project recorded on the work being done at the time. Thus the current structure brings in almost no irrelevant constraints; what is missing is requirements for the whole undertaking that were recorded on the work item where they were stated.
The remedy in concept 3.5 is for maintenance to lift them, but maintenance almost never does (6 maintenance runs and 0 lifts that week in r1; 1 in r2): it makes more than a dozen judgments in one call, and this one is skipped. “Lift when a new constraint and one elsewhere are the same requirement”
(`scope.check`) was connected only to writes in the old v1 flow and stopped being called after the switch to v2—it was originally marked complete in the table. Judgment when new work is created, with three approaches compared offline (r1, judged at each work item’s creation time, scored using the results from the two `cons` judges):

| Approach | Recovered (missing items on siblings) | Provided | Two judges agreed: right / wrong |
|---|---|---|---|
| Lift to a common parent (`lift_for_new_work`) | 0/14 | 0 | — |
| Lift or group several items under a new parent | 13/14 | 40 | 2／26 (grouping brings constraints specific to one item to the whole group) |
| Only judge which also apply to the new work and reference them for it (`inherit_for_new_work`) | 13/14 | 38 | 28／6 |

The third approach recovered 1/1 and gave 0 incorrect on the unused aider todo-app2 data. It has been set as the default (`pipeline.inherit_on_new`), with the judgment made before dispatch. When handing it to the executor, CTM notes: “CTM judges that this also applies here; it was originally a requirement of another work item”;
it makes one extra call only when a sibling of the new work carries a constraint. The first two approaches were not adopted (`lift_on_new`, code deleted on 2026-11-25). `scope.check` was reconnected to v2 but has not been evaluated and is off by default (`lift_same`). The work page lists these constraints under “Constraints” (marked “CTM judges applicable” and indicating which work item originally required them). The user can click “Not applicable” to remove the reference—the user’s changes take precedence over CTM’s inference, and the constraint remains in its original location (`views.node_page`, `ui.drop_inherited_constraint`; browser check and `test_ctm2_structure`).

### Block D (execution context): What a new executor is missing

Using the memory from the warm-start w2 run in block C, the initial context at the time of each new session was reconstructed (memory was saved in time-stamped versions); 21 sessions were created during the run (`blockD.py`).
The standard followed the CTM scenario: opus and grok each read approximately 80 preceding messages in the conversation, this message, and the 5 messages after it, and listed the information from the preceding conversation that a new executor must know to do the work correctly (requirements, decisions, results, identifiers, environment).
Only items listed by both were retained; grok judged whether each item was fully, partially, or not present in the context. The main focus was on the 73 items from during the run (starting 10-13; the warm-start memory contained no constraints or decisions from the earlier history).

- **Leakage found during measurement (corrected)**: The replay wrote executor replies, execution summaries, file versions, and memory written from the message using the message time. Context reconstructed using that time contained content that was only available after execution of that turn (such as “PR created”); the first measurements were optimistic under both conditions and were discarded. The process was changed to delete content written after dispatch of that turn from a copy of the memory before assembling the context (`views_clean`), and the replay script was also changed to write replies 1 second after the message.
  Context in the earlier P-exec (e5f) that was reconstructed from memory rather than taken from dispatch logs had the same problem; those figures are for reference only.
- Original context (without the recent conversation): of the 73 items from during the run, fully present 0.22, partially present 0.40, absent 0.38; median approximately 3,100 characters. Much of the missing information came from the immediately preceding turns, but those turns belonged to another node—
  the user alternated between multiple work items in one conversation, and a new request often followed directly from something just completed in another work item (“commit the code”). The tree-organized scope (path, siblings, uncles) could not reach it; items from siblings were mostly “partial” (the progress summaries lacked details).
- Include the original text of the latest 6 conversation turns (regardless of which work they belonged to, noting that they are only for understanding references, `context.RECENT_CONVERSATION`): fully present 0.44, partially present 0.41, absent 0.15; median approximately 8,400 characters. The trial with the latest 3 turns (before the leakage was corrected) showed a notably smaller benefit.
- End-to-end: flash wrote an execution plan under each of the two context conditions. grok and opus reviewed them against evidence available afterward (subsequent messages in the conversation and earlier replies), with 74% agreement:

| Review | Without: correct／partial／wrong | With 6 turns: correct／partial／wrong | Required information reflected in the plan | Requirements from other work followed |
|---|---|---|---|---|
| opus | 11／10／0 | 10／10／1 | 26/49 → 34/49 | 1 → 1 |
| grok | 11／8／2 | 12／7／2 | 18/35 → 20/35 | 2 → 3 (the additional case was sibling content from the same project, unrelated to the recent conversation) |

- Conclusion: adopt the latest 6 turns. No difference in overall plan correctness was apparent across the 21 cases. The plans used more of the required information, and no requirements from other work were seen to be followed.
- Held-out data (w3, 22 new sessions, 71 items of required information from during the run): without, fully present 0.11, partially present 0.38, absent 0.51 (median approximately 2,400 characters); with the latest 6 turns, fully present 0.35, partially present 0.38, absent 0.27 (approximately 7,900 characters).
- Reused sessions (70 in w2, 310 items of required information): the executor had its initial context, exchanges delivered since then, and the content relayed this time. Fully present 0.66, partially present 0.25, absent 0.09 (median approximately 11,300 characters); adding the recent conversation turns not in this session gave fully present 0.69, absent 0.09 (approximately 14,600 characters). The benefit was very small and each message would have to carry approximately 3,300 more characters, so reused sessions do not get the addition.
- For many “partial” items, the details are in long replies or documents, and the executor must read the documents or ask CTM.

### Block D (continued): Selecting resolution by budget (2026-11-12)

The initial context for new executors in w4 and w5 had a median of 14,000–19,000 characters, with p90 exceeding 30,000 (the original text of the latest 6 conversation turns and sibling exchanges accounted for much of it). Concept 3.2’s “select one layer for each node by budget” was not implemented.
Implementation: when the budget is exceeded, downgrade the most distant parts in order (remove the original text of sibling exchanges → shorten recent conversation turns → reduce this task’s exchanges from 6 turns to 3 → retain only sibling titles → retain only 3 recent conversation turns). The current state of the task, constraints and decisions, and the user’s original words are not downgraded.
Using existing block D labels (required information agreed on by both annotators, with grok judging whether it was in the context), with 19 contexts per group:

| Data | Condition | Characters median／maximum | Required information: present／partial／missing |
|---|---|---|---|
| w2 | current (c6)／24,000／16,000 | 8,420／13,635; 8,091／13,807 (same for both budgets) | 0.41／0.39／0.20; 0.44／0.36／0.21; 0.41／0.38／0.21 |
| w3 | same as above | 7,923／14,848; 8,095／15,020 | 0.33／0.37／0.29; 0.29／0.43／0.28; 0.31／0.43／0.27 |
| t1 | same as above | 6,548／26,200; 24,000: 23,600; 16,000: 15,351 | 0.28／0.41／0.31; 0.30／0.43／0.28; 0.23／0.47／0.30 |

- All w2 and w3 contexts were below both budgets, so the differences were only judge variation (approximately 0.03 between two groups with identical content); for t1, “present” fell to 0.23 at 16,000, while no loss was observed at 24,000.
- Adopt 24,000 characters. Most labeled contexts were relatively short. Whether large contexts remain sufficient after downgrading was tested only on a few t1 cases and is left for observation during the pilot trial.

### Block G (Answering Queries)

For messages that CTM classified as queries and both annotators consistently labeled as side questions, `query.handle` (argon) was run against the memory from block C as it stood at the time (excluding content written after that turn).
Grok and opus each reviewed the results against the answers given at the time by executors that actually had access to the scene and the subsequent messages in the conversation (`blockG.py`). The costs of the two kinds of error differ: an incorrect answer from memory misleads the user; an unnecessary read-only execution is merely slower.

- Original approach (answer from memory if recall finds something, and only otherwise decide whether to use read-only execution), 32 items in development data w2: 17 from memory, 6 correct, 8–10 partial, 1–3 wrong; 15 read-only, 13–14 necessary.
  A typical error: when asked “Does a certain document contain X” (the current state of a file), it answered “yes” based on an earlier record that it had been written, but it was not actually there. Most partial answers were follow-up questions seeking explanation or analysis, for which it merely pieced together the executor's earlier statements.
- Changed to first determine the type of question (`query.ROUTE`): answer from memory only when the question asks about recorded matters (what was done, what was decided, progress and results) and memory can answer it completely; for questions about the current state of files, logs, runtime state, or external data, or questions requiring explanation, analysis, or reasoning, dispatch read-only execution (a read-only branch of the relevant work session), with the answer from memory as a clue. Development data: 4 from memory, 3–4 correct, 0–1 partial, 0 wrong; 28 read-only, 18–19 necessary, 9–10 unnecessary (the two reviewers agreed on 30/32).
- Held-out data (w3, 10-15 to 10-18, 33 items, the two reviewers agreed on 29–30/33): under the original approach, 15 from memory, 3–4 correct, 10–12 partial, 0–1 wrong; 18 read-only. Under the new approach, 0 from memory (almost all questions during this period were technical or sought explanations), 33 read-only, 25–28 necessary, 5–8 unnecessary, the plan could answer the question in 32–33. Adopt ROUTE.

### Pilot trial (pilot)

See the [development instructions](development.md) for how to start it; code is in `src/context_tree/pilot/` (a local web page plus pi RPC sessions as executors),
with offline tests in `tests/test_pilot.py` (fake pi plus model substitutes: new session, reuse, read-only fork, selection, rename, change delivery, recovery after restart). For this, an `after_dispatch` callback was added to `on_message2`:
the executor starts as soon as dispatch is determined, and memory calls no longer delay execution. After smoke testing, rule priority was specified in the fixed terms of the execution context (concept section 6): the exact words this time take priority over earlier task constraints, decisions, and guidance,
and the executor stops only when they conflict with constraint comments or ctm.md.

Completed on 2026-11-12 (following the comparison table in section 2, without adding steps or making semantic judgments in code): interface—the tree is on the left, collapsed by default, with only executing tasks and current work (and their parents) expanded; editing for merge, split, create, reattach and change the type of constraints, root entries, and document sections; three panels on the right for pages (document browsing), queries, and execution; planner enabled, with proposals approved in the conversation and on the tree; modification requests for the same working directory are queued;
object constraints are handed to the executor for the same directory to write; the first executor for a new project proposes `ctm.md` entries; the edit tool escalates when deleting or modifying constraint comments; automatic continuation determines progress based on “whether there was a tool call between the two” and sets a total limit on the number of continuations;
when a turn exceeds 10 minutes, the executor's exact words partway through are recorded; when known files are modified externally, they are recorded as the user's version and the relevant executors are notified. Offline tests: `tests/test_pilot_dirs.py` and the various `test_ctm2_*`.
