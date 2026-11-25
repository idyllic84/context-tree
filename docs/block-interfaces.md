# Boundaries and Interfaces of the Blocks (2026-11-19)

Blocks are divided by **judgment** ([Goals and Method](goals-and-method.md) 3.4). Blocks do not call each other directly; **they hand off only through shared memory**: each block reads some entries and relations and writes others;
what it writes is its interface. A single call can produce results for several blocks (delivery, maintenance, writeback), but each block's part of the output is a separate field, evaluated separately against its own annotations.
Parts executed by code according to rules (constraints inherited along the tree, successors becoming executable after prerequisites are complete, results folded upward, degradation according to budget) are not judgment blocks; unit tests ensure their correctness.

## Shared Memory (Data Used by the Interfaces)

| Category | Entry or relation | Writer | Reader |
|---|---|---|---|
| Original conversation text | `turn` (the user's words, the executor's reply), `segment` (part of a message, `about` the work to which it is delivered) | Delivery | All |
| Work | `task`, `goal` (title, purpose, working directory, status); relations `child`, `dep` (sequence), `uses` (reference), `serves` (research serves work) | Work relations, status | Delivery, memory write, execution context, status, answering queries |
| Requirements stated by the user | `constraint`, `decision` (including rejected and questioned decisions), `guidance`, `environment`; `about` attachment location; `replaces` replacement relation | Memory write | Execution context, answering queries, delivery (objects for candidates) |
| Execution results | `run`, `exchange`, `progress` (done／changed／verified／open／failed), `result` (folded result), file versions, documents | Result writeback | Execution context, status, answering queries, delivery (recent displays) |
| Queries | `query` (question, answer, basis) | Answering queries | Execution context (questions asked), delivery (recent queries) |
| Shown to the user | `display`, `notice`, `pending` | Relay | Delivery (which recently displayed item the user is responding to) |

Each entry carries its write time, source (user, CTM, maintenance, interface), and the entry that replaces it; readers read by time (`at`), giving the executor only current entries and marking history as historical.

## The Blocks

| Block | Trigger | Reads | Writes (interface) | Consumers | Must guarantee | Reference input for independent evaluation | Code |
|---|---|---|---|---|---|---|---|
| 1 Delivery | Every user message | Message, recent conversation, current task, recent displays and pending items, candidate work | Each segment's destination `to` (existing／new／side／research／control／ask／chat) and `node`; recorded as `segment about node` | Memory write, execution context (target work), executor interaction (dispatch), answering queries (side questions) | The user's selection and original words take precedence over inference | Reference memory built from annotations and the current task | `ref.py`, `candidates.py`, `deliver.py` (`to`, `node`) |
| 2 Work relations | New work appears (provided in a delivery call); delivery provides a structural signal; periodic maintenance | Titles, purposes, and original words for work, existing tree and Goals | New work's title, purpose, working directory, `parent`, `after`→`dep`, `goal`, `uses`; grouping from structure judgment; Goal assignment; moves and merges in maintenance; subtasks proposed by the planner | Memory write (attachment paths), execution context (paths, siblings, references), status (dependencies), delivery (candidates) | Every relation written must be true; the tree has no uniquely correct shape | A set of known work and relations provided by the system | `deliver.py` (`new`), `maintain_store.structure`, `assign_goals`, maintenance notes, `planner.py`, working directory judgment |
| 3 Memory write | Every user message (after delivery) | Message, delivery result, recent conversation, current entries | `constraint`／`decision`／`guidance`／`environment` and their attachment locations and types; replacements; behavior guidance documents; judgment on whether new work inherits sibling constraints; constraint lifts and rollbacks in maintenance | Execution context, answering queries, delivery | Faithful to the original words; each thing is recorded in only one place; replacement only when the old entry no longer holds as a whole | Reference delivery and reference tree | `remember.py`, `scope.py`, `documents.py` (behavior guidance) |
| 4 Execution context | Dispatching a new executor; forwarding a message to an existing session | Paths, siblings, references, potentially relevant conclusions elsewhere in memory, recent conversation, document index | Context text for the executor (including entries it can ask CTM about), message forwarded to the original session | Executor | Small but sufficient; only current entries; user's original words are not rewritten | Frozen reference memory | `context.py` |
| 5 Result writeback | Every executor reply | User request, executor reply, execution trace | Five `progress` fields; `exchange` and file versions; long content stored in documents | Execution context, status, answering queries, relay | Every sentence has a basis; nothing needed to take over is omitted | Executor's reply | `progress.py`, `writeback.py`, `documents.py` |
| 6 Execution control | Executor stops | Reply at the stop, user's original words, execution contract | Stop type and action (continue, allow, answer on its behalf, report); whether formally complete | Executor interaction, relay | Allow only what the user's original words have authorized; report irreversible actions | Recorded stops | `control.py`, `execution.py` |
| 7 Status | Periodic maintenance (work untouched for a long time); user changes it in the interface | Work records and whether work was continued afterward | `task.status` events (time, reason, source) | Delivery (work in progress), execution context, dependencies (code) | Executor saying it is done ≠ task completion; self-reports and verification are separate | Reference records of work and annotated follow-up | Status section of maintenance notes V11, `lifecycle.py` |
| 8 Answering queries | Side questions; executor asks CTM | Question, records of the work line in which the question was asked | Answer (with basis and old or current status marked) and `query` entry; whether to use memory or dispatch read-only execution | User (query panel), executor, execution context, delivery | History marked as historical; say "I don't know" when information is absent | Memory and questions | `recall.py`, `query.py` |
| 9 Relay | Execution complete, when the user is needed | Execution results, pending items | `display`／`notice`／`pending`, with numbers and associated tasks | User, delivery | User can refer to items; nothing requiring the user is omitted | — | `relay` (`pipeline.py`) |

