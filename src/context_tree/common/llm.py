"""Copilot chat/Responses streaming, stage settings, request budgets and embeddings."""

import re
import json
import time
import signal
import os
import threading
import hashlib
from contextlib import contextmanager
import requests

from . import auth

MODEL_CHEAP = "gemini-3.6-flash"
MODEL_SMART = "gemini-3.6-flash"
STAGES = ("extract", "tree", "review", "reflexion", "framing", "resolve", "retrieve", "context")
DEFAULT_STAGE_MODELS = {
    "extract": "gemini-4-argon", "tree": "grok-4.6",
    "review": "gemini-3.6-flash", "reflexion": "gemini-4-argon",
    "framing": "gemini-4-argon", "resolve": "gemini-3.6-flash",
    "retrieve": "gemini-3.6-flash", "context": "gemini-4-argon",
}
DEFAULT_STAGE_EFFORTS = {
    stage: "minimal" if model.startswith("gemini-") else "low"
    for stage, model in DEFAULT_STAGE_MODELS.items()
}
STAGE_MODELS = dict(DEFAULT_STAGE_MODELS)
STAGE_EFFORTS: dict[str, str] = dict(DEFAULT_STAGE_EFFORTS)
CALL_METRICS: list[dict] = []
REQUEST_LIMIT: int | None = None
REQUEST_COUNT = 0


class RequestBudgetExceeded(RuntimeError):
    pass


def _count_request():
    global REQUEST_COUNT
    if REQUEST_LIMIT is not None and REQUEST_COUNT >= REQUEST_LIMIT:
        raise RequestBudgetExceeded(f"Model request limit reached ({REQUEST_LIMIT})")
    REQUEST_COUNT += 1


def configure_stages(model: str | None = None, overrides: list[str] = (),
                     efforts: list[str] = ()):
    for stage in STAGES:
        STAGE_MODELS[stage] = model or DEFAULT_STAGE_MODELS[stage]
    STAGE_EFFORTS.clear()
    if not model:
        STAGE_EFFORTS.update(DEFAULT_STAGE_EFFORTS)
    for settings, target in ((overrides, STAGE_MODELS), (efforts, STAGE_EFFORTS)):
        for setting in settings:
            stage, sep, value = setting.partition("=")
            if stage not in STAGES or not sep or not value:
                raise ValueError(f"Expected stage=value for one of {', '.join(STAGES)}")
            target[stage] = value
            if target is STAGE_MODELS:
                STAGE_EFFORTS.pop(stage, None)


_cached_token = None
_cached_token_expires_at = 0.0  # epoch seconds; 0 = unknown
_cached_auth_source = None
_cached_api_base = auth.DEFAULT_API_BASE

# Module-level Session for connection pooling. Pool size set generously to
# allow framing-pass concurrency room (currently sequential but future-proofed).
_SESSION = requests.Session()
_DRAIN = os.environ.get('CT_LLM_DRAIN', '1') == '1'   # read streams to their end so connections are reused
_adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16)
_SESSION.mount("https://", _adapter)


class _StreamTimeout(Exception):
    """Raised by SIGALRM when stream stalls."""
    pass


def _alarm_handler(signum, frame):
    raise _StreamTimeout("stream watchdog fired")


@contextmanager
def _watchdog_scope():
    enabled = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    previous = None
    if enabled and signal.getitimer(signal.ITIMER_REAL)[0] == 0:
        previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _alarm_handler)
    try:
        yield
    finally:
        if previous is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)


def _set_alarm(seconds):
    if (hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
            and signal.getsignal(signal.SIGALRM) is _alarm_handler):
        signal.alarm(seconds)


