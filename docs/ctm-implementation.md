# CTM Implementation

## Core: `src/context_tree/ctm2/`

CTM implemented according to the [CTM concept model](ctm-concept-model.md); `src/context_tree/pilot/` runs it as a local page, with pi sessions as executors.
For an item-by-item mapping of concept entries to modules, what has been evaluated, and how, see Section 2 of the [implementation plan](ctm-implementation-plan.md).
The code retains only the current version of each workflow and description (plus at most one candidate under evaluation); old versions and approaches that were not adopted are recorded in the evaluation records, and the code is in the version history.

| Module | Responsibility | Concept model |
|---|---|---|
| `store.py` | SQLite memory: entries, edges, events; write, occurrence, and validity intervals and replacement and observation times; sources; “as of a certain time” queries | 3.1, Section 4 |
| `tree.py` | Tree view over the store (`StoreTree`): structural changes leave events through the store; the current state of work as seen by delivery | 3.4 |
| `ref.py` | Pointing and objects: how messages point to work (continuation, reference, naming, time), which objects are named | 5.1 Step 1 |
| `candidates.py` | Find candidates based on pointing: recent work, running executors, pending items and display entries, objects (including spelling errors in identifiers), time | 5.1 Step 2 |
| `deliver.py` | Delivery: where and how each part is delivered (continue, create new, side question, research, control, ask first, CTM records it itself); when nothing is suitable, review all work and judge again | 5.1 Step 3 |
| `remember.py` | Write memory after dispatch: constraints, guidance, decisions, facts, behavior guidance, settings, each attached where it belongs; the replacement step compares each entry with the closest current entry | 5.1 Step 5, 3.5, 3.6, Section 4 |
| `writeback.py` | Write back executor replies: execution evidence, one brief progress entry, long content saved as documents; collect “current entries” for memory | 5.2 Item 6, 3.4 |
| `context.py` | Initial context for a new executor (path and subtree, recently executed siblings, recent conversations, referenced conclusions from elsewhere, approaches not to use again, document and file indexes); increments received by reused sessions; context for research entries; reduce resolution according to budget | Section 2, 3.2, 5.2 |
| `execution.py`、`control.py` | Executor lifecycle (create on first execution, reuse the session thereafter; read-only fork for queries); forwarding; stop classification and completion checks by the execution control layer; escalation of scope violations and lack of progress | 5.2 |
| `progress.py` | Brief progress summary of executor replies (what was done, changes, verification, pending items, failures) | 3.4, 5.2 Item 6 |
| `recall.py`、`query.py` | Answer executor and user queries from memory (provide only current content, marking replaced and questioned items); dispatch read-only execution when memory cannot answer | 5.2 Item 5, 5.3 |
| `relay.py` | Relay: numbered display items (with their owning tasks), pending items | 5.4 |
| `documents.py` | File versions, documents (type, purpose, version, updates by section, obsolete status), object constraint index, behavior guidance documents | 3.5, 3.6 |
| `objectfiles.py` | CTM's own `ctm.md` records: when to write, rewrite or delete upon replacement, proposals and withdrawals of source comments | 3.5, 1.1 |
| `planner.py` | Planner: subtasks as proposals; those already authorized by the user's original words become plans directly; approval | 3.4 |
| `scope.py` | Where constraints go: when the same requirement appears on another branch, lift it, or propose it as an object constraint or global preference; new work references constraints that also apply on siblings | 3.5 |
| `maintain_store.py` | Periodic maintenance: reattach, merge, rename, add ordering, fix statuses, lift constraints, Goal ownership and same-level structure judgment; record inheritance changes caused by reattachment and notify executors | 5.6, 3.4 |
| `root.py` | Root layer: persona, understanding of the user, overall goal, preferences and global constraints, commonly used environments | 3.3 |
| `ui.py`、`views.py` | Propagation of interface changes; pages generated from memory (task metadata, exchange records, documents) | 5.5, 1.2, 3.7 |
| `lifecycle.py` | Status events and valid transitions; dependencies and gating; prerequisites completed→executable; overturned→pending recheck; fold upward on completion | 3.4, Section 4 |
| `model.py` | Model calls (through `common/llm.py`), recording the role and usage of each call | — |
| `pipeline.py` | Main workflow: user message (pointing → candidates → delivery → dispatch → memory → structure judgment → relay); executor reply (evidence, progress, execution control layer, status, escalation and response, open items); periodic maintenance | Section 5 |

Offline tests (all model calls replaced): `tests/test_ctm2_*.py` and `tests/test_pilot*.py`; page check `tests/browser_pilot_ui.py` (see [development notes](development.md)).

## Early Prototype (Deleted)

The early prototype `src/context_tree/ctm/` was used to run through the “understanding—locating—writing—assembly—dispatch—writeback—maintenance” loop, and was deleted on 2026-11-23 along with the old package;
the first message workflow in `ctm2` (understanding→locating→placement→writeback) was then deleted on 2026-11-25. For their approaches, gaps with the concept model, and lessons learned, see [evolution](evolution.md).
