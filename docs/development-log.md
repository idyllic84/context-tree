# Development record

## Earlier exploration: April 2026

The original workspace explored a Rust/Tauri memory feature, a Python V2 pipeline, a decision-centered B variant, and the tree-native C direction. The full documents are retained in [history](history/README.md); their status labels, model names and performance figures describe that period.

The original context-tree idea already emphasized organizing task evolution, excluding unrelated branches and composing focused context. Later documents sometimes described the product mainly as cross-session work memory. That narrower description is not the current primary objective.

## 2026-10-01: clarify research focus

The project owner clarified that the most useful mechanism is tree-shaped context organization and rapid branch localization, so an agent can avoid carrying and reprocessing all history. A product feature overlap with generic memory is therefore not sufficient evidence to stop the work.

Two research passes identified closer alternatives: dynamic discourse trees, evidence hierarchies, subgoal working memory, context folding and programmatic access to external context. Historical citation mismatches were recorded in [research](research.md).

## 2026-10-01: extraction and retrieval repairs

The C working tree was updated to align a user's request with its following assistant response and tools, retain multiple assistant text blocks, preserve pending responses, normalize unit references, restore existing task trees and avoid clearing snapshots on no-op sync.

Literal identifier indexing and expandable search hits were added. Query embeddings are reused and session trees are loaded as needed. New search/expand evidence must be observed before finalization. Ambiguous source attribution is not promoted to certain task ownership. Session-bound entities and edges are replaced consistently during incremental updates.

Small live and offline checks were run in isolated data copies. The original knowledge base was not rebuilt. Missing original long-session logs prevented a full large-data validation.

## 2026-10-01: evaluation correction

Initial model screens overemphasized the final retrieval result and simple JSON/keyword checks. The owner required independent evaluation of every step, because each has a different objective and error cost.

The resulting evaluator has 15 controlled cases across seven model-backed steps. A 120-request serial screen, with repeats, informed provisional model choices. Scoring was corrected for legal reaffirmation acts and equivalent bilingual content; old outputs were preserved rather than silently replaced. Model choices and limitations are documented in [evaluation](evaluation.md).

## Standalone repository extraction

The current working files—not an older committed snapshot—were copied into this repository. The original workspace was retained. No Git history, private database, cache, session logs, credentials or raw evaluation logs were imported.

The owner requested independent step directories and a common model tool directory. Accordingly:

- the source is packaged as `context_tree`;
- stages own processors, run entries and evaluations;
- the retrieval monolith is split into indexing, recall, branches, selection and assembly;
- common code contains provider transport, contracts, storage, paths and reusable runners;
- standalone data/session paths and explicit environment credentials replace application coupling;
- imports and offline checks do not write home-directory state or read keychain credentials;
- historical documents are retained with archival and privacy notices;
- licensing is explicitly pending; no publication or redistribution grant is asserted.

The migration validates offline behavior and packaging. It does not add new model-quality claims or complete the deferred online/large-data roadmap.
