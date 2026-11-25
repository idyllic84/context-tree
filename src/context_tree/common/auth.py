"""Independent Copilot device authorization and project-owned private storage.

Never reads another agent's credentials or invokes its authentication helper.
Browser confirmation belongs to the user; access tokens are never displayed.
"""
import base64
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
import webbrowser

import requests

from .config import data_dir

# Public OAuth application ID used by the inherited Copilot device flow, not a secret.
CLIENT_ID = base64.b64decode("SXYxLmI1MDdhMDhjODdlY2ZlOTg=").decode()
GITHUB_DEVICE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_API_BASE = "https://api.githubcopilot.com"
COPILOT_HEADERS = {
    "User-Agent": "GitHubCopilotChat/0.35.0",
    "Editor-Version": "vscode/1.107.0",
    "Editor-Plugin-Version": "copilot-chat/0.35.0",
    "Copilot-Integration-Id": "vscode-chat",
}


class AuthenticationError(RuntimeError):
    """Messages deliberately contain no provider response bodies or credentials."""


def auth_dir() -> Path:
    return data_dir() / "auth"


def credentials_path() -> Path:
    return auth_dir() / "copilot-credentials.json"


def pending_path() -> Path:
    return auth_dir() / "copilot-device-pending.json"


def _protect_directory(directory: Path):
    if any((parent / ".git").exists() for parent in (directory.resolve(), *directory.resolve().parents)):
        raise AuthenticationError("Credentials must be outside Git worktrees; choose a private CONTEXT_TREE_DATA_DIR")
    if directory.is_symlink():
        raise AuthenticationError("Refusing a symlinked authentication directory")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
        return
    # chmod on Windows does not restrict read access. Set an explicit protected
    # DACL for the current user and SYSTEM, inherited by files created below it.
    script = """$ErrorActionPreference = 'Stop'
$Target = [Environment]::GetEnvironmentVariable('CONTEXT_TREE_AUTH_ACL_TARGET')
$User = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$System = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$Acl = [System.IO.Directory]::GetAccessControl(
    $Target, [System.Security.AccessControl.AccessControlSections]::Access)
$Acl.SetAccessRuleProtection($true, $false)
foreach ($Rule in @($Acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]))) {
    $Acl.RemoveAccessRuleSpecific($Rule)
}
foreach ($Sid in @($User, $System)) {
    $Rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $Sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $Acl.AddAccessRule($Rule)
}
[System.IO.Directory]::SetAccessControl($Target, $Acl)
"""
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=20,
            env=dict(os.environ, CONTEXT_TREE_AUTH_ACL_TARGET=str(directory)))
    except (OSError, subprocess.TimeoutExpired):
        raise AuthenticationError("Cannot establish private Windows authentication permissions") from None
    if result.returncode:
        raise AuthenticationError("Cannot establish private Windows authentication permissions")