def get_token(force_refresh: bool = False) -> str:
    """Explicit environment overrides, then our opt-in private authentication file."""
    global _cached_token, _cached_token_expires_at, _cached_auth_source, _cached_api_base
    now = time.time()
    direct = os.environ.get("CONTEXT_TREE_COPILOT_TOKEN", "").strip()
    pat = os.environ.get("CONTEXT_TREE_GITHUB_TOKEN", "").strip()
    if direct:
        if force_refresh:
            raise RuntimeError("Copilot bearer token was rejected; replace CONTEXT_TREE_COPILOT_TOKEN")
        source = "direct:" + hashlib.sha256(direct.encode()).hexdigest()
        data = {"copilot_token": direct, "expires_at": 0, "api_base": auth.api_base_from_token(direct)}
    elif pat:
        source = "github:" + hashlib.sha256(pat.encode()).hexdigest()
        if not force_refresh and source == _cached_auth_source and _cached_token and now < _cached_token_expires_at - 60:
            return _cached_token
        data = auth.exchange_github_token(pat, session=_SESSION)
    else:
        data = auth.get_saved_token(force_refresh=force_refresh, session=_SESSION)
        source = "saved:" + hashlib.sha256(data["copilot_token"].encode()).hexdigest()
    if source != _cached_auth_source:
        _model_cache.clear()
    _cached_auth_source = source
    _cached_token = data["copilot_token"]
    _cached_token_expires_at = data["expires_at"]
    _cached_api_base = auth.validate_api_base(data["api_base"])
    return _cached_token


def get_api_base() -> str:
    get_token()
    return _cached_api_base


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **auth.COPILOT_HEADERS,
            "Openai-Intent": "conversation-panel", "Content-Type": "application/json"}


def chat(system: str, user: str, model: str | None = None, timeout: int = 180,
          read_timeout: int = 30,
          no_content_timeout: int = 45,
          idle_content_timeout: int = 20, *, stage: str | None = None,
          reasoning_effort: str | None = None, max_output_tokens: int | None = None,
          response_schema: dict | None = None) -> dict:
    configured_model = STAGE_MODELS.get(stage, MODEL_SMART)
    model = model or configured_model
    if re.search(r'(^|[-_.])sol($|[-_.:])', model or '') and os.environ.get('CONTEXT_TREE_ALLOW_SOL_JUDGE') != '1':
        # user decision 2026-11-03: no sol models in this project; 2026-11-09: sol allowed only as an evaluation judge on request
        raise ValueError(f'model {model!r} is not used in this project (sol models are excluded)')
    if reasoning_effort is None and model == configured_model:
        reasoning_effort = STAGE_EFFORTS.get(stage)
    started = time.perf_counter()
    before = REQUEST_COUNT
    metric = {"stage": stage, "model": model, "effort": reasoning_effort,
              "input_chars": len(system) + len(user)}
    try:
        with _watchdog_scope():
            response = _chat_stream(
                system, user, model, timeout, read_timeout, no_content_timeout,
                idle_content_timeout, reasoning_effort=reasoning_effort,
                max_output_tokens=max_output_tokens, response_schema=response_schema)
        metric.update(usage=response.get("usage") or None,
                      finish_reason=response["choices"][0]["finish_reason"],
                      output_chars=len(response["choices"][0]["message"]["content"]),
                      ok=True)
        return response
    except Exception as exc:
        metric.update(ok=False, error=type(exc).__name__)
        raise
    finally:
        metric.update(seconds=round(time.perf_counter() - started, 3),
                      requests=REQUEST_COUNT - before)
        CALL_METRICS.append(metric)


