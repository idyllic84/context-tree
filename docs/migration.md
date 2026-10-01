# Source migration map

The standalone repository was populated from the latest working files of the Companion C prototype, including uncommitted changes. Source files and documents remain in the original workspace; migration did not delete them or rewrite its Git history.

## Code mapping

| Original file | Standalone location |
|---|---|
| `companion.py` | `src/context_tree/pipeline/cli.py` |
| `copilot_api.py` | `src/context_tree/common/llm.py` |
| `models.py` | `src/context_tree/common/models.py` |
| `store.py` | `src/context_tree/common/store.py` |
| `claude_adapter.py` | `src/context_tree/stages/ingest/processor.py` |
| `extract_units.py` | `src/context_tree/stages/extract/processor.py` |
| `build_tree.py` | `src/context_tree/stages/tree/processor.py` |
| `state_machine.py` | `src/context_tree/stages/tree/state.py` |
| `tree_review.py` | `src/context_tree/stages/review/processor.py` |
| `reflexion.py` | `src/context_tree/stages/reflexion/processor.py` |
| `framing_pass.py` | `src/context_tree/stages/framing/processor.py` |
| `tree_to_entities.py` | `src/context_tree/stages/emit/processor.py` |
| `entity_resolver.py` | `src/context_tree/stages/resolve/processor.py` |
| `retrieval.py` | `stages/index`, `recall`, `branches`, `select`, `context`; loop orchestration in `pipeline/retrieval.py`; shared vector/scope/view helpers under `common` |
| `tree_extractor.py` | `src/context_tree/legacy/tree_extractor.py`, retained but not selected by default |
| `tools/benchmark_models.py` | Stage-owned `evaluate.py` files plus `common/evaluation.py`, `common/evaluation_runner.py`; tool entry retained |
| `tools/export_obsidian.py` | `src/context_tree/tools/export_obsidian.py`, now reads source DB read-only |
| `tools/__init__.py` | `src/context_tree/tools/__init__.py` |

New `run.py` wrappers expose explicit JSON contracts for each stage. New shared configuration removes dependency on the originating application. New offline checks exercise the package without model calls.

## Documents

All ten original Markdown files appear by the same filename in [history](history/README.md). Added banners distinguish history from current behavior. Personal path segments and short session identifiers are anonymized consistently; technical content and relative document links remain.

Current project documentation was written separately rather than overwriting earlier designs. The October changes and evaluation corrections are summarized in [development-log](development-log.md).

## Intentionally excluded

- Git history and remote configuration.
- Databases, caches, device identifiers and build/interpreter artifacts.
- Credentials and original application authentication configuration.
- Real session JSONL and private evaluation logs.
- Unrelated Rust/Tauri/UI components and earlier A/B codebases.

No license was granted, no remote repository was created, and no commit or push was performed as part of extraction. See [license status](../LICENSE-STATUS.md).
