# Security and privacy

## Data boundary

Context Tree processes conversations, source file paths, instructions and model-generated summaries. These may contain secrets, confidential code, personal information or untrusted instructions.

- Online extraction, review, framing and retrieval send selected text to the configured provider.
- Embedding requests also transmit their input text; local SQLite storage does not make the whole pipeline local-only.
- No comprehensive secret-redaction or prompt-injection defense is implemented.
- Historical text and retrieved snippets are evidence, not authority to execute commands or override current instructions.
- Model-generated tree mutations and JSON are validated in places, but not every adversarial shape is handled safely. Use controlled inputs.

## Safe defaults and operator responsibilities

CLI operations requiring provider access require `--allow-network`. Stage runners default to blocking transport. Python library calls are lower-level APIs: callers are responsible for their network policy.

Credentials are read only from explicitly named environment variables. No original application keychain is accessed. Use a secret manager or temporary shell environment; do not commit credentials. A short-lived bearer token must be replaced when it expires.

Use a selected source directory, a session filter and a finite request budget. Without a session filter, sync can process every discovered conversation. Review the payload before authorizing its transmission. Only use accounts, endpoints and data you are authorized to access.

Databases, cache files, device IDs, exported vaults and model evaluation results are private artifacts. `.gitignore` is a guardrail, not a security boundary. Do not store them under versioned examples. Inspect files before publishing or sharing.

The SQLite database is not encrypted by this application. Filesystem permissions, disk encryption, backup policies and deletion remain the operator's responsibility. Exported Obsidian content can reveal full paths and session relationships.

## Reporting

No public repository or security-reporting contact has been configured. Do not invent a reporting address or post private logs publicly. Contact the person who supplied this repository through an existing private channel; include minimal sanitized reproduction steps, not tokens or full conversation transcripts.

## Release status

This is a research prototype with [licensing pending](LICENSE-STATUS.md). Packaging checks and offline fixtures are not a security audit. Public release requires a fresh privacy, authorization and dependency review.