def _chat_stream(system: str, user: str, model: str, timeout: int,
                 read_timeout: int, no_content_timeout: int,
                 idle_content_timeout: int, *, reasoning_effort: str | None,
                 max_output_tokens: int | None, response_schema: dict | None) -> dict:
    """Chat completions (streaming SSE) with SIGALRM-based fail-fast.

    Triggers (whichever fires first) interrupt iter_lines via SIGALRM:
      - no_content_timeout (45s): no content delta within N s of starting → raise
      - idle_content_timeout (20s): N s since last content delta → raise
      - read_timeout (socket-level 30s): no bytes for N s → ReadTimeout
      - timeout (180s wall-clock cap, enforced per-chunk if alarm reset)

    On timeout/error: 3 attempts then raise. Caller (preprocessor / atomizer)
    handles split-and-retry by halving the failing batch.

    Models requiring /responses endpoint (gpt-5.5+) are routed to
    _chat_responses(), which returns the same shape.
    """
    if _uses_responses_api(model):
        return _chat_responses(system, user, model, timeout=timeout,
                               read_timeout=read_timeout,
                               no_content_timeout=no_content_timeout,
                               idle_content_timeout=idle_content_timeout,
                               reasoning_effort=reasoning_effort,
                               max_output_tokens=max_output_tokens,
                               response_schema=response_schema)

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "stream": True,
    }
    _apply_options(payload, model, reasoning_effort, max_output_tokens,
                   response_schema, responses=False)

    for attempt in range(3):
        token = get_token()
        try:
            _count_request()
            resp = _SESSION.post(
                get_api_base() + "/chat/completions",
                json=payload, headers=_headers(token),
                timeout=(10, read_timeout), stream=True,
            )
            if resp.status_code == 401:
                resp.close()
                print(f"    🔑 401 token expired, refreshing (attempt {attempt+1})")
                get_token(force_refresh=True)
                continue
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", "5"))
                resp.close()
                print(f"    ⏳ 429 rate limited, waiting {retry}s (attempt {attempt+1})")
                time.sleep(retry)
                continue
            if not resp.ok:
                body_text = resp.text[:200]
                resp.close()
                raise RuntimeError(f"HTTP {resp.status_code}: {body_text}")

            resp.encoding = "utf-8"

            content_parts: list[str] = []
            finish_reason = None
            usage = None
            saw_content = False
            t_start = time.monotonic()

            # Arm SIGALRM: fires after no_content_timeout if iter_lines hasn't
            # yielded a content chunk; reset to idle_content_timeout after each.
            _set_alarm(no_content_timeout)
            done = False
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if done: continue                    # drain the stream's tail: a fully read response returns its connection to the pool
                    if time.monotonic() - t_start >= timeout:
                        raise RuntimeError(f"Stream deadline exceeded ({timeout}s)")
                    if not line: continue
                    if not line.startswith("data:"): continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        if not _DRAIN: break
                        done = True; continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError: continue
                    if "error" in chunk:
                        raise RuntimeError(f"API error: {chunk['error'].get('message', chunk['error'])}")
                    ch = (chunk.get("choices") or [{}])[0]
                    delta = ch.get("delta") or {}
                    if (c := delta.get("content")) is not None:
                        content_parts.append(c)
                        saw_content = True
                        # Reset alarm to idle threshold; capped by remaining wall-clock
                        remaining = max(1, int(timeout - (time.monotonic() - t_start)))
                        _set_alarm(min(idle_content_timeout, remaining))
                    if (fr := ch.get("finish_reason")) is not None:
                        finish_reason = fr
                    if "usage" in chunk:
                        usage = chunk["usage"]
            except _StreamTimeout:
                resp.close()
                if done: pass                            # the answer was complete; only the tail was not read
                elif not saw_content:
                    raise RuntimeError(f"stream watchdog: no content for {no_content_timeout}s")
                else:
                    raise RuntimeError(f"stream watchdog: idle {idle_content_timeout}s after content")
            except requests.exceptions.RequestException:
                if not done: raise                       # an error while draining after [DONE] loses only the connection
            finally:
                _set_alarm(0)
                resp.close()

            if finish_reason != "stop":
                raise RuntimeError(f"Incomplete chat response: finish_reason={finish_reason}")
            return {
                "choices": [{"message": {"content": "".join(content_parts)},
                              "finish_reason": finish_reason}],
                "usage": usage or {},
            }
        except requests.exceptions.ReadTimeout as e:
            if attempt == 2:
                raise RuntimeError(f"Stream read timeout (no socket bytes for {read_timeout}s) after retries")
            print(f"    ⏱  stream read timeout {read_timeout}s (attempt {attempt+1})")
            time.sleep(1)
        except requests.RequestException as e:
            if attempt == 2:
                raise RuntimeError(f"Network error after retries: {e}")
            time.sleep(2)

    raise RuntimeError("Failed after max retries")


def chat_content(system: str, user: str, model: str | None = None,
                 timeout: int = 180, **options) -> str:
    """Chat and return just the content string.

    Robust to malformed responses (missing choices / null message / null content)
    — raises RuntimeError with context instead of NoneType subscript errors.
    """
    resp = chat(system, user, model, timeout=timeout, **options)
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError(f"chat response missing choices: {str(resp)[:200]}")
    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content")
    if content is None:
        finish = (choices[0] or {}).get("finish_reason", "?")
        raise RuntimeError(f"chat response had null content (finish={finish})")
    return content


# ─── Responses API support (for gpt-5.5+) ──────────────────────────────────
# Newer OpenAI models (gpt-5.5, future tiers) only expose `/responses` on
# Copilot — /chat/completions returns "unsupported_api_for_model". We query
# /models metadata once, cache the supported endpoints per model, and prefer
# /chat/completions when both are available. Same return shape so callers
# don't care which API ran.

