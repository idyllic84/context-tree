# Development

## Local environment

Use Python 3.10+. The only runtime third-party dependency is `requests`; SQLite, data classes and CLI tooling are from the standard library.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
context-tree-check
context-tree-benchmark --offline-check
```

To build a wheel:

```sh
python -m pip wheel . --no-deps --wheel-dir dist
```

For a disconnected installation, first prepare wheels on a connected machine with the same Python/platform target:

```sh
mkdir -p artifacts/wheelhouse
python -m pip wheel . --wheel-dir artifacts/wheelhouse
```

Copy that wheelhouse through an approved channel, then install locally without an index:

```sh
python -m pip install --no-index --find-links artifacts/wheelhouse context-tree
```

This uses the prepared project wheel and dependency wheels; do not run an editable build on a fresh disconnected machine unless its build requirements are already installed.

The repository has no remote configured by the migration process. No release or PyPI availability is implied by its project name/version. Licensing must be resolved before distribution.

## Layout and dependency direction

- `common/llm.py`: all network model calls, capabilities, stage defaults, budgets and metrics.
- `common/models.py`: versioned serialized domain objects.
- `common/store.py`, `config.py`: storage and independent paths.
- `common/context_view.py`: shared selection/assembly wire-format rendering.
- `common/stage_cli.py`, `evaluation.py`, `evaluation_runner.py`: generic transport and evaluation protocol, not stage-specific scoring.
- `stages/<step>/processor.py`: algorithm for one step.
- `stages/<step>/run.py`: JSON input/output adapter for that step.
- `stages/<step>/evaluate.py`: local fixtures, expected properties and checks.
- `pipeline/cli.py`: full-workflow sequencing and persistence.
- `legacy/tree_extractor.py`: retained single-pass alternative, not used by default.

A stage may reuse a lower-level pure function; it must not silently invoke upstream LLM stages to prepare its own supposedly fixed evaluation input. The context fixtures reuse a synthetic branch constructor, not upstream model output.

## Offline checks

`context-tree-check` imports the package with transport blocked, validates all stage fixtures and pure-code checks, and exercises temporary storage/cache/ID isolation. It also checks fresh-home import behavior and watchdog restoration. It is not a substitute for semantic accuracy evaluation.

Individual checks are independently runnable:

```sh
python -m context_tree.stages.ingest.evaluate --offline-check
python -m context_tree.stages.index.evaluate --offline-check
python -m context_tree.stages.context.evaluate --offline-check
```

Keep new checks deterministic and synthetic. Do not put private logs or provider responses into fixtures. CI installs dependencies and runs offline checks; it receives no credentials and performs no model inference.

## Online experiments

Use explicit credentials, `--allow-network`, a disposable database and a request budget. Calls are serial to avoid rate-limit interference. Freeze prompt/input/schema before comparing candidates. Save raw outputs privately along with hashes so scoring corrections can be audited without rerunning models.

Record distinct case count and repeat count separately. Do not compare changed prompts as though only the model changed. Do not infer a speedup from dissimilar historical workloads.

## Migration integrity

All 18 original Python files were preserved in the [migration mapping](migration.md); the original retrieval module and benchmark module were decomposed rather than duplicated as active monoliths. All ten original Markdown documents are archived. The source workspace remains untouched by this independent-repository restructure.

Only package boundaries, explicit configuration, credential handling, standalone entries and offline checks are changed for independence. Algorithmic limitations are listed in [architecture](architecture.md) and [roadmap](roadmap.md), not hidden by packaging.

## Before public release

Resolve [license status](../LICENSE-STATUS.md), review historical examples, inspect the built wheel and source archive, and run a new privacy/dependency review. Do not add a badge, hosted documentation URL or public issue contact until those resources actually exist.
