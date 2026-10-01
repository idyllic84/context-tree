"""Offline stage, packaging and isolation checks without provider calls."""
import argparse
import importlib
import io
import json
import os
from pathlib import Path
import pkgutil
import signal
import subprocess
import sys
import tempfile
from unittest.mock import patch

from ..common import llm, store
from ..common.evaluation_runner import MODEL_STAGES, LOCAL_STAGES, offline
from ..common.models import AtomicUnit, DialogueTurn, Goal, Task, Session
from ..stages.ingest import processor as ingest
from ..stages.extract import processor as extract
from ..stages.tree.state import TreeStateMachine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imports-only", action="store_true")
    args = parser.parse_args()
    import context_tree
    with patch.object(llm._SESSION, "request", side_effect=AssertionError("Unexpected network call")):
        for module in pkgutil.walk_packages(context_tree.__path__, context_tree.__name__ + "."):
            if not module.name.endswith(".__main__"):
                importlib.import_module(module.name)
        if args.imports_only:
            print("Package imports passed")
            return
        print(json.dumps(offline(MODEL_STAGES + LOCAL_STAGES), indent=2))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"CONTEXT_TREE_DATA_DIR": str(root/'data')}, clear=False):
                store.configure_paths(str(root/'checks.db'))
                assert not (root/'data').exists()
                conn = store.connect()
                session = Session("check", "/example", "check", [Goal("g4", "CSV", tasks=[
                    Task("t7", "CSV parser", "g4", "goal", linked_unit_ids=["u9"])], last_accessed_at=42)],
                    [DialogueTurn(0, "", "parse_csv", "Implement CSV", units=[AtomicUnit("u9", "agent", "propose", "parse_csv", for_task_id="t7")])])
                with conn:
                    store.mark_processed(conn, "check", 1, tree_json=json.dumps(session.to_dict()), schema_version=2)
                with conn:
                    store.mark_processed(conn, "check", 2)
                assert json.loads(store.get_processing_state(conn, "check")["task_tree_json"])["goals"]
                before = conn.execute("SELECT message_count FROM processing_state WHERE session_id='check'").fetchone()[0]
                try:
                    with conn:
                        store.mark_processed(conn, "check", 99)
                        raise RuntimeError("rollback")
                except RuntimeError:
                    pass
                assert conn.execute("SELECT message_count FROM processing_state WHERE session_id='check'").fetchone()[0] == before
                assert store.load_cached_turns("absent") == [] and not store.CACHE_DIR.exists()
                store.save_cached_turns("check", [t.to_dict() for t in session.turns])
                assert len(store.load_cached_turns("check")) == 1
                (store.CACHE_DIR/'old.json').write_text('[]', encoding='utf-8')
                try:
                    store.load_cached_turns("old")
                    raise AssertionError("Legacy cache silently accepted")
                except ValueError:
                    pass
                sm = TreeStateMachine(session)
                assert sm._goal_counter == 4 and sm._task_counter == 7
                assert sm.apply_mutations([{"op": "reparent", "task_id": "t7", "new_parent_id": "t7"}], [])
                assert sm._goal_by_id["g4"].last_accessed_at == 42
                conn.close()
                identity = ingest.get_device_id()
                assert ingest.get_device_id() == identity
                assert (root/'data/device_id').exists()
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HOME=str(root/'fresh-home'),
                       CONTEXT_TREE_DATA_DIR=str(root/'fresh-data'), XDG_DATA_HOME=str(root/'fresh-xdg'))
            subprocess.run([sys.executable, "-B", "-c", "import context_tree.pipeline.cli; import context_tree.tools.benchmark_models"],
                           env=env, cwd=root, check=True)
            assert not (root/'fresh-data').exists() and not (root/'fresh-home').exists()
        from ..stages.tree.run import run as run_tree
        from ..stages.tree.evaluate import cases as tree_cases
        from types import SimpleNamespace
        prior_case = tree_cases()[1]

        def apply_feedback(sm, units, **kwargs):
            assert "u11" in sm._unit_by_id
            mutations = [{"op": "reject_propose", "task_id": "t2", "unit_id": "u11", "correction_text": "retry once"}]
            assert not sm.apply_mutations(mutations, units)
            return mutations

        with patch("context_tree.stages.tree.run.build_tree_for_batch", side_effect=apply_feedback):
            output = run_tree({"session": prior_case.fixture["session"], "units": prior_case.fixture["units"]}, SimpleNamespace())
            assert any(u["id"] == "u11" for turn in output["session"]["turns"] for u in turn["units"])
        from . import export_obsidian
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            export_obsidian.write_session_md(vault, "../../outside", {"goals": []})
            assert all(p.resolve().is_relative_to(vault.resolve()) for p in vault.rglob("*.md"))
            try:
                export_obsidian.write_page(vault, "sessions", "../../outside.md", ["blocked"])
                raise AssertionError("Export path escape accepted")
            except ValueError:
                pass
        if hasattr(signal, "SIGALRM"):
            before = signal.getsignal(signal.SIGALRM)
            with llm._watchdog_scope():
                llm._set_alarm(0)
            assert signal.getsignal(signal.SIGALRM) == before
        with patch.dict(os.environ, {"CONTEXT_TREE_COPILOT_TOKEN": "fixture-token", "CONTEXT_TREE_GITHUB_TOKEN": ""}):
            assert llm.get_token() == "fixture-token"
        with patch.dict(os.environ, {"CONTEXT_TREE_COPILOT_TOKEN": "", "CONTEXT_TREE_GITHUB_TOKEN": ""}):
            llm._cached_token = None
            try:
                llm.get_token()
                raise AssertionError("Missing explicit credentials accepted")
            except RuntimeError:
                pass
    print("Offline isolation, cache, transaction, ID and transport checks passed")


if __name__ == "__main__":
    main()
