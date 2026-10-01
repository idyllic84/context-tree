# Context Tree

**Organize a large interaction history once. Locate the relevant task branches. Give an agent only the context it needs now.**

[中文说明](README.zh-CN.md) · [Goals](docs/goals.md) · [Architecture](docs/architecture.md) · [Independent stages](docs/stages.md)

Context Tree is a Python research prototype for task-structured context organization and selective context assembly. It transforms a chronological dialogue into a persistent forest of goals, tasks, subtasks, constraints, decisions and source references. A query identifies relevant branches; a selection loop expands missing evidence and excludes unrelated work; a separately configured model assembles compact context candidates.

The main objective is **not to accumulate more memories**. It is to reduce how much history the consuming agent must read, carry and reconstruct while preserving the information needed for its current task. Cross-session retrieval is one application of this mechanism.

## Status and licensing

- Research/alpha implementation, extracted from the Companion C prototype.
- Current source adapter: Claude Code JSONL. No live editor integration or automatic replacement of another agent's active context window.
- Experimental GitHub Copilot transport; model availability depends on the account and service policy. This is not an official provider SDK.
- **License pending. No open-source license is granted by this repository.** Do not treat this local preparation as authorization to redistribute the code. See [LICENSE-STATUS.md](LICENSE-STATUS.md).
- No private dialogue corpus, database, credentials or raw model evaluation logs are included.

## How it works

```text
Source dialogue
  → ingest: user-triggered response/tool spans
  → extract: speech-act units and feedback references
  → tree: goal/task mutations and source ownership
  → review + reflexion: structural and evidence checks
  → framing: faithful, compact unit descriptions
  → emit + resolve + index: persistent evidence and lookup indexes

Current query
  → recall: semantic, file and literal identifier candidates
  → branches: task-topology neighborhoods and inherited constraints
  → select: expand / drop / search / done
  → context: assemble selected evidence for the consuming agent
```

Task hierarchy and semantic similarity have different jobs. Embeddings find candidate nodes; topology provides their work context. The current dense recall implementation scans indexed vectors—it is **not** a logarithmic tree-search engine.

## Install locally

Python 3.10 or newer is required. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
context-tree --help
context-tree-check
context-tree-benchmark --offline-check
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Offline fixtures and packaging are intended to be portable; provider calls on Windows have not been validated. Installation may download `requests` and packaging dependencies. The offline checks make no model calls and require no credentials.

## Run one step, not the entire pipeline

Every directory under `src/context_tree/stages/` owns its implementation, input/output entry point and evaluation. Shared model transport, contracts, paths and storage live under `common/`.

```sh
mkdir -p artifacts
python -m context_tree.stages.ingest.run --example --output artifacts/input.json
python -m context_tree.stages.ingest.run --input artifacts/input.json --output artifacts/turns.json
python -m context_tree.stages.ingest.evaluate --offline-check
python -m context_tree.stages.tree.run --example
python -m context_tree.stages.tree.evaluate --offline-check
```

A model-backed step requires explicit permission to send its input:

```sh
python -m context_tree.stages.extract.run \
  --input artifacts/turns.json --output artifacts/units.json \
  --allow-network --request-limit 10
```

Configure credentials first as described below. Do not use private sessions until you understand what is transmitted. See [stage contracts](docs/stages.md) for the exact envelope accepted by each step.

## Configure explicit online access

There is no automatic credential discovery or application-keychain fallback. Supply **one** of these environment variables through your shell or secret manager:

- `CONTEXT_TREE_COPILOT_TOKEN`: a valid short-lived Copilot bearer token.
- `CONTEXT_TREE_GITHUB_TOKEN`: an eligible GitHub token for the experimental token-exchange flow.

A generic GitHub token may not have the necessary access. Do not paste credentials into source files, examples, benchmark outputs or issues.

```sh
context-tree --allow-network models
context-tree --allow-network --request-limit 20 \
  --sessions-dir /path/to/approved/session-directory \
  --db ./artifacts/demo.db sync --session SESSION_PREFIX
context-tree --allow-network --request-limit 8 --db ./artifacts/demo.db \
  retrieve "What context is relevant to CSV import?" --mode agent
```

The commands above are examples, not an instruction to upload your entire history. `sync` without a session filter may process every discovered session. [Configuration](docs/configuration.md) describes directories, model overrides, request budgets and provider limitations.

## Evaluate the right thing

Each step has a different objective. Model selection uses fixed inputs and step-local gold checks, **not the quality of the final pipeline answer**:

- extraction: explicit information, acts and targets;
- tree building: hierarchy, ownership and constraint scope;
- review: repairs without damaging correct branches;
- reflexion: evidence-supported corrections;
- framing: fidelity, identifiers, numbers and scope;
- selection: the right next action for a frozen evidence state;
- context: necessary facts, exclusions, citations and size.

The shipped cases are small, synthetic, assistant-authored screening fixtures, not a broad benchmark. Current model defaults are provisional. Gemini 3.8 Flash was not included in the latest independent-stage comparison. No model family is claimed to be universally best. See [evaluation methodology and recorded limitations](docs/evaluation.md).

## Documentation

| Document | Purpose |
|---|---|
| [Goals and scope](docs/goals.md) | Problem, non-goals and success criteria |
| [Architecture](docs/architecture.md) | Current algorithms, data flow and known limitations |
| [Stages](docs/stages.md) | Independent run/evaluation contracts |
| [Configuration](docs/configuration.md) | Credentials, data paths, models and CLI usage |
| [Development](docs/development.md) | Installation, offline checks and package workflow |
| [Evaluation](docs/evaluation.md) | Per-step metrics, screening evidence and open questions |
| [Research](docs/research.md) | Closest mechanisms and corrections to old citations |
| [Roadmap](docs/roadmap.md) | Implemented, incomplete and unvalidated capabilities |
| [Development log](docs/development-log.md) | Recent decisions and migration record |
| [Historical archive](docs/history/README.md) | All ten original development documents |

Read [SECURITY.md](SECURITY.md) before using real logs. See [CONTRIBUTING.md](CONTRIBUTING.md) before proposing changes.