_model_cache: dict[str, dict] = {}


def list_models(refresh: bool = False) -> list[dict]:
    token = get_token()
    if refresh or not _model_cache:
        response = _SESSION.get(_cached_api_base + "/models",
                                headers=_headers(token), timeout=15)
        try:
            response.raise_for_status()
            models = response.json().get("data", [])
            if not models:
                raise RuntimeError("Copilot returned an empty model catalog")
            _model_cache.clear()
            _model_cache.update({m["id"]: m for m in models if m.get("id")})
        finally:
            response.close()
    return list(_model_cache.values())


def _model_endpoints(model: str) -> set[str]:
    list_models()
    return set(_model_cache.get(model, {}).get("supported_endpoints") or [])


def _apply_options(payload: dict, model: str, effort: str | None,
                   output_limit: int | None, schema: dict | None, *, responses: bool):
    list_models()
    capabilities = _model_cache.get(model, {}).get("capabilities", {})
    supports = capabilities.get("supports", {})
    if effort:
        if effort not in supports.get("reasoning_effort", []):
            raise ValueError(f"{model} does not advertise reasoning effort {effort}")
        if responses:
            payload["reasoning"] = {"effort": effort}
        else:
            payload["reasoning_effort"] = effort
            if not model.startswith("gemini-"):
                payload.pop("temperature", None)
    if output_limit is not None:
        if output_limit <= 0:
            raise ValueError("max_output_tokens must be positive")
        payload["max_output_tokens" if responses else "max_tokens"] = output_limit
    if schema is not None:
        if not supports.get("structured_outputs"):
            raise ValueError(f"{model} does not advertise structured outputs")
        if responses:
            payload["text"] = {"format": {"type": "json_schema", "name": "result",
                                            "schema": schema, "strict": True}}
        else:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            }


def _uses_responses_api(model: str) -> bool:
    """True iff model only supports /responses (no /chat/completions)."""
    eps = _model_endpoints(model)
    if not eps:
        return False  # unknown → assume chat (default path)
    return "/chat/completions" not in eps and "/responses" in eps


def _chat_responses(system: str, user: str, model: str, timeout: int = 180,
                    read_timeout: int = 30,
                    no_content_timeout: int = 60,
                    idle_content_timeout: int = 30, *,
                    reasoning_effort: str | None = None,
                    max_output_tokens: int | None = None,
                    response_schema: dict | None = None) -> dict:
    """Streaming /responses call — returns same shape as chat()."""
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user",   "content": [{"type": "input_text", "text": user}]},
        ],
        "stream": True,
    }
    _apply_options(payload, model, reasoning_effort, max_output_tokens,
                   response_schema, responses=True)

    for attempt in range(3):
        token = get_token()
        try:
            _count_request()
            resp = _SESSION.post(
                get_api_base() + "/responses",
                json=payload, headers=_headers(token),
                timeout=(10, read_timeout), stream=True,
            )
            if resp.status_code == 401:
                resp.close()
                print(f"    🔑 401 token expired, refreshing (attempt {attempt+1})")
                get_token(force_refresh=True)
                continue
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", "5"))
                resp.close()
                print(f"    ⏳ 429 rate limited, waiting {retry}s (attempt {attempt+1})")
                time.sleep(retry)
                continue
            if not resp.ok:
                body_text = resp.text[:300]
                resp.close()
                raise RuntimeError(f"HTTP {resp.status_code}: {body_text}")

            resp.encoding = "utf-8"

            content_parts: list[str] = []
            usage = None
            completed = False
            saw_content = False
            t_start = time.monotonic()

            _set_alarm(no_content_timeout)
            done = False
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if done: continue                    # drain the stream's tail: a fully read response returns its connection to the pool
                    if time.monotonic() - t_start >= timeout:
                        raise RuntimeError(f"Stream deadline exceeded ({timeout}s)")
                    if not line: continue
                    if not line.startswith("data:"): continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        if not _DRAIN: break
                        done = True; continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError: continue
                    etype = chunk.get("type", "")
                    if etype == "response.output_text.delta":
                        d = chunk.get("delta", "")
                        if d:
                            content_parts.append(d)
                            saw_content = True
                            remaining = max(1, int(timeout - (time.monotonic() - t_start)))
                            _set_alarm(min(idle_content_timeout, remaining))
                    elif etype in ("response.failed", "response.incomplete"):
                        state = chunk.get("response") or {}
                        reason = state.get("incomplete_details") or state.get("error") or etype
                        raise RuntimeError(f"Incomplete Responses output: {reason}")
                    elif etype == "response.completed":
                        state = chunk.get("response") or {}
                        completed = state.get("status", "completed") == "completed"
                        u = state.get("usage")
                        if u:
                            usage = {
                                "prompt_tokens": u.get("input_tokens", 0),
                                "completion_tokens": u.get("output_tokens", 0),
                                "total_tokens": u.get("total_tokens", 0),
                            }
                    elif etype == "error":
                        err = chunk.get("error") or chunk
                        raise RuntimeError(f"responses API error: {err.get('message', err)}")
            except _StreamTimeout:
                resp.close()
                if done: pass                            # the answer was complete; only the tail was not read
                elif not saw_content:
                    raise RuntimeError(f"stream watchdog: no content for {no_content_timeout}s")
                else:
                    raise RuntimeError(f"stream watchdog: idle {idle_content_timeout}s after content")
            except requests.exceptions.RequestException:
                if not done: raise                       # an error while draining after [DONE] loses only the connection
            finally:
                _set_alarm(0)
                resp.close()

            if not completed:
                raise RuntimeError("Responses stream ended before response.completed")
            return {
                "choices": [{"message": {"content": "".join(content_parts)},
                              "finish_reason": "stop"}],
                "usage": usage or {},
            }
        except requests.exceptions.ReadTimeout:
            if attempt == 2:
                raise RuntimeError(f"Stream read timeout (no socket bytes for {read_timeout}s) after retries")
            print(f"    ⏱  stream read timeout {read_timeout}s (attempt {attempt+1})")
            time.sleep(1)
        except requests.RequestException as e:
            if attempt == 2:
                raise RuntimeError(f"Network error after retries: {e}")
            time.sleep(2)

    raise RuntimeError("Failed after max retries")


