# Contributing

This repository is a research prototype under the [MIT License](LICENSE); contributions are accepted under the same license.

## Keep the problem in focus

The goal is a small but sufficient context for each execution, correct localization across sessions and works, and measurable cost
([goals and method](docs/goals-and-method.md)). Explain how a change affects these, not only whether a mechanism works.

## Work within a block

CTM's judgments are divided into blocks ([block interfaces](docs/block-interfaces.md)). A change to one block is evaluated on its own,
with reference inputs from the blocks upstream; end-to-end runs only find problems. Put model calls in `common/llm.py` (through `ctm2/model.py`);
do not add private clients or credential discovery elsewhere.

A model or prompt comparison freezes the block's input, measures on data not used to find the errors, and counts only what independent
annotators agree on. Report quality before latency; never trade silent information loss for speed.

## Before proposing a change

```sh
python -m pip install -e .
for f in tests/test_*.py; do PYTHONPATH=src python "$f" || exit 1; done
```

Offline tests stub the model calls; add a small test for changed behavior. Do not call models while running offline checks. The browser
check (`tests/browser_pilot_ui.py`) runs against a copy of a CTM directory ([development](docs/development.md)).

## Scope and history

Use a copy of a CTM directory for experiments; do not rebuild a user's memory without asking. Update the design documents when responsibilities
or contracts change; record superseded approaches and adverse results in [evolution](docs/evolution.md). Do not claim production
readiness or model superiority without matching evidence.
