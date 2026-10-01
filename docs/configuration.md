# Configuration and operation

## Paths

No default points to the former application database or device ID.

| Setting | Default / behavior |
|---|---|
| `CONTEXT_TREE_DATA_DIR` | Overrides all platform data-directory defaults |
| macOS data | `~/Library/Application Support/context-tree` |
| Linux data | `$XDG_DATA_HOME/context-tree`, otherwise `~/.local/share/context-tree` |
| Windows data | `%LOCALAPPDATA%/context-tree` |
| Default DB | `context-tree.db` under the data directory |
| Default cache | `cache/` under the data directory |
| `--db PATH` | Explicit DB; default cache becomes a sibling `<db-stem>-cache/` |
| `--cache-dir PATH` | Explicit cache override |
| `CONTEXT_TREE_SESSIONS_DIR` | Source-session root; otherwise `~/.claude/projects` |
| `--sessions-dir PATH` | Pipeline CLI override for source discovery |

Device identity is generated lazily under the independent data directory only when needed. Importing the package, asking for help and running synthetic offline fixtures do not access the original application's keychain/data directories.

## Credentials

Set one explicit environment variable outside the repository:

- `CONTEXT_TREE_COPILOT_TOKEN`: short-lived bearer token. The application cannot renew an externally supplied bearer; replace it after expiry/rejection.
- `CONTEXT_TREE_GITHUB_TOKEN`: token eligible for the inherited experimental Copilot token-exchange flow. Access is account-dependent; no promise is made that arbitrary PAT scopes work.

The transport uses Copilot's model directory, Chat Completions/Responses and embedding endpoints. These are experimental integrations, not a supported public-provider SDK contract. Verify service terms and your authorization before use. No login/device-flow helper or new secret storage is implemented.

Authentication and all provider calls are implemented in `src/context_tree/common/llm.py`. Credential acquisition is outside this prototype: obtain an authorized token through your account's approved tooling or administrator. Do not scrape another application's credential store. If no supported token is available, use the offline stages and fixtures; online onboarding is not yet self-contained.

Missing credentials fail explicitly; the code never silently reads another app's keychain. Do not pass credentials as command-line arguments or include them in benchmark input.

## Network permission and budgets

The pipeline CLI requires global `--allow-network` for `models`, `sync` and `retrieve`. Independent stage and evaluation CLIs also require explicit permission for provider calls. Lower-level Python APIs are not a sandbox.

`--request-limit N` counts actual inference/embedding requests, including transport retries. Catalog/auth requests are not inference requests. A budget is not a dollar cap: model pricing, reasoning tokens and cache accounting differ. Exhaustion can leave an incomplete experiment; do not report that as successful completion.

## Model configuration

The migrated defaults are research choices from a small independent-stage screen:

| Runtime role | Model | Effort |
|---|---|---|
| extract | GPT-5.6 Sol Fast | low |
| tree | Grok 4.6 | low |
| review | Gemini 3.6 Flash | minimal |
| reflexion | GPT-5.6 Sol Fast | low |
| framing | GPT-5.6 Sol Fast | low |
| retrieve (next action) | Gemini 3.6 Flash | minimal |
| context (assembly) | GPT-5.6 Sol Fast | low |
| resolve (rare semantic decisions) | Gemini 3.6 Flash | minimal |

Exact IDs and defaults live in `common/llm.py`. Availability must be checked on the active account. Resolve was not comprehensively rebenchmarked; embedding remains `text-embedding-3-small`. Gemini 3.8 was absent from the latest independent-stage screen. These defaults are not universal recommendations.

```sh
context-tree --allow-network models
context-tree --allow-network --db ./artifacts/demo.db --request-limit 8 \
  retrieve "Continue CSV work" --mode agent \
  --stage-model retrieve=AVAILABLE_MODEL --stage-effort retrieve=SUPPORTED_EFFORT \
  --stage-model context=ANOTHER_MODEL --stage-effort context=SUPPORTED_EFFORT
```

`--model` overrides all model-backed roles for that pipeline command. A per-stage override takes precedence. Effort must be supported by the selected model's catalog entry. No silent model fallback is performed.

## CLI argument ordering

Global options appear before the command; command options follow it:

```sh
context-tree --db ./artifacts/demo.db stats
context-tree --db ./artifacts/demo.db index-identifiers
context-tree --db ./artifacts/demo.db export-obsidian --out ./exports/demo
```

`index-identifiers` uses stored snapshots and no LLM; run it on a copy before modifying a valuable database. Export opens its source read-only but creates Markdown that may contain private information.

## Compatibility limits

Turn schema version 2 changed response ownership. Older databases are not automatically reinterpreted; use a new DB/cache for rebuilding. Do not mix embedding spaces or import old snapshots as verified gold.

On POSIX main-thread calls, a stream watchdog temporarily installs SIGALRM only if no existing real-time timer is active. The previous handler is restored. Other threads/platforms rely on socket timeouts and chunk-level elapsed checks; this is not a strict cross-platform whole-request deadline.

Missing original logs cannot be repaired from lossy extraction snapshots. A saved database can support query regression without proving that the current adapter could reconstruct the same history.