def chat_cheap(system: str, user: str, timeout: int = 90, *,
               stage: str | None = None) -> str:
    return chat_content(system, user, model=None if stage else MODEL_CHEAP,
                        timeout=timeout, stage=stage)


def chat_usage(system: str, user: str, model: str | None = None) -> tuple[str, int, int]:
    """Chat and return (content, prompt_tokens, completion_tokens)."""
    resp = chat(system, user, model)
    content = resp["choices"][0]["message"]["content"]
    usage = resp.get("usage", {})
    return content, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


EMBEDDING_BATCH_MAX = 64  # Copilot embedding endpoint rejects 710-input request
                          # with "too many inputs" — chunk to be safe.

def embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings, chunked to EMBEDDING_BATCH_MAX per request."""
    if not texts:
        return []

    out: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_MAX):
        chunk = texts[i:i + EMBEDDING_BATCH_MAX]
        out.extend(_embeddings_one(chunk))
    return out


def _embeddings_one(texts: list[str]) -> list[list[float]]:
    """Single embedding API call (no chunking). Returns list of vectors."""
    if not texts:
        return []
    payload = {"model": "text-embedding-3-small", "input": texts}

    for attempt in range(3):
        token = get_token()
        hdrs = _headers(token)
        del hdrs["Openai-Intent"]
        try:
            _count_request()
            resp = _SESSION.post(
                get_api_base() + "/embeddings",
                json=payload, headers=hdrs, timeout=30,
            )
            if resp.status_code == 401:
                print(f"    🔑 Embedding 401 token expired, refreshing")
                get_token(force_refresh=True)
                continue
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", "5"))
                print(f"    ⏳ Embedding 429, waiting {retry}s")
                time.sleep(retry)
                continue
            if not resp.ok:
                raise RuntimeError(f"Embedding HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"Embedding error: {data['error'].get('message', data['error'])}")
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            if len(items) != len(texts):
                raise RuntimeError("Embedding response omitted inputs")
            return [item["embedding"] for item in items]
        except requests.RequestException as e:
            if attempt == 2:
                raise RuntimeError(f"Embedding network error after retries: {e}")
            time.sleep(2)

    raise RuntimeError("Embedding rate limited after max retries")
