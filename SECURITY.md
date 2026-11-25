# Security and privacy

## What leaves the machine

CTM sends the user's messages, recent conversation, memory items, executor replies, file paths and tool traces to the configured
model provider (GitHub Copilot models through the project's own credentials). Embedding requests send their input text too. Local
SQLite storage does not make the system local-only.

## What runs, and what it may change

- **Executors** are pi coding-agent sessions started in the works' directories. They read and change files and run commands with
  the user's permissions. pi's own tool permissions apply; CTM adds an execution contract and a control step that stops, continues or
  asks the user, and asks before irreversible actions it can recognize. This is a judgment by a model, not a sandbox.
- **CTM itself** writes only its own data (the CTM directory) and `ctm.md` files next to objects. It adds `ctm.md` to the repository's
  local exclude list (`.git/info/exclude`) so that it is never committed. Executors only read `ctm.md`.
- There is no comprehensive prompt-injection defense. Text from files, web pages and tool results is treated as evidence, never as
  the user's instruction, but a model can still be misled. Use the system on data and accounts you are authorized to use.

## Private data

The CTM directory (memory, conversation, executor sessions, logs, usage records), session archives, credentials, evaluation data and
model outputs are private. Keep them outside Git; `.gitignore` is a guardrail, not a security boundary. The SQLite files are not
encrypted by this application; filesystem permissions, disk encryption and backups are the operator's responsibility.

Credentials come from explicit environment variables or the opt-in device login of `context-tree-auth`, which never displays access
tokens and refuses to store credentials inside a Git worktree. See [docs/authentication.md](docs/authentication.md).

## Reporting

No public security contact has been configured. Do not post private logs or transcripts publicly; contact the maintainer through an
existing private channel with minimal, sanitized reproduction steps.

## Release status

This is a research prototype under the [MIT License](LICENSE), provided as is. Offline tests are not a security audit.