def _save_private(path: Path, value: dict):
    _protect_directory(path.parent)
    if path.is_symlink():
        raise AuthenticationError("Refusing a symlinked credential file")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
            temporary = Path(handle.name)
            if os.name != "nt":
                temporary.chmod(0o600)
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _read_private(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or path.parent.is_symlink():
        raise AuthenticationError("Refusing symlinked authentication data")
    if os.name != "nt":
        if path.stat().st_mode & 0o077 or path.parent.stat().st_mode & 0o077:
            raise AuthenticationError("Authentication file/directory permissions are too broad")
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        raise AuthenticationError("Saved authentication data is unreadable or malformed") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise AuthenticationError("Unsupported authentication data")
    return data


def load_credentials() -> dict | None:
    data = _read_private(credentials_path())
    if data is not None:
        if data.get("mode") != "device" or not isinstance(data.get("copilot_token"), str) or not data["copilot_token"]:
            raise AuthenticationError("Invalid saved Copilot authentication")
        expiry = data.get("expires_at")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
            raise AuthenticationError("Invalid saved token expiry")
        if validate_api_base(data.get("api_base", DEFAULT_API_BASE)) != api_base_from_token(data["copilot_token"]):
            raise AuthenticationError("Saved API endpoint does not match the Copilot token")
        if not isinstance(data.get("github_token"), str) or not data["github_token"]:
            raise AuthenticationError("Device login has no renewal credential")
    return data


def validate_api_base(value: str) -> str:
    if not isinstance(value, str):
        raise AuthenticationError("Invalid Copilot API endpoint")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise AuthenticationError("Invalid Copilot API endpoint") from None
    if (url.scheme != "https" or url.username or url.password or port not in (None, 443)
            or url.path not in ("", "/") or url.query or url.fragment
            or not re.fullmatch(r"api(?:\.[a-z0-9-]+)*\.githubcopilot\.com", url.hostname or "")):
        raise AuthenticationError("Refusing an untrusted Copilot API endpoint")
    return value.rstrip("/")


def api_base_from_token(token: str) -> str:
    match = re.search(r"(?:^|;)proxy-ep=([^;]+)", token)
    if match:
        return validate_api_base("https://" + re.sub(r"^proxy\.", "api.", match.group(1)))
    return DEFAULT_API_BASE


def _request_json(session, method: str, url: str, **kwargs) -> dict:
    try:
        response = session.request(method, url, timeout=30, allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise AuthenticationError("Authentication network request failed") from None
    try:
        if not response.ok or 300 <= response.status_code < 400:
            raise AuthenticationError(f"Authentication endpoint returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise AuthenticationError("Authentication endpoint did not return JSON") from None
        if not isinstance(data, dict):
            raise AuthenticationError("Invalid authentication response")
        return data
    finally:
        response.close()


def exchange_github_token(token: str, session=requests) -> dict:
    data = _request_json(session, "GET", COPILOT_TOKEN_URL,
                         headers={"Authorization": "Bearer " + token, "Accept": "application/json", **COPILOT_HEADERS})
    bearer, expiry = data.get("token"), data.get("expires_at")
    if (not isinstance(bearer, str) or not bearer or isinstance(expiry, bool)
            or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= time.time() + 60):
        raise AuthenticationError("Invalid or already expired Copilot token response")
    return {"copilot_token": bearer, "expires_at": expiry, "api_base": api_base_from_token(bearer)}


def start_device_login(*, open_browser: bool = True, session=requests) -> dict:
    _protect_directory(auth_dir())
    data = _request_json(session, "POST", GITHUB_DEVICE_URL,
                         headers={"Accept": "application/json", **COPILOT_HEADERS},
                         data={"client_id": CLIENT_ID, "scope": "read:user"})
    for key in ("device_code", "user_code", "verification_uri"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise AuthenticationError("Invalid device authorization response")
    expiry, interval = data.get("expires_in"), data.get("interval", 5)
    if (isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not 0 < expiry <= 3600
            or isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 < interval <= 60):
        raise AuthenticationError("Invalid device authorization timing")
    uri = urlsplit(data["verification_uri"])
    if uri.scheme != "https" or uri.hostname != "github.com" or uri.path != "/login/device" or uri.username or uri.password or uri.port not in (None, 443) or uri.query or uri.fragment:
        raise AuthenticationError("Refusing an untrusted device verification URL")
    pending = {"version": 1, "device_code": data["device_code"], "user_code": data["user_code"],
               "verification_uri": data["verification_uri"], "expires_at": time.time() + expiry, "interval": interval}
    _save_private(pending_path(), pending)
    browser_opened = False
    if open_browser:
        try:
            browser_opened = bool(webbrowser.open(data["verification_uri"]))
        except webbrowser.Error:
            pass
    # Device code is secret; only the short user code is shown for browser approval.
    return {"status": "awaiting_browser_approval", "verification_uri": data["verification_uri"],
            "user_code": data["user_code"], "expires_in": expiry, "browser_opened": browser_opened}


def complete_device_login(*, timeout: int = 180, session=requests, sleep=time.sleep, clock=time.time) -> dict:
    if not 1 <= timeout <= 900:
        raise AuthenticationError("Authorization polling timeout must be 1..900 seconds")
    pending = _read_private(pending_path())
    if not pending or not isinstance(pending.get("device_code"), str):
        raise AuthenticationError("Start device login first")
    expiry, interval = pending.get("expires_at"), pending.get("interval", 5)
    if not isinstance(expiry, (int, float)) or not isinstance(interval, (int, float)) or interval <= 0:
        raise AuthenticationError("Invalid pending authorization timing")
    deadline = min(expiry, clock() + timeout)
    while clock() < deadline:
        delay = min(interval, max(0, deadline - clock()))
        sleep(delay)
        if clock() >= deadline:
            break
        data = _request_json(session, "POST", GITHUB_ACCESS_URL,
            headers={"Accept": "application/json", **COPILOT_HEADERS},
            data={"client_id": CLIENT_ID, "device_code": pending["device_code"],
                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        github_token = data.get("access_token")
        if isinstance(github_token, str) and github_token:
            credential = {"version": 1, "mode": "device", "created_at": clock(), "github_token": github_token,
                          **exchange_github_token(github_token, session)}
            _save_private(credentials_path(), credential)
            pending_path().unlink(missing_ok=True)
            return status()
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            pending["interval"] = interval
            _save_private(pending_path(), pending)
            continue
        if error in ("access_denied", "expired_token"):
            pending_path().unlink(missing_ok=True)
            raise AuthenticationError("Device authorization was denied or expired")
        raise AuthenticationError("Device authorization failed")
    if clock() >= expiry:
        pending_path().unlink(missing_ok=True)
        raise AuthenticationError("Device authorization expired; start again")
    raise AuthenticationError("Still awaiting approval; run complete again within the device-code lifetime")


def get_saved_token(*, force_refresh: bool = False, session=requests) -> dict:
    data = load_credentials()
    if not data:
        raise AuthenticationError("No project credentials; run context-tree-auth login or configure an explicit environment token")
    if not force_refresh and data["expires_at"] > time.time() + 60:
        return data
    refreshed = exchange_github_token(data["github_token"], session)
    if force_refresh and refreshed["copilot_token"] == data["copilot_token"]:
        raise AuthenticationError("Authentication helper returned the rejected token; log in again")
    current = load_credentials()
    if current is None or current != data:
        raise AuthenticationError("Credentials changed during refresh; retry with the current login")
    data.update(refreshed, refreshed_at=time.time())
    _save_private(credentials_path(), data)
    return data


def check_access(session=requests) -> dict:
    data = get_saved_token(session=session)
    models = _request_json(session, "GET", validate_api_base(data["api_base"]) + "/models",
                           headers={"Authorization": "Bearer " + data["copilot_token"],
                                    "Accept": "application/json", **COPILOT_HEADERS})
    if not isinstance(models.get("data"), list):
        raise AuthenticationError("Copilot did not return a model directory")
    return {**status(), "access_verified": True, "model_count": len(models["data"])}


def status() -> dict:
    data = load_credentials()
    return {"configured": data is not None, "path": str(credentials_path()),
            "mode": data.get("mode") if data else None,
            "expires_at": data.get("expires_at") if data else None,
            "expired": data["expires_at"] <= time.time() + 60 if data else None,
            "pending_device_login": pending_path().exists(),
            "environment_override": bool(os.environ.get("CONTEXT_TREE_COPILOT_TOKEN", "").strip() or os.environ.get("CONTEXT_TREE_GITHUB_TOKEN", "").strip())}


def logout():
    for path in (credentials_path(), pending_path()):
        if path.is_symlink():
            raise AuthenticationError("Refusing symlinked authentication data")
        path.unlink(missing_ok=True)
