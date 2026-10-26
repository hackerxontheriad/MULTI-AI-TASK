"""MADEX Single-Model AI Hub.

Official/free-tier providers are called through their own HTTP APIs when server-side
keys are set. Community GPT4Free (g4f) adapters are experimental and optional.
Every request uses exactly one provider/model route; nothing falls back silently.
"""
from __future__ import annotations

import asyncio
import functools
import hmac
import importlib.metadata
import importlib.util
import json
import logging
import os
import platform
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import agents
import http_client
import runtime_env
from http_client import explain_exception, redact
from provider_catalog import (
    IMAGE_PROVIDERS, STATIC_MODELS, ProviderCredentialsMissing, ProviderHTTPError,
    call_official_chat, call_official_image, get_runtime_provider_catalog, key_is_configured,
    normalize_messages,
)

APP_DIR = Path(__file__).resolve().parent
# Must run before any os.getenv() below so keys in .env are really used.
_DOTENV_LOADED = runtime_env.load_dotenv(APP_DIR / ".env")
STATIC_DIR = APP_DIR / "static"
IMAGE_DIR = APP_DIR / "generated_images"
MEDIA_DIR = APP_DIR / "generated_media"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
# g4f writes media here unless told otherwise (Docker sets the same value).
os.environ.setdefault("G4F_MEDIA_DIR", str(IMAGE_DIR))

# CA bundle + a *real* Chromium path (never a path that does not exist).
CA_INFO = http_client.configure_ca_bundle()
BROWSER_INFO = runtime_env.configure_runtime()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("madex-single-model-ai")


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        log.warning("%s is not an integer; using %s", name, default)
        value = default
    return min(high, max(low, value))


APP_NAME = "MadEx Multi-Provider AI Hub"
VERSION = "15.3.0"
CATALOG_TTL = _int_env("CATALOG_TTL_SECONDS", 900, 60, 86400)
REQUEST_TIMEOUT = _int_env("G4F_REQUEST_TIMEOUT", 60, 15, 300)
G4F_MAX_WORKERS = _int_env("G4F_MAX_WORKERS", 4, 1, 8)
RATE_LIMIT_PER_MIN = _int_env("RATE_LIMIT_PER_MIN", 30, 0, 100000)
G4F_EXECUTOR = ThreadPoolExecutor(max_workers=G4F_MAX_WORKERS, thread_name_prefix="g4f-worker")
OFFICIAL_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="official-api")
CATALOG_URLS = [
    item.strip()
    for item in os.getenv(
        "G4F_WORKING_RESULTS_URLS",
        "https://raw.githubusercontent.com/Free-AI-Things/g4f-working/main/working/working_results.txt,"
        "https://raw.githubusercontent.com/maruf009sultan/g4f-working/refs/heads/main/working/working_results.txt",
    ).split(",")
    if item.strip().startswith("https://")
]
# Do not use external routers listed as model aliases; this project is intended
# to use direct provider routes, without a router account.
BLOCKED_PROVIDER_TERMS = ("openrouter", "kilocode")  # community-scraped aliases only; official OpenRouter Free route is explicit
ALLOWED_TYPES = {"text", "image", "video", "audio"}

if not os.getenv("API_ACCESS_TOKEN", "").strip():
    log.warning("API_ACCESS_TOKEN is empty: anyone who can reach this server can spend your provider quotas. "
                "Set it before exposing the service publicly.")

app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description="Single-route multi-provider gateway: free-tier APIs, official APIs, local Ollama and experimental g4f adapters.",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# g4f's ImageResponse URLs are commonly /media/<filename>.
app.mount("/media", StaticFiles(directory=str(IMAGE_DIR)), name="media-images")
app.mount("/media-files", StaticFiles(directory=str(MEDIA_DIR)), name="media-files")


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class Message(BaseModel):
    role: str = Field(min_length=1, max_length=30)
    content: Any

    @field_validator("role")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"system", "user", "assistant", "developer", "tool"}:
            raise ValueError("role must be system, developer, user, assistant, or tool")
        return value


class ChatRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, max_length=120)
    model: str = Field(default="auto", max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=60)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    stream: bool = False
    # Explicit ordered failover list. Empty by default to avoid changing providers silently.
    fallback_models: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("fallback_models")
    @classmethod
    def safe_fallback_models(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if len(cleaned) != len(value):
            raise ValueError("fallback_models cannot contain empty entries")
        if any(len(item) > 200 or any(ch in item for ch in "\r\n\x00") for item in cleaned):
            raise ValueError("invalid fallback model identifier")
        if len({item.lower() for item in cleaned}) != len(cleaned):
            raise ValueError("fallback_models must be unique")
        if any("|" not in item for item in cleaned):
            raise ValueError("each fallback must be an explicit provider|model route")
        return cleaned

    @field_validator("model")
    @classmethod
    def safe_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return "auto"
        if len(value) > 200 or any(ch in value for ch in "\r\n\x00"):
            raise ValueError("invalid model identifier")
        return value


class ImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="auto", max_length=200)
    n: int = Field(default=1, ge=1, le=2)
    size: Optional[str] = Field(default="1024x1024", max_length=30)
    response_format: str = Field(default="url", pattern="^(url|b64_json)$")


class VideoRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    model: str = Field(default="auto", max_length=200)
    aspect_ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1|4:3|3:4)$")
    image_url: Optional[str] = Field(default=None, max_length=2000)


class AgentRequest(BaseModel):
    mode: str = Field(pattern="^(compare|council|plan)$")
    prompt: str = Field(min_length=1, max_length=6000)
    # compare: models to compare | council: member models | plan: worker models
    routes: list[str] = Field(min_length=1, max_length=agents.MAX_ROUTES)
    judge: Optional[str] = Field(default=None, max_length=200)      # council judge / plan synthesiser
    planner: Optional[str] = Field(default=None, max_length=200)    # plan only
    rounds: int = Field(default=1, ge=1, le=2)                      # council: 2 = members critique each other
    max_subtasks: int = Field(default=4, ge=1, le=agents.MAX_SUBTASKS)
    temperature: float = Field(default=0.5, ge=0, le=2)
    max_tokens: int = Field(default=700, ge=64, le=1500)


# --------------------------------------------------------------------------- #
# Access control + rate limit
# --------------------------------------------------------------------------- #
async def require_access_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Optional app-level token. This is not a model-provider API key."""
    expected = os.getenv("API_ACCESS_TOKEN", "").strip()
    if not expected:
        return
    actual = (authorization or "").strip()
    if actual.lower().startswith("bearer "):
        actual = actual[7:].strip()
    if not actual or not hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Missing or invalid app access token")


_rate_lock = threading.Lock()
_rate_hits: dict[str, deque] = {}


def _client_key(request: Request) -> str:
    if os.getenv("TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


async def rate_limit(request: Request) -> None:
    """Small in-memory per-client limiter that protects free-tier quotas (0 = off)."""
    if RATE_LIMIT_PER_MIN <= 0:
        return
    key = _client_key(request)
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits.setdefault(key, deque())
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= RATE_LIMIT_PER_MIN:
            retry = max(1, int(60 - (now - hits[0])))
            raise HTTPException(status_code=429, detail={
                "error": "gateway_rate_limited",
                "message": f"More than {RATE_LIMIT_PER_MIN} requests/minute from this client. Retry in {retry}s.",
                "fallback_used": False,
            }, headers={"Retry-After": str(retry)})
        hits.append(now)
        if len(_rate_hits) > 2000:  # bound memory
            for stale in [k for k, v in _rate_hits.items() if not v or now - v[-1] > 60][:1000]:
                _rate_hits.pop(stale, None)


# --------------------------------------------------------------------------- #
# Community catalog
# --------------------------------------------------------------------------- #
_cache: dict[str, Any] = {"at": 0.0, "rows": [], "source": None, "error": None, "ttl": CATALOG_TTL}
_cache_lock = asyncio.Lock()


def _is_router(provider: str, model: str) -> bool:
    value = f"{provider} {model}".lower()
    return any(term in value for term in BLOCKED_PROVIDER_TERMS)


def parse_working_results(raw: str) -> list[dict[str, str]]:
    """Parse the upstream provider|model|type format, safely ignoring bad rows."""
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        provider, model, kind = parts[0], parts[1], parts[2].lower()
        if not provider or not model or kind not in ALLOWED_TYPES:
            continue
        if len(provider) > 100 or len(model) > 200 or _is_router(provider, model):
            continue
        # Reject control characters before model/provider names can reach g4f.
        if any(ord(c) < 32 for c in provider + model):
            continue
        key = (provider, model, kind)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "id": f"g4f:{provider}|{model}",
            "provider": provider,
            "route_provider": f"g4f:{provider}",
            "model": model,
            "type": kind,
            "verified_by": "g4f-working",
            "route_kind": "g4f_community",
            "auth_required": None,
            "availability": "community-reported; not guaranteed to work on every request",
        })
    return rows


def _fetch_catalog_sync() -> tuple[list[dict[str, str]], Optional[str], Optional[str]]:
    errors: list[str] = []
    for url in CATALOG_URLS:
        try:
            response = http_client.get(url, timeout=8, retries=1, deadline=time.monotonic() + 20)
            response.raise_for_status()
            rows = parse_working_results(response.text)
            if rows:
                return rows, url, None
            errors.append(f"{url}: catalog had no parseable entries")
        except Exception as exc:  # upstream is optional; degrade gracefully
            hint = explain_exception(exc)
            errors.append(f"{url}: {type(exc).__name__}" + (f" ({hint})" if hint else ""))
    return [], None, redact("; ".join(errors), 700) if errors else "catalog unavailable"


async def get_catalog(refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if not refresh and _cache["rows"] and now - float(_cache["at"]) < float(_cache.get("ttl", CATALOG_TTL)):
        return dict(_cache)
    async with _cache_lock:
        now = time.time()
        if not refresh and _cache["rows"] and now - float(_cache["at"]) < float(_cache.get("ttl", CATALOG_TTL)):
            return dict(_cache)
        rows, source, error = await asyncio.to_thread(_fetch_catalog_sync)
        # The static official catalog keeps every free/official route visible even when
        # the community list is offline. Choosing a row never switches providers.
        visible_rows = list(rows)
        try:
            visible_rows.extend(await asyncio.to_thread(get_runtime_provider_catalog))
        except Exception as exc:  # never let one provider break the whole catalog
            log.warning("provider catalog build failed: %s", redact(exc))
            error = ((error + "; ") if error else "") + "provider catalog partially unavailable"
        if not any(row["id"] == "auto|auto" for row in visible_rows):
            visible_rows.insert(0, {
                "id": "auto|auto", "provider": "Auto · one g4f route", "model": "auto",
                "type": "text", "verified_by": "g4f Auto route (not live-verified)",
                "route_kind": "g4f_auto", "auth_required": None,
                "availability": "one g4f Auto call; upstream provider behavior can vary",
            })
        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in visible_rows:
            row_id = row.get("id")
            if row_id and row_id not in seen_ids:
                seen_ids.add(row_id)
                deduped.append(row)
        # A failed community fetch is retried after 60s instead of being cached for 15 minutes.
        ttl = CATALOG_TTL if rows else min(CATALOG_TTL, 60)
        result = {"at": now, "rows": deduped, "source": source, "error": error, "ttl": ttl}
        _cache.update(result)
        return dict(_cache)


# --------------------------------------------------------------------------- #
# g4f (community) execution
# --------------------------------------------------------------------------- #
class G4FBusy(RuntimeError):
    """All g4f worker threads are occupied (a timed-out call keeps its thread until it ends)."""


_g4f_lock = threading.Lock()
_g4f_active = 0


def _resolve_provider(provider_name: Optional[str]) -> Any:
    """Return a provider class only if the installed g4f package actually exports it."""
    if not provider_name or provider_name.lower() == "auto":
        return None
    try:
        import g4f  # lazy so the API still runs if g4f isn't installed

        provider_module = getattr(g4f, "Provider", None)
        if provider_module is None:
            return None
        variants = [
            provider_name, provider_name.replace("-", "_"), provider_name.replace("_", ""),
            re.sub(r"[^A-Za-z0-9]", "", provider_name),
        ]
        for candidate in variants:
            value = getattr(provider_module, candidate, None)
            if value is not None:
                return value
        wanted = re.sub(r"[^a-z0-9]", "", provider_name.lower())
        for attr in dir(provider_module):
            if re.sub(r"[^a-z0-9]", "", attr.lower()) == wanted and not attr.startswith("_"):
                return getattr(provider_module, attr)
    except Exception:
        return None
    return None


def _extract_chat_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response.strip()
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if content is not None:
                return str(content).strip()
        if isinstance(first, dict):
            content = first.get("message", {}).get("content")
            if content is not None:
                return str(content).strip()
    return str(response).strip()


def _client_chat_once(model: str, messages: list[dict[str, Any]], provider_name: Optional[str],
                      temperature: float, max_tokens: int) -> str:
    runtime_env.configure_runtime()  # make sure CHROME_BIN points at a real binary
    from g4f.client import Client

    client = Client()
    kwargs: dict[str, Any] = {
        "model": model or "auto",
        "messages": normalize_messages(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "web_search": False,
    }
    clean_provider = provider_name.split(":", 1)[-1].strip() if provider_name and provider_name.lower().startswith("g4f:") else (provider_name.strip() if provider_name else provider_name)
    provider = _resolve_provider(clean_provider)
    if clean_provider and clean_provider.lower() != "auto":
        if provider is None:
            raise RuntimeError(f"Selected g4f adapter '{clean_provider}' is not installed/exported in this environment")
        kwargs["provider"] = provider
    # Different g4f versions accept different optional kwargs. Drop only the one the
    # error names, then retry the *same* provider/model (never a different one).
    response = None
    for _ in range(4):
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except TypeError as exc:
            message = str(exc).lower()
            dropped = False
            for optional in ("web_search", "max_tokens", "temperature"):
                if optional in message and optional in kwargs:
                    kwargs.pop(optional)
                    dropped = True
                    break
            if not dropped:
                raise
    text = _extract_chat_text(response)
    if not text:
        raise RuntimeError("provider returned an empty response")
    return text


def _model_candidates(requested: str, rows: list[dict[str, str]]) -> list[tuple[str, Optional[str]]]:
    """Resolve exactly one explicit provider/model; never guesses a route."""
    requested = (requested or "auto").strip()
    if requested.lower() in {"auto", "default", "auto|auto"}:
        return [("auto", None)]
    if "|" in requested:
        provider_name, model_name = requested.split("|", 1)
        provider_name, model_name = provider_name.strip(), model_name.strip()
        if provider_name.lower().startswith("g4f:"):
            provider_name = "g4f:" + provider_name.split(":", 1)[1].strip()
        if not provider_name or not model_name:
            raise HTTPException(status_code=400, detail={
                "error": "invalid_model_selection", "requested_model": requested,
                "message": "Use the exact provider|model ID from /v1/models.",
            })
        # OpenRouter is allowed only as this named direct API adapter; scraped community aliases and KiloCode remain blocked.
        is_official_openrouter = provider_name == "OpenRouter Free API"
        blocked = "kilocode" in f"{provider_name} {model_name}".lower()
        if not is_official_openrouter:
            blocked = blocked or _is_router(provider_name, model_name)
        if blocked:
            raise HTTPException(status_code=400, detail={
                "error": "requested_model_blocked", "requested_model": requested,
                "message": "Unofficial router/community aliases are disabled; use a configured explicit provider route.",
            })
        return [(model_name, provider_name)]
    # Bare OpenRouter/KiloCode aliases are not trusted; use OpenRouter Free API|model from the catalog.
    if _is_router("", requested):
        raise HTTPException(status_code=400, detail={
            "error": "requested_model_blocked", "requested_model": requested,
            "message": "Use an explicit provider|model ID from /v1/models.",
        })
    return [(requested, None)]


async def _run_g4f_thread(fn, *args, timeout: int):
    """Run a blocking g4f call in the small g4f pool.

    A timed-out thread cannot be killed in Python, so it keeps a slot until it ends.
    We count slots and answer "busy" immediately instead of queueing behind hung calls.
    """
    global _g4f_active
    with _g4f_lock:
        if _g4f_active >= G4F_MAX_WORKERS:
            raise G4FBusy(
                f"All {G4F_MAX_WORKERS} community-adapter workers are busy or stuck on earlier requests. "
                "Retry shortly, or use an official free-tier API route (no browser needed)."
            )
        _g4f_active += 1

    def runner():
        global _g4f_active
        try:
            return fn(*args)
        finally:
            with _g4f_lock:
                _g4f_active -= 1

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(G4F_EXECUTOR, runner)
    return await asyncio.wait_for(future, timeout=timeout)


async def _run_official_thread(fn, *args, timeout: int):
    """Run a blocking official-API call. The adapter enforces its own deadline (< timeout)."""
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(OFFICIAL_EXECUTOR, functools.partial(fn, *args))
    return await asyncio.wait_for(future, timeout=timeout)


def _failure(status: int, error: str, label: str, reason: str, hint: Optional[str] = None,
             headers: Optional[dict[str, str]] = None, **extra: Any) -> HTTPException:
    detail: dict[str, Any] = {
        "error": error,
        "requested_model": label,
        "message": f"Requested model/provider '{label}' failed. No other model was tried.",
        "reason": reason,
        "fallback_used": False,
    }
    if hint:
        detail["hint"] = hint
    detail.update(extra)
    return HTTPException(status_code=status, detail=detail, headers=headers)


async def _generate_chat(requested_model: str, messages: list[dict[str, Any]], temperature: float,
                         max_tokens: int) -> tuple[str, str, Optional[str], list[str]]:
    candidates = _model_candidates(requested_model, [])
    model, provider = candidates[0]  # exactly one model/provider attempt per request
    label = f"{provider}|{model}" if provider else model
    hint: Optional[str] = None
    try:
        if provider in STATIC_MODELS:
            text = await _run_official_thread(
                call_official_chat, provider, model, messages, temperature, max_tokens, REQUEST_TIMEOUT,
                timeout=REQUEST_TIMEOUT + 5,
            )
        else:
            text = await _run_g4f_thread(
                _client_chat_once, model, messages, provider, temperature, max_tokens, timeout=REQUEST_TIMEOUT
            )
        return text, model, provider, []
    except asyncio.TimeoutError:
        reason = f"timed out after {REQUEST_TIMEOUT}s"
        hint = "Provider too slow. Try a smaller/faster model or an official free-tier API route."
        status, error, headers = 504, "requested_model_failed", None
    except ProviderCredentialsMissing as exc:
        raise HTTPException(status_code=424, detail={
            "error": "provider_credentials_missing", "requested_model": label,
            "message": redact(exc), "fallback_used": False,
        }) from exc
    except G4FBusy as exc:
        raise _failure(503, "g4f_workers_busy", label, redact(exc), "Use an official/free-tier API route.",
                       {"Retry-After": "10"}) from exc
    except ProviderHTTPError as exc:
        reason = redact(exc, 500)
        headers = None
        if exc.status == 429:
            status, error = 429, "provider_rate_limited"
            if exc.retry_after:
                headers = {"Retry-After": str(max(1, int(exc.retry_after)))}
            hint = "Free tiers are rate limited. Wait and retry; no other provider was tried."
        elif exc.status in (401, 403):
            status, error = 424, "provider_auth_failed"
            hint = "The provider rejected the server-side key/token (wrong, expired, or missing permission)."
        else:
            status, error = 502, "requested_model_failed"
        log.info("provider error for %s: %s", label, reason)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {redact(exc, 300)}"
        hint = explain_exception(exc)
        status, error, headers = 502, "requested_model_failed", None
        log.info("requested provider/model failed: %s (%s)", label, reason)
    raise _failure(status, error, label, reason, hint, headers)


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
def _extract_image_data(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if not data:
        raise RuntimeError("image provider returned no media data")
    first = data[0]
    if isinstance(first, dict):
        url, b64, revised = first.get("url"), first.get("b64_json"), first.get("revised_prompt")
    else:
        url = getattr(first, "url", None)
        b64 = getattr(first, "b64_json", None)
        revised = getattr(first, "revised_prompt", None)
    if url:
        return {"url": str(url), "revised_prompt": revised}
    if b64:
        return {"b64_json": str(b64), "revised_prompt": revised}
    content = getattr(first, "content", None)
    if isinstance(content, str) and content.startswith("data:image/"):
        return {"url": content, "revised_prompt": revised}
    raise RuntimeError("image provider returned data without a usable URL or base64 image")


def _client_image_once(model: str, prompt: str, size: Optional[str], response_format: str,
                       provider_name: Optional[str] = None) -> dict[str, Any]:
    runtime_env.configure_runtime()
    from g4f.client import Client

    client = Client()
    kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "response_format": response_format}
    if size:
        kwargs["size"] = size
    if provider_name:
        provider_key = provider_name.split(":", 1)[-1].strip() if provider_name.lower().startswith("g4f:") else provider_name.strip()
        provider = _resolve_provider(provider_key)
        if provider is None:
            raise RuntimeError(f"Selected g4f adapter '{provider_name}' is not installed/exported in this environment")
        kwargs["provider"] = provider
    response = None
    for _ in range(4):
        try:
            response = client.images.generate(**kwargs)
            break
        except TypeError as exc:
            message = str(exc).lower()
            for optional in ("size", "response_format"):
                if optional in message and optional in kwargs:
                    kwargs.pop(optional)
                    break
            else:
                raise
    return _extract_image_data(response)


def _prune_media(directory: Path, keep: int = 200) -> None:
    try:
        files = sorted((p for p in directory.iterdir() if p.is_file() and p.name != ".gitkeep"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def _save_official_image(provider: str, model: str, prompt: str, size: Optional[str],
                         response_format: str) -> dict[str, Any]:
    data, ext = call_official_image(provider, model, prompt, size, REQUEST_TIMEOUT)
    if response_format == "b64_json":
        import base64
        return {"b64_json": base64.b64encode(data).decode("ascii")}
    name = f"img-{uuid.uuid4().hex[:16]}.{ext}"
    (IMAGE_DIR / name).write_bytes(data)
    _prune_media(IMAGE_DIR)
    return {"url": f"/media/{name}"}


async def _generate_image(req: ImageRequest) -> dict[str, Any]:
    """Attempt one selected image model only; no provider/model fallback chain."""
    requested = (req.model or "auto").strip()
    if _is_router("", requested):
        raise HTTPException(status_code=400, detail={"error": "requested_model_blocked", "requested_model": requested})
    provider: Optional[str] = None
    model = "auto" if requested.lower() in {"auto", "default"} else requested
    if "|" in requested:
        provider, model = (part.strip() for part in requested.split("|", 1))
        if provider.lower().startswith("g4f:"):
            provider = "g4f:" + provider.split(":", 1)[1].strip()
    label = f"{provider}|{model}" if provider else model
    hint: Optional[str] = None
    try:
        if provider in IMAGE_PROVIDERS:
            image = await _run_official_thread(
                _save_official_image, provider, model, req.prompt, req.size, req.response_format,
                timeout=REQUEST_TIMEOUT + 10,
            )
            mode = "official-api"
        else:
            image = await _run_g4f_thread(
                _client_image_once, model, req.prompt, req.size, req.response_format, provider, timeout=REQUEST_TIMEOUT
            )
            mode = "g4f-community"
        return {"image": image, "model": label, "attempts": 0, "provider_mode": mode}
    except asyncio.TimeoutError:
        reason, status, error = f"timed out after {REQUEST_TIMEOUT}s", 504, "requested_image_model_failed"
        headers: Optional[dict[str, str]] = None
    except ProviderCredentialsMissing as exc:
        raise HTTPException(status_code=424, detail={
            "error": "provider_credentials_missing", "requested_model": label,
            "message": redact(exc), "fallback_used": False, "fake_media": False,
        }) from exc
    except G4FBusy as exc:
        raise _failure(503, "g4f_workers_busy", label, redact(exc), "Use an official image route.",
                       {"Retry-After": "10"}, fake_media=False) from exc
    except ProviderHTTPError as exc:
        reason = redact(exc, 400)
        headers = {"Retry-After": str(max(1, int(exc.retry_after)))} if exc.retry_after else None
        status = 429 if exc.status == 429 else 424 if exc.status in (401, 403) else 502
        error = "provider_rate_limited" if status == 429 else "provider_auth_failed" if status == 424 else "requested_image_model_failed"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {redact(exc, 250)}"
        hint = explain_exception(exc)
        status, error, headers = 502, "requested_image_model_failed", None
        log.info("requested image model failed: %s (%s)", label, reason)
    failure = _failure(status, error, label, reason, hint, headers, fake_media=False)
    failure.detail["message"] = f"Requested image model '{label}' failed. No other model was tried."
    raise failure


# --------------------------------------------------------------------------- #
# Health / diagnostics
# --------------------------------------------------------------------------- #
def _g4f_info() -> tuple[bool, Optional[str]]:
    # Do not import g4f here: it is heavy and /health is polled by the host.
    if importlib.util.find_spec("g4f") is None:
        return False, None
    try:
        return True, importlib.metadata.version("g4f")
    except Exception:
        return True, "installed"


def _configured_free_routes() -> list[str]:
    return [name for name, cfg in STATIC_MODELS.items()
            if cfg.get("free_tier") and name != "Ollama Local" and key_is_configured(name)]


def _health_info() -> dict[str, Any]:
    g4f_ok, g4f_version = _g4f_info()
    chrome_path = runtime_env.find_chrome()
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": VERSION,
        "g4f_installed": g4f_ok,
        "g4f_version": g4f_version,
        "chromium_found": bool(chrome_path),
        "chromium_path": chrome_path,
        "ca_bundle": http_client.ca_info().get("source"),
        "community_routes_can_be_keyless": True,
        "official_api_keys_supported": True,
        "official_provider_count": len(STATIC_MODELS),
        "configured_official_providers": [name for name in STATIC_MODELS if name != "Ollama Local" and key_is_configured(name)],
        "configured_free_providers": _configured_free_routes(),
        "access_token_set": bool(os.getenv("API_ACCESS_TOKEN", "").strip()),
        "note": "Health OK does not prove model availability. Official/free API routes need their provider keys; community routes are experimental.",
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return _health_info()


@app.get("/v1/diagnostics")
async def diagnostics(probe: bool = True, refresh: bool = False, _: None = Depends(require_access_token)):
    """Deep checks: CA bundle, real Chromium launch, g4f worker slots, configured keys (names only)."""
    browser = await asyncio.to_thread(runtime_env.probe_browser, refresh) if probe else {"skipped": True}
    with _g4f_lock:
        active = _g4f_active
    return {
        "service": APP_NAME, "version": VERSION, "python": platform.python_version(),
        "platform": platform.platform(), "root": runtime_env.running_as_root(),
        "tls": http_client.ca_info(),
        "browser": browser,
        "g4f": {"installed": _g4f_info()[0], "version": _g4f_info()[1], "workers": G4F_MAX_WORKERS, "busy": active},
        "configured_providers": [n for n in STATIC_MODELS if n != "Ollama Local" and key_is_configured(n)],
        "configured_free_providers": _configured_free_routes(),
        "image_routes": list(IMAGE_PROVIDERS),
        "rate_limit_per_minute": RATE_LIMIT_PER_MIN,
        "advice": [
            "Browser-based community adapters need a working Chromium and enough RAM (~1 GB); free 512 MB hosts usually cannot run them.",
            "For zero-cost, reliable operation prefer the official free-tier routes (Groq, Cerebras, Mistral, Gemini, GitHub Models, Hugging Face, Cloudflare, Pollinations) or local Ollama.",
        ],
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    raise HTTPException(status_code=404, detail="No favicon")


@app.get("/v1/catalog")
async def catalog(refresh: bool = False):
    data = await get_catalog(refresh=refresh)
    rows = data["rows"]
    reported_rows = [row for row in rows if row.get("verified_by") == "g4f-working"]
    counts: dict[str, int] = {kind: sum(1 for row in reported_rows if row["type"] == kind) for kind in sorted(ALLOWED_TYPES)}
    return {
        "object": "catalog",
        "source": data["source"],
        "fetched_at": int(data["at"]),
        "cache_ttl_seconds": int(data.get("ttl", CATALOG_TTL)),
        "counts": counts,
        "free_route_count": sum(1 for row in rows if row.get("free_tier")),
        "rows": rows,
        "catalog_warning": data["error"],
        "policy": "Single-route mode: each preset calls only its own provider; community presets are experimental; no model fallback is attempted.",
        "route_kinds": {"official_api": "requires configured provider key (free tiers available)", "local": "requires local service",
                        "g4f_community": "experimental adapter; may be unavailable or require sessions", "g4f_auto": "one upstream Auto call"},
    }


@app.get("/v1/models")
async def models():
    data = await get_catalog()
    unique: dict[str, dict[str, Any]] = {"auto": {"id": "auto", "object": "model", "owned_by": "g4f-single-route", "type": "text"}}
    for row in data["rows"]:
        unique.setdefault(row["id"], {
            "id": row["id"], "object": "model", "owned_by": row["provider"], "type": row["type"],
            "route_kind": row.get("route_kind"), "auth_required": row.get("auth_required"),
            "auth_configured": row.get("auth_configured"), "availability": row.get("availability"),
            "free_tier": row.get("free_tier"),
        })
    return {"object": "list", "data": list(unique.values())}


@app.post("/v1/catalog/refresh")
async def refresh_catalog(_: None = Depends(require_access_token)):
    data = await get_catalog(refresh=True)
    return {"ok": bool(data["rows"]), "source": data["source"], "count": len(data["rows"]), "warning": data["error"]}


@app.post("/v1/chat/completions", dependencies=[Depends(rate_limit)])
async def chat_completions(req: ChatRequest, _: None = Depends(require_access_token)):
    messages = [{"role": msg.role, "content": msg.content} for msg in req.messages]
    # Validate the requested route and all fallback routes before spending provider quota.
    _model_candidates(req.model, [])
    for route in req.fallback_models:
        if route.lower() == (req.model or "auto").lower():
            raise HTTPException(status_code=400, detail={"error": "duplicate_fallback_route", "message": "fallback_models cannot repeat the primary route."})
        _model_candidates(route, [])
    failed_routes: list[dict[str, Any]] = []
    try:
        text, used_model, used_provider, _ = await _generate_chat(req.model, messages, req.temperature, req.max_tokens)
    except HTTPException as first_error:
        retryable = first_error.status_code in {424, 429, 502, 503, 504}
        if not req.fallback_models or not retryable:
            raise
        # Explicit user-configured fallback routes only. Each failure is redacted and bounded.
        first_detail = first_error.detail if isinstance(first_error.detail, dict) else {"message": str(first_error.detail)}
        failed_routes.append({
            "route": req.model,
            "status": first_error.status_code,
            "error": str(first_detail.get("error", "provider_failed"))[:80],
            "message": redact(first_detail.get("reason") or first_detail.get("message") or "provider failed", 240),
        })
        last_error = first_error
        for route in req.fallback_models:
            try:
                text, used_model, used_provider, _ = await _generate_chat(route, messages, req.temperature, req.max_tokens)
                break
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                failed_routes.append({
                    "route": route,
                    "status": exc.status_code,
                    "error": str(detail.get("error", "provider_failed"))[:80],
                    "message": redact(detail.get("reason") or detail.get("message") or "provider failed", 240),
                })
                last_error = exc
        else:
            detail = first_error.detail if isinstance(first_error.detail, dict) else {"message": str(first_error.detail)}
            detail = dict(detail)
            detail.update({
                "message": "The primary route and all explicitly configured fallback routes failed.",
                "fallback_used": False,
                "fallback_attempts": failed_routes,
            })
            raise HTTPException(status_code=last_error.status_code, detail=detail, headers=last_error.headers) from last_error
    model_label = f"{used_provider}|{used_model}" if used_provider else used_model
    failed_labels = [item["route"] for item in failed_routes]
    fallback_labels = [route for route in failed_labels if route != req.model]
    response_body = {
        "id": "chatcmpl-" + uuid.uuid4().hex[:20],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_label,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "madex": {
            "provider": used_provider, "model": used_model,
            "fallbacks_before_success": fallback_labels,
            "failed_routes_before_success": failed_labels,
            "fallback_used": bool(failed_routes),
        },
    }
    if req.stream:
        # Buffered SSE: the selected upstream response is collected before emitting chunks.
        async def chunks():
            base = {"id": response_body["id"], "object": "chat.completion.chunk", "created": response_body["created"], "model": model_label}
            for delta, finish in (({"role": "assistant"}, None), ({"content": text}, None), ({}, "stop")):
                payload = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")
    return JSONResponse(response_body)


def _describe_agent_error(exc: BaseException) -> dict[str, Any]:
    """Turn any per-agent failure into a small, secret-free record."""
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        text = detail.get("reason") or detail.get("message") or "request failed"
        return {"status": exc.status_code, "error": detail.get("error", "error"),
                "message": redact(text, 400), "hint": detail.get("hint")}
    return {"status": 500, "error": "agent_internal_error",
            "message": redact(f"{type(exc).__name__}: {exc}", 300), "hint": explain_exception(exc)}


@app.post("/v1/agents/run", dependencies=[Depends(rate_limit)])
async def agents_run(req: AgentRequest, _: None = Depends(require_access_token)):
    """Multi-agent modes. Every agent uses the route the caller named; none is ever re-routed."""
    all_routes = [*req.routes, *[x for x in (req.judge, req.planner) if x]]
    for route in all_routes:
        _model_candidates(route, [])  # rejects blocked router aliases / malformed IDs with HTTP 400

    async def chat(route, messages, temperature, max_tokens):
        return await _generate_chat(route, messages, temperature, max_tokens)

    try:
        result = await agents.run_agents(
            mode=req.mode, prompt=req.prompt, routes=[r.strip() for r in req.routes],
            judge=req.judge.strip() if req.judge else None, planner=req.planner.strip() if req.planner else None,
            rounds=req.rounds, max_subtasks=req.max_subtasks, temperature=req.temperature,
            max_tokens=req.max_tokens, chat=chat, describe_error=_describe_agent_error,
        )
    except agents.AgentPlanError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_agent_request", "message": str(exc),
                                                     "fallback_used": False}) from exc
    return result


@app.post("/v1/images/generations", dependencies=[Depends(rate_limit)])
@app.post("/v1/image/generate", dependencies=[Depends(rate_limit)])
async def image_generate(req: ImageRequest, _: None = Depends(require_access_token)):
    result = await _generate_image(req)
    image = result["image"]
    item: dict[str, Any] = {}
    if image.get("url"):
        item["url"] = image["url"]
    if image.get("b64_json"):
        item["b64_json"] = image["b64_json"]
    if image.get("revised_prompt"):
        item["revised_prompt"] = image["revised_prompt"]
    return {
        "created": int(time.time()), "data": [item],
        "model": result["model"], "provider_mode": result.get("provider_mode", "g4f-community"),
        "note": "This is a real provider result; no sample image is substituted.",
    }


def _extract_media_url(response: Any) -> Optional[str]:
    if isinstance(response, str):
        return response if response.startswith(("http://", "https://", "/media/")) else None
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if data:
        first = data[0]
        if isinstance(first, dict):
            return first.get("url") or first.get("video_url")
        return getattr(first, "url", None) or getattr(first, "video_url", None)
    return getattr(response, "url", None) or getattr(response, "video_url", None)


@app.post("/v1/video/generate", dependencies=[Depends(rate_limit)])
async def video_generate(req: VideoRequest, _: None = Depends(require_access_token)):
    data = await get_catalog()
    rows = [row for row in data["rows"] if row["type"] == "video" and row.get("verified_by") == "g4f-working"]
    # g4f may not provide a stable videos.generate endpoint. If there is one, use exactly
    # the explicitly selected row or one Auto-selected row; never loop.
    try:
        from g4f.client import Client

        client = Client()
        videos_api = getattr(client, "videos", None)
        generate = getattr(videos_api, "generate", None) if videos_api is not None else None
    except Exception:
        generate = None
    if not callable(generate) or not rows:
        raise HTTPException(status_code=503, detail={
            "error": "no_verified_keyless_video_provider",
            "message": "No working video provider with a supported g4f video API is listed right now. "
                       "Free official video APIs are not available in this gateway; image routes work without a browser.",
            "catalog_video_entries": len(rows),
            "next_step": "Refresh the catalog later or configure a real authorized/local video provider.",
            "fake_media": False, "fallback_used": False,
        })
    requested = (req.model or "auto").strip()
    if requested.lower() in {"auto", "default"}:
        selected = rows[0]
    else:
        matching = [r for r in rows if requested in {r.get("id"), r.get("model"), f"{r.get('provider')}|{r.get('model')}", f"g4f:{r.get('provider')}|{r.get('model')}"}]
        if not matching:
            raise HTTPException(status_code=400, detail={"error": "requested_video_model_not_listed", "requested_model": requested, "fallback_used": False})
        selected = matching[0]
    try:
        kwargs = {"model": selected["model"], "prompt": req.prompt, "aspect_ratio": req.aspect_ratio}
        if req.image_url:
            kwargs["image_url"] = req.image_url
        response = await _run_g4f_thread(functools.partial(generate, **kwargs), timeout=REQUEST_TIMEOUT * 3)
        output = _extract_media_url(response)
        if output:
            return {"status": "success", "id": uuid.uuid4().hex, "model": selected["model"],
                    "provider": selected["provider"], "video_url": output, "fallback_used": False}
        reason = "provider returned no usable video URL"
    except asyncio.TimeoutError:
        reason = f"timed out after {REQUEST_TIMEOUT * 3}s"
    except G4FBusy as exc:
        reason = redact(exc)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {redact(exc, 200)}"
    raise HTTPException(status_code=502, detail={
        "error": "requested_video_model_failed",
        "message": f"Requested video route '{selected['provider']}|{selected['model']}' failed. No other model was tried.",
        "reason": reason, "fallback_used": False, "fake_media": False,
    })


@app.get("/v1/status")
async def status():
    data = await get_catalog()
    reported_rows = [row for row in data["rows"] if row.get("verified_by") == "g4f-working"]
    counts = {kind: sum(1 for row in reported_rows if row["type"] == kind) for kind in ALLOWED_TYPES}
    return {
        "status": "ok",
        "service": APP_NAME,
        "health": _health_info(),
        "catalog_source": data["source"],
        "catalog_counts": counts,
        "feature_status": {
            "text": "free-tier and official API routes, local Ollama, and experimental community routes; selection is single-route",
            "image": "official free routes (Pollinations, Cloudflare Workers AI) need keys; community image routes are experimental",
            "video": "unavailable until the live catalog and installed g4f expose a video provider",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), reload=False)
