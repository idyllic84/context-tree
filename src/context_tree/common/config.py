"""Standalone paths without filesystem or credential access at import time."""
import os
import sys
from pathlib import Path


def data_dir() -> Path:
    configured = os.environ.get("CONTEXT_TREE_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/context-tree"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "context-tree"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "context-tree"


def sessions_dir() -> Path:
    return Path(os.environ.get("CONTEXT_TREE_SESSIONS_DIR", Path.home() / ".claude/projects")).expanduser().resolve()
