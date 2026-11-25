# Standalone GitHub/Copilot Login Tool

The tool is in the **context-tree project**: `src/context_tree/tools/auth.py`. Its command entry point is
`context-tree-auth`. It does not modify pi or read or reuse credentials from pi, VS Code, or other agents.

## Login

After installing this project:

```sh
context-tree-auth login --allow-network
```

If the command entry point is not yet installed, use the Python module from the repository root; first make the package importable through an editable install or
`PYTHONPATH=src`:

```sh
python -m context_tree.tools.auth login --allow-network
```

The tool requests a GitHub OAuth device code, opens `https://github.com/login/device`,
and displays a short-lived **user code**. The user signs in to their own account in the browser, enters the code, and confirms authorization.
An agent cannot enter the account password or confirm authorization on the user's behalf.

This flow uses an experimental Copilot device authorization protocol and a public OAuth client ID. It requires the account to have
Copilot access and comply with the terms of service; it is not a public SDK that guarantees all GitHub PATs will work.
Currently, only github.com is supported; custom GitHub Enterprise Server domains are not included.

### Two-step adaptation for coding agent tool calls

By default, `login` returns immediately after displaying the code and does not start a hidden background polling process. This lets the coding
agent give the code to the user without blocking until the authorization expires before displaying it.

After approving in the browser, run:

```sh
context-tree-auth complete --allow-network --timeout 180
```

The tool polls for the authorization result, obtains a GitHub OAuth access token, then exchanges it for a short-lived Copilot bearer
and saves it. `authorization_pending` causes it to wait; `slow_down` increases and saves the polling interval.
Denial or expiration stops the process; it does not retry indefinitely. If a short polling attempt times out but the device code is still valid, complete can be run again.
A failed login does not overwrite previously usable credentials.

When operating directly in an interactive terminal, the user can also wait in a single step:

```sh
context-tree-auth login --wait --allow-network
```

`--no-browser` prevents the browser from opening automatically, but still displays the verification link and user code.
**The user code is not an access token**; it is only used for the current short-lived device authorization. The tool does not display the secret
`device_code`, GitHub access token, or Copilot bearer.

## Credential Location and Permissions

Default Windows location:

```text
%LOCALAPPDATA%/context-tree/auth/copilot-credentials.json
```

Other platforms use the project's data directory (`context_tree.common.config.data_dir`).
`CONTEXT_TREE_DATA_DIR` can override the location, but paths inside a Git worktree are rejected when saving authentication files.
The tool code is in the repository; credentials must not be placed in the repository.

- POSIX: authentication directory `0700`, credential file `0600`.
- Windows: explicitly sets a protected DACL; only the current user and SYSTEM have access.
- Saving uses a temporary file in the same directory, flush/fsync, and atomic replacement; symbolic links for the authentication directory or file are rejected.
- Tokens are plain-text JSON, not an encrypted vault. Disk encryption, backups, and user account security must still be protected separately.
- Pending device codes are temporarily stored in the same private directory and removed on completion, denial, or expiration.
- Authentication response bodies, secrets, and subprocess output are not written to logs or displayed in the terminal.

## View Status and Verify

```sh
context-tree-auth status
context-tree-auth status --check --allow-network
```

`status` only checks local metadata and returns the save location, login mode, validity period, whether it has expired, and whether an
environment variable override exists. It does not read the authentication status of other applications.

`--check` fetches the Copilot model catalog to verify access and returns the number of entries in the catalog; it does not perform inference.
This count does not guarantee that every model is authorized for use; model policy remains subject to the actual account capabilities.

```sh
context-tree-auth logout
```

Only deletes this project's credentials and pending authorization data; it does not affect other agent logins or revoke server-side authorization on GitHub.
To revoke it, use the authorized applications settings on GitHub.

## Model Transport Integration

`common/llm.py` selects credentials in the following order of priority:

1. `CONTEXT_TREE_COPILOT_TOKEN`: explicit short-lived bearer; if rejected, asks the user to replace it.
2. `CONTEXT_TREE_GITHUB_TOKEN`: explicit GitHub token; attempts a normal exchange.
3. Project-private credentials created by this tool.

When the Copilot bearer in the private credentials is about to expire, it is renewed normally using the GitHub OAuth token saved by this project.
A 401 triggers an attempt to renew it; if the same rejected token is still returned, it stops and asks the user to log in again.
Logging in again does not bypass authorization by reading tokens from other applications.

The API address is derived from the token's proxy endpoint. Only official GitHub Copilot domains over HTTPS
are allowed, to avoid sending the Authorization header to arbitrary addresses. Environment variable overrides follow the same
address validation. The in-process model catalog cache is cleared when switching accounts.

These authentication/model catalog requests do not count against the inference request budget; `sync`, `retrieve`, and model evaluation
still require a separate `--allow-network`. A successful login does not mean that uploading all private history is permitted.

## Tests

```sh
python -m unittest discover -s tests -p test_auth.py -v
```

The tests use fictional tokens and mock requests, covering safe output, device authorization waiting／slowdown／denial／
expiration, saving and renewal, environment variable precedence, API address validation, and Windows ACL commands.
They do not log in to real accounts, read or modify the user's existing credentials, or call real models.
