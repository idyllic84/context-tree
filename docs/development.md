# Development

## Local environment

Use Python 3.10+. The only runtime third-party dependency is `requests`; SQLite, data classes and CLI tooling are from the standard library.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
context-tree-auth --help      # model credentials (see authentication.md)
context-tree --help           # the pilot page
```

To build a wheel:

```sh
python -m pip wheel . --no-deps --wheel-dir dist
```

No release or PyPI availability is implied by the project name or version. The code is under the [MIT License](../LICENSE).

## Layout

The design is the [CTM concept model](ctm-concept-model.md); which concept items are wired into the running flow is section 2 of the
[implementation plan](ctm-implementation-plan.md). The history of earlier designs and code is in [evolution](evolution.md).

- `src/context_tree/ctm2/`: CTM itself. `store.py` (SQLite items, edges and events with valid time and replacement), `tree.py`, and one module
  per part of the message flow: `ref.py` (pointing and objects), `candidates.py`, `deliver.py`, `remember.py` (memory writes and replacement checks),
  `context.py` (executor context and forwards), `execution.py`, `control.py`, `progress.py`, `relay.py`, `query.py` and `recall.py`,
  `lifecycle.py`, `maintain_store.py`, `documents.py`, `objectfiles.py` (CTM's own `ctm.md` records and annotation proposals), `root.py`,
  `ui.py`; `pipeline.py` (`CTM`) runs the flow.
- `src/context_tree/pilot/`: the local page (`app.py`, `server.py`, `static/index.html`), pi sessions as executors (`pi_rpc.py`), the on-disk
  vector cache (`vectors.py`), the import of recent history (`bootstrap.py`) and the usage report (`report.py`).
- `src/context_tree/common/`: model transport (`llm.py`), credentials (`auth.py`) and the data directory (`config.py`).
- `src/context_tree/tools/auth.py`: the credential tool behind `context-tree-auth`.

Prompts keep their earlier versions next to the current one (`PROMPT_V..`) so that evaluations can compare; the current one is the module's
`PROMPT` (or the constant named in the implementation plan).

## Running the pilot

```sh
python -m context_tree --root <CTM directory> [--port 8765] [--open]
```

The CTM directory holds the runtime data: `ctm.sqlite` (memory), `vectors.sqlite`, `ctm-state.json`, `conversation.jsonl`, `events.jsonl`,
`sessions/` (executor pi sessions), `logs/`, `records/`, `behavior/`, `work/`. Executors and other subprocesses start without windows.

## History import

`python -m context_tree.pilot.bootstrap --root <CTM directory> --since <date>` builds the memory from earlier sessions: pi session files,
and optionally an archive in ClaudeViewer's format (`CONTEXT_TREE_HISTORY_DB`, `CONTEXT_TREE_HISTORY_LIB`). Sessions under
`CONTEXT_TREE_EXCLUDE_DIRS`, sessions whose first message starts with one of `CONTEXT_TREE_AUTOMATED_PREFIXES`, and connection tests
(`CONTEXT_TREE_PROBE_PATTERNS`) are left out. The other
settings are listed in the [README](../README.md#configuration).

## Usage report

`python -m context_tree.pilot.report --root <CTM directory> [--since <date>] [--judge]` counts messages, waiting, corrections, executor stops,
CTM's own `ctm.md` records and proposals, and errors; real use is the evaluation data from here on.

## Checks

Offline tests stub the model calls; each file runs on its own:

```sh
for f in tests/test_*.py; do PYTHONPATH=src python "$f" || exit 1; done
```

The browser check drives the page with Playwright and the installed Edge. It changes data, so run it against a copy of a CTM directory:

```sh
python -m context_tree --root <copy> --port 8799
python tests/browser_pilot_ui.py
```

## Before public release

Session records, CTM directories, credentials and evaluation data are private and stay outside Git.
