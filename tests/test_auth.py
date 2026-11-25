"""Synthetic authentication regression tests. No real credentials or endpoints."""
import contextlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

from context_tree.common import auth, llm
from context_tree.tools.auth import main

_ORIGINAL_PROTECT_DIRECTORY = auth._protect_directory


class Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status
        self.ok = 200 <= status < 300
        self.closed = False

    def json(self):
        return self.data

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected authentication request")
        return self.responses.pop(0)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = patch.dict(os.environ, {"CONTEXT_TREE_DATA_DIR": str(self.root),
            "CONTEXT_TREE_COPILOT_TOKEN": "", "CONTEXT_TREE_GITHUB_TOKEN": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        # Windows DACL has its own mocked test; functional tests never launch processes.
        if os.name == "nt":
            def directory(path):
                path.mkdir(parents=True, exist_ok=True)
            protection = patch.object(auth, "_protect_directory", side_effect=directory)
            protection.start()
            self.addCleanup(protection.stop)
        network = patch.object(requests, "request", side_effect=AssertionError("Live network forbidden"))
        network.start()
        self.addCleanup(network.stop)
        self.old = (llm._cached_token, llm._cached_token_expires_at, llm._cached_auth_source, llm._cached_api_base, dict(llm._model_cache))
        self.addCleanup(self.restore_llm)
        llm._cached_token = None
        llm._cached_auth_source = None
        llm._model_cache.clear()

    def restore_llm(self):
        llm._cached_token, llm._cached_token_expires_at, llm._cached_auth_source, llm._cached_api_base, models = self.old
        llm._model_cache.clear()
        llm._model_cache.update(models)

    def credential(self, expiry=9999999999, token="fixture-copilot"):
        return {"version": 1, "mode": "device", "github_token": "fixture-github",
                "copilot_token": token, "expires_at": expiry, "api_base": auth.api_base_from_token(token)}

    def device(self, **kwargs):
        return {"device_code": "fixture-secret-device", "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device", "expires_in": 900, "interval": 1, **kwargs}

    def save_credential(self, **kwargs):
        data = self.credential(**kwargs)
        auth._save_private(auth.credentials_path(), data)
        return data

    def test_status_is_local_and_contains_no_secrets(self):
        self.assertFalse(auth.status()["configured"])
        self.assertFalse(auth.auth_dir().exists())
        self.save_credential()
        data = auth.status()
        self.assertTrue(data["configured"])
        for secret in ("fixture-github", "fixture-copilot"):
            self.assertNotIn(secret, json.dumps(data))

    def test_private_atomic_storage(self):
        self.save_credential()
        self.assertEqual(auth.load_credentials()["github_token"], "fixture-github")
        self.assertFalse(list(auth.auth_dir().glob("tmp*")))
        if os.name != "nt":
            self.assertEqual(auth.auth_dir().stat().st_mode & 0o777, 0o700)
            self.assertEqual(auth.credentials_path().stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits only")
    def test_broad_permissions_refused(self):
        self.save_credential()
        auth.credentials_path().chmod(0o644)
        with self.assertRaises(auth.AuthenticationError):
            auth.load_credentials()

    def test_windows_protection_uses_dacl_not_chmod(self):
        with patch.object(auth, "os", SimpleNamespace(name="nt", environ=os.environ)):
            with patch.object(auth.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                _ORIGINAL_PROTECT_DIRECTORY(self.root / "protected")
                args = run.call_args.args[0]
                self.assertEqual(args[0], "powershell.exe")
                self.assertIn("-Command", args)
                self.assertEqual(run.call_args.kwargs["env"]["CONTEXT_TREE_AUTH_ACL_TARGET"], str(self.root / "protected"))
                self.assertNotIn("fixture-github", repr(run.call_args))

    def test_failed_permission_setup_never_writes_credential(self):
        with patch.object(auth, "_protect_directory", side_effect=auth.AuthenticationError("Permissions denied")):
            with self.assertRaises(auth.AuthenticationError):
                self.save_credential()
        self.assertFalse(auth.credentials_path().exists())

    def test_device_start_exposes_user_code_not_device_secret(self):
        response = Response(self.device())
        session = FakeSession(response)
        with patch.object(auth.webbrowser, "open", return_value=True) as browser:
            data = auth.start_device_login(session=session)
        self.assertEqual(data["user_code"], "ABCD-EFGH")
        self.assertNotIn("fixture-secret-device", json.dumps(data))
        self.assertTrue(auth.pending_path().exists())
        self.assertTrue(response.closed)
        browser.assert_called_once_with("https://github.com/login/device")
        self.assertEqual(session.calls[0][2]["data"]["scope"], "read:user")
        self.assertFalse(session.calls[0][2]["allow_redirects"])

    def test_credential_directory_inside_git_refused(self):
        self.root.joinpath(".git").mkdir()
        with self.assertRaisesRegex(auth.AuthenticationError, "outside Git"):
            _ORIGINAL_PROTECT_DIRECTORY(self.root / "auth")

    def test_untrusted_browser_url_refused(self):
        for url in ("file:///bad.exe", "https://github.com.evil/login/device", "http://github.com/login/device", "https://github.com/login/device?token=secret"):
            with self.subTest(url=url):
                with self.assertRaises(auth.AuthenticationError):
                    auth.start_device_login(session=FakeSession(Response(self.device(verification_uri=url))), open_browser=False)
        self.assertFalse(auth.pending_path().exists())

    def test_device_poll_pending_slowdown_success(self):
        auth.start_device_login(session=FakeSession(Response(self.device())), open_browser=False)
        now = [1000.0]
        pending = auth._read_private(auth.pending_path())
        pending["expires_at"] = 2000
        auth._save_private(auth.pending_path(), pending)
        delays = []
        def sleep(seconds):
            delays.append(seconds)
            now[0] += seconds
        session = FakeSession(Response({"error": "authorization_pending"}), Response({"error": "slow_down"}),
                              Response({"access_token": "fixture-github"}),
                              Response({"token": "fixture-copilot", "expires_at": 5000}))
        with patch.object(auth.time, "time", side_effect=lambda: now[0]):
            result = auth.complete_device_login(session=session, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(delays, [1, 1, 6])
        self.assertTrue(result["configured"])
        self.assertFalse(auth.pending_path().exists())
        self.assertEqual(auth.load_credentials()["github_token"], "fixture-github")
        self.assertNotIn("fixture-github", json.dumps(result))

    def test_denied_login_preserves_previous_working_credentials(self):
        self.save_credential()
        auth.start_device_login(session=FakeSession(Response(self.device())), open_browser=False)
        with self.assertRaises(auth.AuthenticationError):
            auth.complete_device_login(session=FakeSession(Response({"error": "access_denied", "error_description": "secret-value"})), sleep=lambda _: None)
        self.assertFalse(auth.pending_path().exists())
        self.assertEqual(auth.load_credentials()["copilot_token"], "fixture-copilot")

    def test_polling_timeout_keeps_pending_authorization(self):
        auth.start_device_login(session=FakeSession(Response(self.device())), open_browser=False)
        now = [1000.0]
        pending = auth._read_private(auth.pending_path())
        pending["expires_at"] = 2000
        auth._save_private(auth.pending_path(), pending)
        def sleep(seconds):
            now[0] += seconds
        with self.assertRaises(auth.AuthenticationError):
            auth.complete_device_login(timeout=2, session=FakeSession(Response({"error": "authorization_pending"})), clock=lambda: now[0], sleep=sleep)
        self.assertTrue(auth.pending_path().exists())

    def test_expired_device_removed(self):
        auth.start_device_login(session=FakeSession(Response(self.device())), open_browser=False)
        with self.assertRaises(auth.AuthenticationError):
            auth.complete_device_login(session=FakeSession(), clock=lambda: 9999999999, sleep=lambda _: None)
        self.assertFalse(auth.pending_path().exists())

    def test_provider_bodies_and_credentials_not_in_errors(self):
        response = Response({"token": "secret-provider-token", "error": "secret-value"}, 403)
        with self.assertRaises(auth.AuthenticationError) as caught:
            auth.exchange_github_token("secret-github", FakeSession(response))
        self.assertNotIn("secret", str(caught.exception))
        self.assertIn("403", str(caught.exception))
        self.assertTrue(response.closed)

    def test_no_credentials_no_other_agent_access(self):
        with patch.object(auth.subprocess, "run", side_effect=AssertionError("No external auth helper")):
            with self.assertRaises(auth.AuthenticationError):
                auth.get_saved_token(session=FakeSession())

    def test_valid_token_uses_no_network(self):
        self.save_credential()
        self.assertEqual(auth.get_saved_token(session=FakeSession())["copilot_token"], "fixture-copilot")

    def test_expired_token_renews_and_persists(self):
        self.save_credential(expiry=1)
        session = FakeSession(Response({"token": "renewed", "expires_at": 9999999999}))
        self.assertEqual(auth.get_saved_token(session=session)["copilot_token"], "renewed")
        self.assertEqual(auth.load_credentials()["copilot_token"], "renewed")
        self.assertEqual(len(session.calls), 1)

    def test_rejected_token_not_retried_if_refresh_returns_same(self):
        self.save_credential()
        with self.assertRaises(auth.AuthenticationError):
            auth.get_saved_token(force_refresh=True, session=FakeSession(Response({"token": "fixture-copilot", "expires_at": 9999999999})))

    def test_api_base_allowlist(self):
        token = "tid=fixture;exp=9999999999;proxy-ep=proxy.business.githubcopilot.com;"
        self.assertEqual(auth.api_base_from_token(token), "https://api.business.githubcopilot.com")
        for base in ("http://api.githubcopilot.com", "https://api.githubcopilot.com.evil", "https://api.githubcopilot.com/path", "https://secret@api.githubcopilot.com", "https://api.githubcopilot.com?x=secret"):
            with self.subTest(base=base), self.assertRaises(auth.AuthenticationError):
                auth.validate_api_base(base)

    def test_invalid_expiry_and_foreign_auth_modes_rejected(self):
        for value in (True, math.nan, "soon"):
            data = self.credential()
            data["expires_at"] = value
            auth._save_private(auth.credentials_path(), data)
            with self.assertRaises(auth.AuthenticationError):
                auth.load_credentials()
        data = self.credential()
        data["mode"] = "pi"
        auth._save_private(auth.credentials_path(), data)
        with self.assertRaises(auth.AuthenticationError):
            auth.load_credentials()

    def test_environment_priority_and_no_saved_access(self):
        with patch.dict(os.environ, {"CONTEXT_TREE_COPILOT_TOKEN": "fixture-direct", "CONTEXT_TREE_GITHUB_TOKEN": "fixture-github"}), \
                patch.object(auth, "get_saved_token", side_effect=AssertionError("Environment must win")):
            self.assertEqual(llm.get_token(), "fixture-direct")
            with self.assertRaises(RuntimeError):
                llm.get_token(force_refresh=True)

    def test_llm_saved_token_endpoint_and_catalog_reset(self):
        self.save_credential(token="tid=fixture;proxy-ep=proxy.individual.githubcopilot.com;")
        llm._model_cache["old-account"] = {"id": "old-account"}
        self.assertEqual(llm.get_token(), "tid=fixture;proxy-ep=proxy.individual.githubcopilot.com;")
        self.assertEqual(llm.get_api_base(), "https://api.individual.githubcopilot.com")
        self.assertFalse(llm._model_cache)

    def test_github_environment_exchange_cache_and_source_changes(self):
        with patch.dict(os.environ, {"CONTEXT_TREE_GITHUB_TOKEN": "first"}), \
                patch.object(auth, "exchange_github_token", return_value={"copilot_token": "bearer", "expires_at": 9999999999, "api_base": auth.DEFAULT_API_BASE}) as exchange:
            llm.get_token()
            llm.get_token()
            self.assertEqual(exchange.call_count, 1)
            os.environ["CONTEXT_TREE_GITHUB_TOKEN"] = "second"
            llm.get_token()
            self.assertEqual(exchange.call_count, 2)

    def test_access_check_no_inference(self):
        self.save_credential()
        session = FakeSession(Response({"data": [{"id": "model"}]}))
        result = auth.check_access(session)
        self.assertTrue(result["access_verified"])
        self.assertEqual(result["model_count"], 1)
        self.assertTrue(session.calls[0][1].endswith("/models"))
        self.assertNotIn("fixture-copilot", json.dumps(result))

    def test_logout_removes_only_owned_auth_files(self):
        self.save_credential()
        self.root.joinpath("unrelated.json").write_text("preserve", encoding="utf-8")
        auth.logout()
        self.assertFalse(auth.credentials_path().exists())
        self.assertTrue(self.root.joinpath("unrelated.json").exists())

    def test_cli_blocks_network_without_opt_in(self):
        with patch.object(sys, "argv", ["auth", "login"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main()
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(auth.auth_dir().exists())

    def test_cli_status_no_secret_output(self):
        self.save_credential()
        stream = io.StringIO()
        with patch.object(sys, "argv", ["auth", "status"]), contextlib.redirect_stdout(stream):
            main()
        self.assertTrue(json.loads(stream.getvalue())["configured"])
        self.assertNotIn("fixture-copilot", stream.getvalue())
        self.assertNotIn("fixture-github", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