## Where One Call Produces Results for Several Blocks

| Call | Output | Assigned to |
|---|---|---|
| Delivery (`deliver`) | `to`, `node` | Block 1 |
| | Title, purpose, `parent`, `after`, `goal`, `uses`, `same_work_as`, `plan` of `new` | Block 2 |
| Maintenance (`maintain_store`) | Moving, merging, grouping, attaching research | Block 2 |
| | Lifting and rollback of constraints | Block 3 |
| | Status | Block 7 |
| Write-back (`on_reply`) | Progress summary | Block 5 |
| | Whether conditional dependencies are satisfied (judged in the same summary) | Dependency relationships in block 2, used by status |

## Mechanisms Whose Assignment Is Settled Here

- Judgment of the working directory and subtasks proposed by the planner: part of the definition and composition of new work, assigned to block 2.
- Whether new work inherits constraints from siblings, and the lifting of constraints in maintenance: judging which work a requirement covers, assigned to block 3.
- Whether to continue with the original session or start a new one, and read-only branches: dispatch methods, assigned to block 5 (executor interaction); use reference delivery for evaluation.
- Documents: long-form content of execution results belongs to block 5; behavior guidance belongs to block 3.
- User changes in the interface: the highest-authority input. Synchronize four aspects according to concept 5.5. This is not a judgment block; unit tests ensure it.

## Not Yet Settled or to Be Changed

- Recall in block 2 (omitted references) is the source of block 4 missing conclusions from other work. It must be resolved in block 2; the approach of retrieving other work by similarity during assembly has been withdrawn (it bypasses work relationships).
- Block 3’s `environment` (facts) has not yet been annotated or evaluated.
- Block 5’s dispatch method (whether to continue with the original session or start a new one) has only been examined using the system’s own deliveries. It should use reference delivery instead.
- Block 6 has only been evaluated on stop classification; the formal completion check has not been evaluated.
- Block 9 can only be evaluated in real use.

## Current State of Each Block (2026-11-20, Independent Evaluation)

