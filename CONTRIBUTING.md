# Contributing

This repository is a research prototype and its [license is not yet selected](LICENSE-STATUS.md). Confirm contribution and redistribution terms with the maintainer before submitting material for publication.

## Keep the problem in focus

The goal is task-structured organization and selective context loading, not a generic memory feature checklist. Explain how a change affects relevant-branch discovery, necessary evidence, irrelevant context, agent reading burden or total cost.

## Work within a stage

Each `src/context_tree/stages/<name>/` owns its processor, run contract and evaluation. Put provider calls in `common/llm.py`; do not add private clients or credential discovery to stages. Keep pipeline orchestration separate from the stage algorithm.

A model comparison must freeze that stage's input and use stage-local expected properties. Do not feed each candidate its own upstream outputs and call the resulting final answer a fair comparison. Report quality before latency; never trade silent information loss for speed.

## Before proposing a change

```sh
python -m pip install -e .
context-tree-check
context-tree-benchmark --offline-check
python -m context_tree.stages.tree.evaluate --offline-check
```

Add small synthetic fixtures for changed behavior. The project currently uses executable offline checks and independent stage evaluations, not a large mocked pytest suite. Do not call models in CI or while running offline checks.

Paid evaluation is explicit and serial:

```sh
mkdir -p artifacts
context-tree-benchmark --allow-network --stages tree \
  --models MODEL_ID:EFFORT --request-limit 10 --output artifacts/tree-evaluation.json
```

Replace placeholders with an account-accessible model and supported effort. Record prompt/input hashes, failures, token accounting and latency. Keep private outputs outside version control. Repeats of two fixtures are not four independent examples.

## Scope and history

Preserve source provenance and document schema changes. Never silently mix legacy and current turn semantics. Use an isolated database for experiments; do not auto-rebuild a user's knowledge base.

Update current documentation when responsibilities or contracts change. Preserve historical documents as history; correct obsolete claims in the current docs rather than pretending they were never made. Do not claim asymptotic search speed, production readiness or model superiority without matching evidence.
