# Context Tree

[中文说明](README.zh-CN.md)

Context Tree is a research project on a **context tree manager (CTM)**: one assistant between a user and the coding agents doing
the work. The user talks only to CTM, in one continuous conversation, while many works run in parallel. CTM keeps long-term memory
of the **work** itself, decides which work each message belongs to, and gives every execution a small but sufficient context.

Agent sessions forget, get replaced and get compacted. CTM keeps continuity outside them:

- **Work-oriented memory.** A tree of goals and tasks, each with what was decided, which rules hold, what was done and how it
  relates to other work. Rules are scoped (a task, a goal, everything, or an object such as a module) and inherited down the tree.
- **The user's words are the authority.** Every item keeps its time and what replaced it; only current items reach executors.
  Executor reports never replace what the user said.
- **Localization.** Each message (or part of one) is delivered to the right work: continue it, start a new one under the right
  goal, ask a side question, control an executor, or just let CTM remember something.
- **Small, sufficient context.** Executor context is assembled from the memory by code, within a budget, rather than written
  freely by a model.
- **Measured block by block.** Each judgment (delivery, memory, context, progress, control, query, maintenance, relay) is
  evaluated on its own with reference inputs.

Status: research prototype for a single user, run locally (developed on Windows). Code, prompts and the page are in English;
what the models write for you (work titles, summaries, answers) follows the language you write in. The design and evaluation
records are in Chinese.
Licensed under the [MIT License](LICENSE).

## How it works

1. A message arrives. A light model call reads how it points at work (continuation, reference, named objects, time).
2. Candidates come from those pointers (recent works, works that touched the named objects, the current work).
3. The delivery call decides where each part goes and how.
4. Executors start right away (pi coding-agent sessions, one modifier per working directory), with a context assembled from the
   memory; a reused session receives only what changed since its last turn.
5. Memory is written after dispatch: constraints, decisions, facts and guidance, each checked against the most similar current
   items to record what it replaces.
6. Executor replies are summarized into progress; a control step decides whether to continue, stop or ask the user; open items
   become numbered pending items in the conversation.
7. Periodic maintenance revisits the tree with hindsight (merges, re-parenting, statuses, lifting shared rules).

The full model is [docs/ctm-concept-model.zh-CN.md](docs/ctm-concept-model.zh-CN.md); what is implemented and how each part was
evaluated is section 2 of [docs/ctm-implementation-plan.zh-CN.md](docs/ctm-implementation-plan.zh-CN.md).

## Layout

| Path | Contents |
|---|---|
| `src/context_tree/ctm2/` | CTM: store (items, edges, events with valid time), tree, and one module per judgment (`ref`, `candidates`, `deliver`, `remember`, `context`, `progress`, `control`, `query`, `recall`, `maintain_store`, `relay`, `objectfiles`); `pipeline.py` runs the flow |
| `src/context_tree/pilot/` | The local web page, pi sessions as executors, the vector cache, the import of earlier session history, the usage report |
| `src/context_tree/common/` | Model transport, credentials, data directory |
| `tests/` | Offline tests (model calls stubbed) and a browser check |
| `docs/` | Design, goals and method, implementation status, evaluations, related work, history (Chinese) |

## Requirements

- Python 3.10+ and `requests`.
- Model access through a GitHub Copilot account, via the project's own device login (`context-tree-auth`, see
  [docs/authentication.md](docs/authentication.md)). Only use accounts you are authorized to use.
- Executors: the [pi coding agent](https://github.com/earendil-works/pi) CLI (`pi` on `PATH`, or a build's bundled `cli.js`).
- git, for working directories that are repositories.

## Quick start

```sh
python -m pip install -e .
context-tree-auth login --allow-network # sign in for model access (browser device login)
context-tree --root <CTM directory> --open
```

The CTM directory holds the runtime data (memory, conversation, executor sessions, logs). It is private: keep it outside Git.

## Configuration

| Variable | Use |
|---|---|
| `CONTEXT_TREE_DATA_DIR` | Where credentials and caches live (default: the user's local application data) |
| `CONTEXT_TREE_PI_CLI` (or `PI_LOCAL_CLI`) | A pi build's bundled `cli.js`; without it, `pi` on `PATH` |
| `CONTEXT_TREE_GITHUB_TOKEN`, `CONTEXT_TREE_COPILOT_TOKEN` | Explicit credentials instead of the device login |
| `CONTEXT_TREE_HISTORY_DB`, `CONTEXT_TREE_HISTORY_LIB` | Optional archive of earlier sessions for the history import (`python -m context_tree.pilot.bootstrap`) |
| `CONTEXT_TREE_SESSIONS_DIR` | Claude Code session directory for the import |
| `CONTEXT_TREE_EXCLUDE_DIRS` | `;`-separated directories whose sessions the import leaves out |
| `CONTEXT_TREE_AUTOMATED_PREFIXES` | `;`-separated first-message prefixes of sessions started by your own automations |
| `CONTEXT_TREE_PROBE_PATTERNS` | `;`-separated regular expressions for your own connection-test messages (sessions of at most two such messages are left out) |
| `CT_LLM_DRAIN` | `1` (default) reads model streams to the end so connections are reused |

## Checks

```sh
for f in tests/test_*.py; do PYTHONPATH=src python "$f" || exit 1; done
```

The offline tests stub every model call. The browser check (`tests/browser_pilot_ui.py`, Playwright with Edge) changes data, so
run it against a copy of a CTM directory; see [docs/development.md](docs/development.md).

## Documentation

Start with [docs/README.md](docs/README.md): the concept model, goals and method (including the planned direction and its order),
the implementation plan, block evaluations, related work and the history of design choices. See also
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