| Block | Now | Meets expectations? | Next step |
|---|---|---|---|
| 1 Delivery | Block A: continuing current work 0.96–0.98; other existing work 0.87–0.92; new work identification 0.82–0.85; side questions about other work 0.73–0.76 (most errors picked an adjacent piece of subwork, or both readings were valid) | Largely meets expectations | — |
| 2 Work relationships | 96% of agreed Goal assignments are correct; positions (parent, preceding step) are largely correct; structural grouping: 8 correct／1 incorrect; references are about 85% correct, but only 8 of 18 actual dependencies were linked | Reference recall does not meet expectations | Implicit dependencies are hard to judge at delivery. As a fallback, the executor asks and block 8 answers within the Goal subtree; candidates in block 1 |
| 3 Memory write | Recall for constraints and decisions about 95%; precision about 70%; replacement misjudgments 7→3; fact recall is low (10 of 66 recorded), but the original words are delivered in full, so additional extraction of facts is not warranted | Constraints and decisions meet expectations; facts delivered in the original words | How object rules without a directory reach work elsewhere that uses the same object (more evidence needed) |
| 4 Execution context | 92% of structurally reachable information is provided; with reference memory and Goal, overall “none” 15→3; after no longer repeating summaries for turns whose original text is included in full, “present” 132→143 | Meets expectations (the gap is in structure) | Implicit dependencies between parallel work under the same Goal (references, executor questions) |
| 5 Result write-back | Progress summary V4: about 65–70% of information needed later is written in; 2–4% of sentences lack support | Partially meets expectations | Re-evaluate the dispatch method using reference delivery |
| 6 Execution control | Stop classification 0.82; risky cases allowed through about 2.6%; formal completion check 94% (53 items agreed on by two people) | Meets expectations | — |
| 7 Status | On reference input, 63 of 73 items agreed on by two people judged correctly (86%); the user returned after completion was judged in 4 items | Meets expectations | — |
| 8 Answering queries | Probe questions answered correctly 28→33／46 (retrieve more records, include replaced entries); several approaches to current-state cards (always provide, provide only when nothing is found, provide only for questions about the current state) produced no improvement beyond fluctuation, so none were adopted; most remaining errors are due to question ambiguity and answer variability | 72%, the level of this method for now | More and clearer probe questions to estimate the true level |
| 9 Relay | Code combines several fields of the progress summary into a relay, with no separate judgment; from the user’s side, the relay alone was sufficient in 58 of 60 passages (agreed on by two people), and the user subsequently depended on missing details in 0 passages | Meets expectations | Count how often users open the original reply in real use |

## Assembly Walkthrough: Going Through the Blocks for the Concept’s Scenarios (2026-11-20)

| Scenario | Blocks traversed | Can assembly achieve the concept’s effect? |
|---|---|---|
| S1 Act after a query | 8→1→4 | Yes: the conclusion of read-only execution is written back to the query record (`answered`), the new work references this query, and the executor receives the conclusion itself |
| S2 Short approval during parallel work; S8 “Change it according to the second item” | 9→1 | **Added** (2026-11-20, `pipeline.OPEN_ITEMS`): items left for the user in a reply become numbered pending items and displays; previously: after execution completed, the display written to memory was only one line, “Completed: …”; the items requiring a user decision in the relay were only on the pilot interface, and did not become numbered displays and pending items identifying the work they belonged to (concept 1.2, 5.2 item 6). Delivery could not see what a number referred to and could only guess from the recent conversation; the block A evaluation always passed an empty display list, so this path was not tested |
| S3 Return to old work the next day | 1→5→4 | **Added** (11-20): starting with delivery V9, “the most recent turns to continue from” are no longer named. A resumed session cannot see what was just said in other work (lower bound on need rate 4/92); related queries answered from memory were not forwarded. Code now forwards turns from other work and related queries since its previous turn (`context.FORWARD_BETWEEN`) |
| S4 Write a correction into an object file | 3→executor | Requires the executor to actually write it; replay cannot test it |
| S5 Delegate planning | 2 (planner)→6 | Appears very rarely in the data; not evaluated |
| S6 Verify a report | 8 | Yes: the progress summary separates “evidence of” from “self-reported”, and query answers include supporting evidence |
| S7 Depend on a decision in another task | 1→2→4, 3 | Yes: referenced decisions are delivered to the executor; when a decision is replaced, the work referencing it is marked for rechecking (`remember` calls `recheck_on_replaced_decision`) |
| S9 User changes the tree, S10 External changes | Code | Covered by unit tests and browser checks |
| S11 Ambiguous reference, S12 Interrupt execution | 1, 6 | Delivery has “ask first” and “control” categories; few samples in block A |
| S13 One message concerns multiple pieces of work | 1 | Delivery can split it into several parts, but block A scoring only looks at the first part. Frequency was checked: none of the deliveries for 480 messages in four replays were split; of 96 messages in w1118＋d1120, two people agreed that only 2 targeted multiple pieces of work at once (another 12 were judged so by only one person, mostly involving several aspects of the same work). Both were delivered in full to one piece of work, at the cost of handing them to the same executor. There are too few samples to evaluate a change, so leave it as is for now |
| S14 Point out a problem while browsing, S15 Preferences | 3, interface | Partially implemented, not evaluated |

To add: the S2／S8 interface (specified in the concept, missing from implementation); separate independent evaluations of S3 forwarding and S13 splitting.
