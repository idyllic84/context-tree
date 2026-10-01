# Independent stage contracts

Each stage is a Python module with its own implementation, executable runner and evaluator:

```sh
python -m context_tree.stages.STAGE.run --help
python -m context_tree.stages.STAGE.run --example
python -m context_tree.stages.STAGE.evaluate --offline-check
```

Replace `STAGE` with a directory name below. `--example` emits synthetic JSON without model calls. Runners read a JSON object from `--input FILE` or stdin and write JSON to `--output FILE` or stdout. Progress messages go to stderr. Parent output directories must already exist.

Model access is disabled unless `--allow-network` is set. `--model`, `--effort` and `--request-limit` apply only to the step being run; they do not execute the upstream pipeline. A supplied upstream artifact is the caller's responsibility.

## Contracts

| Stage | Input object | Output object | Side effects |
|---|---|---|---|
| `ingest` | `file_path` or synthetic `messages`; optional `session_id` | `session` with completed and pending turns | Reads explicit source; no model |
| `extract` | `session`; optional `prior_units` | Updated `session`, `unit_count` | L1 model calls |
| `tree` | `session` containing extracted turns, or explicit `units`; optional `initial_session` | Updated `session`, `mutations`, `warnings` | L2 model calls; no DB write |
| `review` | `session`; optional `max_iterations` (default 1) | Updated `session`, mutation count/log | Structural-review model calls |
| `reflexion` | `session` with dialogue and claims | Updated `session`, `corrections` | Evidence-audit model call |
| `framing` | `session` with task-linked units | Updated `session` | Framing model calls |
| `emit` | `session`; optional `date` | `entities`, `edges` | No model; file entities may create a device ID in the configured data directory |
| `resolve` | `entities`; explicit `--db` | Resolved `entities`, embedding vectors | May call embeddings/LLM and modify existing DB records; use a disposable DB |
| `index` | `session`; optional `identifiers_only` | Counts and database path | Explicit `--db` required; writes index/snapshot; embeddings unless identifiers-only |
| `recall` | `query`, or `identifier`, or `file`; optional `project_path`, `query_embedding`, `top_n` | Candidate `hits`, `occurrences`, or `files` | Existing `--db` read-only; dense query calls embedding unless supplied |
| `branches` | `hits` and `sessions` keyed by session ID | `branches` | Pure topology, no DB/model |
| `select` | `query`, `branches`; optional observed `history`, `search_results`, `mode` | One `action` | Exactly the action-decision step; does not execute tools or run a loop |
| `context` | `query`, selected observed `branches`; optional `search_results`, `mode` | Validated context `candidates` and metadata | Assembly model only; cannot search/expand |

A `session` is the serialization of `common.models.Session`: `session_id`, `project_path`, `display_name`, `goals`, `turns`, `pending_turns`. The data classes are the source of truth. Examples contain complete minimal objects.

A branch includes internal node/parent maps and expanded evidence needed for later selection. JSON serializes internal sets as lists. Treat branch files as private artifacts when created from real history.

## A partial pipeline without an orchestrator

```sh
mkdir -p artifacts
python -m context_tree.stages.ingest.run --example --output artifacts/source.json
python -m context_tree.stages.ingest.run --input artifacts/source.json --output artifacts/turns.json
python -m context_tree.stages.extract.run --allow-network \
  --input artifacts/turns.json --output artifacts/units.json --request-limit 5
python -m context_tree.stages.tree.run --allow-network \
  --input artifacts/units.json --output artifacts/tree.json --request-limit 5
```

The first two commands are offline. The last two require explicit credentials and may incur usage charges. Outputs can feed the next stage when their envelopes match. Entity output and branch selection have distinct contracts; they are not interchangeable session objects.

For an existing tree plus new extracted turns, provide the old complete snapshot as `initial_session` and the new turns under `session.turns`. Do not pass the same historical turns as both old and new. When supplying the explicit `units` array instead, `session` is the existing snapshot: its historical units are retained so feedback may target them, and the new units are appended as a new source span.

## Independent evaluation

Seven model steps own their own synthetic cases and scoring in `evaluate.py`: extract, tree, review, reflexion, framing, select and context. The remaining stages provide deterministic local checks with no model ranking.

```sh
python -m context_tree.stages.select.evaluate --offline-check
python -m context_tree.stages.tree.evaluate --allow-network \
  --models MODEL_ID:EFFORT --request-limit 8 --output artifacts/tree-results.json
```

Offline fixture checks validate the test setup, not model quality. Online stage evaluation always uses the fixed input for that stage; it does not consume another candidate's newly generated output. `select` is scored on its next action and selected branch IDs, not its answer wording. `context` is scored only with supplied evidence held fixed.
