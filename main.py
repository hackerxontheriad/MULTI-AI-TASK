"""MADEX Single-Model AI Hub.

Official providers are called through their APIs when server-side keys are set.
Community GPT4Free (g4f) adapters are experimental. Each request uses one route.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import functools
from concurrent.futures import ThreadPoolExecutor
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from provider_catalog import (
    STATIC_MODELS, ProviderCredentialsMissing, call_official_chat, get_runtime_provider_catalog,
)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
# g4f normally writes media to ./generated_images or ./generated_media.
IMAGE_DIR = APP_DIR / "generated_images"
MEDIA_DIR = APP_DIR / "generated_media"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("CHROME_BIN", os.getenv("CHROME_BIN", "/usr/bin/chromium"))
os.environ.setdefault("CHROMIUM_PATH", os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("madex-single-model-ai")

APP_NAME = "MadEx Single-Model AI Hub"
VERSION = "15.0.0"
CATALOG_TTL = max(60, int(os.getenv("CATALOG_TTL_SECONDS", "900")))
REQUEST_TIMEOUT = max(15, int(os.getenv("G4F_REQUEST_TIMEOUT", "60")))
G4F_MAX_WORKERS = min(8, max(1, int(os.getenv("G4F_MAX_WORKERS", "4"))))
G4F_EXECUTOR = ThreadPoolExecutor(max_workers=G4F_MAX_WORKERS, thread_name_prefix="g4f-worker")
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
# to use the g4f adapters directly, without an OpenRouter key or router account.
BLOCKED_PROVIDER_TERMS = ("openrouter", "kilocode")
ALLOWED_TYPES = {"text", "image", "video", "audio"}

app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description="Single-route multi-provider gateway: official APIs, local Ollama, and experimental g4f adapters.",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# g4f's ImageResponse URLs are commonly /media/<filename>.
app.mount("/media", StaticFiles(directory=str(IMAGE_DIR)), name="media-images")
app.mount("/media-files", StaticFiles(directory=str(MEDIA_DIR)), name="media-files")


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


_cache: dict[str, Any] = {"at": 0.0, "rows": [], "source": None, "error": None}
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
            response = requests.get(url, timeout=5, headers={"User-Agent": "MadEx-Free-AI/14.1"})
            response.raise_for_status()
            rows = parse_working_results(response.text)
            if rows:
                return rows, url, None
            errors.append(f"{url}: catalog had no parseable entries")
        except Exception as exc:  # upstream is optional; fall back gracefully
            errors.append(f"{url}: {type(exc).__name__}")
    return [], None, "; ".join(errors)[:500] if errors else "catalog unavailable"


async def get_catalog(refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if not refresh and _cache["rows"] and now - float(_cache["at"]) < CATALOG_TTL:
        return dict(_cache)
    async with _cache_lock:
        now = time.time()
        if not refresh and _cache["rows"] and now - float(_cache["at"]) < CATALOG_TTL:
            return dict(_cache)
        rows, source, error = await asyncio.to_thread(_fetch_catalog_sync)
        # The static official catalog makes all major providers visible even when
        # the community list is offline. Each official route states whether its key
        # is configured; choosing it never silently switches to another provider.
        visible_rows = list(rows)
        visible_rows.extend(await asyncio.to_thread(get_runtime_provider_catalog))
        if not any(row["id"] == "auto|auto" for row in visible_rows):
            visible_rows.insert(0, {
                "id": "auto|auto", "provider": "Auto · one g4f route", "model": "auto",
                "type": "text", "verified_by": "g4f Auto route (not live-verified)",
                "route_kind": "g4f_auto", "auth_required": None,
                "availability": "one g4f Auto call; upstream provider behavior can vary",
            })
        # Keep unique route IDs if a community list starts echoing one of our presets.
        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in visible_rows:
            row_id = row.get("id")
            if row_id and row_id not in seen_ids:
                seen_ids.add(row_id)
                deduped.append(row)
        result = {"at": now, "rows": deduped, "source": source, "error": error}
        _cache.update(result)
        return dict(_cache)


def _resolve_provider(provider_name: Optional[str]) -> Any:
    """Return a provider class only if the installed g4f package actually exports it."""
    if not provider_name or provider_name.lower() == "auto":
        return None
    try:
        import g4f  # lazy so the API health page still runs if g4f isn't installed
        provider_module = getattr(g4f, "Provider", None)
        if provider_module is None:
            return None
        variants = [provider_name]
        variants.extend([
            provider_name.replace("-", "_"),
            provider_name.replace("_", ""),
            re.sub(r"[^A-Za-z0-9]", "", provider_name),
        ])
        for candidate in variants:
            value = getattr(provider_module, candidate, None)
            if value is not None:
                return value
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


def _client_chat_once(model: str, messages: list[dict[str, Any]], provider_name: Optional[str], temperature: float, max_tokens: int) -> str:
    from g4f.client import Client

    client = Client()
    kwargs: dict[str, Any] = {
        "model": model or "auto",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "web_search": False,
    }
    clean_provider = provider_name.split(":", 1)[-1] if provider_name and provider_name.startswith("g4f:") else provider_name
    provider = _resolve_provider(clean_provider)
    if clean_provider and clean_provider.lower() != "auto":
        if provider is None:
            raise RuntimeError(f"Selected g4f adapter '{clean_provider}' is not installed/exported in this environment")
        kwargs["provider"] = provider
    # Keep compatibility with provider/client versions that don't accept every
    # optional argument. Don't silently swap to a paid API: g4f remains gateway.
    try:
        response = client.chat.completions.create(**kwargs)
    except TypeError as exc:
        message = str(exc).lower()
        if "web_search" in message:
            kwargs.pop("web_search", None)
            response = client.chat.completions.create(**kwargs)
        elif "max_tokens" in message or "temperature" in message:
            kwargs.pop("max_tokens", None)
            kwargs.pop("temperature", None)
            response = client.chat.completions.create(**kwargs)
        else:
            raise
    text = _extract_chat_text(response)
    if not text:
        raise RuntimeError("provider returned an empty response")
    return text


def _model_candidates(requested: str, rows: list[dict[str, str]]) -> list[tuple[str, Optional[str]]]:
    """Resolve exactly one requested provider/model. Never switch to another model."""
    requested = (requested or "auto").strip()
    if _is_router("", requested):
        raise HTTPException(status_code=400, detail={
            "error": "requested_model_blocked",
            "requested_model": requested,
            "message": "OpenRouter/KiloCode model aliases are disabled in this build.",
        })
    if requested.lower() in {"auto", "default"}:
        # g4f's own Auto route is a single upstream call; this gateway does not
        # iterate through a list of providers/models.
        return [("auto", None)]
    if "|" in requested:
        provider_name, model_name = requested.split("|", 1)
        provider_name, model_name = provider_name.strip(), model_name.strip()
        if not provider_name or not model_name:
            raise HTTPException(status_code=400, detail={
                "error": "invalid_model_selection",
                "requested_model": requested,
                "message": "Use the exact provider|model ID from /v1/models.",
            })
        if _is_router(provider_name, model_name):
            raise HTTPException(status_code=400, detail={
                "error": "requested_model_blocked",
                "requested_model": requested,
                "message": "OpenRouter/KiloCode model aliases are disabled in this build.",
            })
        return [(model_name, provider_name)]
    # A bare model name is passed through as-is to g4f, with no provider/model
    # discovery and no fallback to a different model.
    return [(requested, None)]


async def _run_g4f_thread(fn, *args, timeout: int):
    """Run a potentially blocking g4f provider in a small shared worker pool."""
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(G4F_EXECUTOR, functools.partial(fn, *args))
    return await asyncio.wait_for(future, timeout=timeout)


async def _generate_chat(requested_model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int) -> tuple[str, str, Optional[str], list[str]]:
    candidates = _model_candidates(requested_model, [])
    model, provider = candidates[0]  # exactly one model/provider attempt per request
    label = f"{provider}|{model}" if provider else model
    try:
        if provider in STATIC_MODELS:
            text = await _run_g4f_thread(
                call_official_chat, provider, model, messages, temperature, max_tokens,
                REQUEST_TIMEOUT, timeout=REQUEST_TIMEOUT,
            )
        else:
            text = await _run_g4f_thread(
                _client_chat_once, model, messages, provider, temperature, max_tokens, timeout=REQUEST_TIMEOUT
            )
        return text, model, provider, []
    except asyncio.TimeoutError:
        reason = f"timed out after {REQUEST_TIMEOUT}s"
    except ProviderCredentialsMissing as exc:
        raise HTTPException(status_code=424, detail={
            "error": "provider_credentials_missing", "requested_model": label,
            "message": str(exc), "fallback_used": False,
        }) from exc
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:300]}"
        log.info("requested provider/model failed: %s (%s)", label, reason)
    raise HTTPException(
        status_code=502,
        detail={
            "error": "requested_model_failed",
            "requested_model": label,
            "message": f"Requested model/provider '{label}' failed. No other model was tried.",
            "reason": reason,
            "fallback_used": False,
        },
    )


def _extract_image_data(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if not data:
        raise RuntimeError("image provider returned no media data")
    first = data[0]
    if isinstance(first, dict):
        url = first.get("url")
        b64 = first.get("b64_json")
        revised = first.get("revised_prompt")
    else:
        url = getattr(first, "url", None)
        b64 = getattr(first, "b64_json", None)
        revised = getattr(first, "revised_prompt", None)
    if url:
        return {"url": str(url), "revised_prompt": revised}
    if b64:
        return {"b64_json": str(b64), "revised_prompt": revised}
    # Some providers return a data URI in `url`-like content fields.
    content = getattr(first, "content", None)
    if isinstance(content, str) and content.startswith("data:image/"):
        return {"url": content, "revised_prompt": revised}
    raise RuntimeError("image provider returned data without a usable URL or base64 image")


def _client_image_once(model: str, prompt: str, size: Optional[str], response_format: str) -> dict[str, Any]:
    from g4f.client import Client

    client = Client()
    kwargs: dict[str, Any] = {"model": model, "prompt": prompt, "response_format": response_format}
    if size:
        kwargs["size"] = size
    try:
        response = client.images.generate(**kwargs)
    except TypeError as exc:
        message = str(exc).lower()
        kwargs.pop("size", None)
        if "response_format" in message:
            kwargs.pop("response_format", None)
        response = client.images.generate(**kwargs)
    return _extract_image_data(response)


async def _generate_image(req: ImageRequest) -> dict[str, Any]:
    """Attempt one selected image model only; no provider/model fallback chain."""
    requested = (req.model or "auto").strip()
    if _is_router("", requested):
        raise HTTPException(status_code=400, detail={"error": "requested_model_blocked", "requested_model": requested})
    # Auto means one g4f Auto call, not iterating through a list of image models.
    model = "auto" if requested.lower() in {"auto", "default"} else requested
    try:
        image = await _run_g4f_thread(
            _client_image_once, model, req.prompt, req.size, req.response_format, timeout=REQUEST_TIMEOUT
        )
        return {"image": image, "model": model, "attempts": 0}
    except asyncio.TimeoutError:
        reason = f"timed out after {REQUEST_TIMEOUT}s"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:250]}"
        log.info("requested image model failed: %s (%s)", model, reason)
    raise HTTPException(
        status_code=502,
        detail={
            "error": "requested_image_model_failed",
            "requested_model": model,
            "message": f"Requested image model '{model}' failed. No other model was tried.",
            "reason": reason,
            "fallback_used": False,
            "fake_media": False,
        },
    )

async def require_access_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Optional app-level token. This is not a model-provider API key."""
    expected = os.getenv("API_ACCESS_TOKEN", "").strip()
    if not expected:
        return
    actual = (authorization or "").strip()
    if actual.lower().startswith("bearer "):
        actual = actual[7:].strip()
    if not actual or actual != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid app access token")


def _health_info() -> dict[str, Any]:
    try:
        import g4f  # noqa: F401
        g4f_ok = True
        g4f_version = getattr(g4f, "__version__", "installed")
    except Exception:
        g4f_ok = False
        g4f_version = None
    chrome_candidates = [os.getenv("CHROME_BIN", ""), os.getenv("CHROMIUM_PATH", ""), "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]
    chrome_path = next((path for path in chrome_candidates if path and Path(path).exists()), None)
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": VERSION,
        "g4f_installed": g4f_ok,
        "g4f_version": g4f_version,
        "chromium_found": bool(chrome_path),
        "chromium_path": chrome_path,
        "community_routes_can_be_keyless": True,
        "official_api_keys_supported": True,
        "official_provider_count": len(STATIC_MODELS),
        "configured_official_providers": [name for name in STATIC_MODELS if name != "Ollama Local" and any(os.getenv(key, "").strip() for key in STATIC_MODELS[name].get("key_env", ()))],
        "note": "Health OK does not prove model availability. Official API routes need their provider keys; community routes are experimental.",
    }


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return _health_info()


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
        "cache_ttl_seconds": CATALOG_TTL,
        "counts": counts,
        "rows": rows,
        "catalog_warning": data["error"],
        "policy": "Single-route mode: official API presets call only their own provider; community presets are experimental; no model fallback is attempted.",
        "route_kinds": {"official_api": "requires configured provider key", "local": "requires local service", "g4f_community": "experimental adapter; may be unavailable or require sessions", "g4f_auto": "one upstream Auto call"},
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
        })
    return {"object": "list", "data": list(unique.values())}


@app.post("/v1/catalog/refresh")
async def refresh_catalog(_: None = Depends(require_access_token)):
    data = await get_catalog(refresh=True)
    return {"ok": bool(data["rows"]), "source": data["source"], "count": len(data["rows"]), "warning": data["error"]}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, _: None = Depends(require_access_token)):
    messages = [{"role": msg.role, "content": msg.content} for msg in req.messages]
    text, used_model, used_provider, errors = await _generate_chat(req.model, messages, req.temperature, req.max_tokens)
    model_label = f"{used_provider}|{used_model}" if used_provider else used_model
    response_body = {
        "id": "chatcmpl-" + uuid.uuid4().hex[:20],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_label,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "madex": {"provider": used_provider, "model": used_model, "fallbacks_before_success": [], "fallback_used": False},
    }
    if req.stream:
        # The provider response is collected first; this emits OpenAI-compatible
        # SSE chunks but does not pretend that the upstream generation was token-streamed.
        async def chunks():
            start = {"id": response_body["id"], "object": "chat.completion.chunk", "created": response_body["created"], "model": model_label,
                     "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            yield f"data: {json.dumps(start, ensure_ascii=False)}\n\n"
            delta = {"id": response_body["id"], "object": "chat.completion.chunk", "created": response_body["created"], "model": model_label,
                     "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
            end = {"id": response_body["id"], "object": "chat.completion.chunk", "created": response_body["created"], "model": model_label,
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            yield f"data: {json.dumps(end, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")
    return JSONResponse(response_body)


@app.post("/v1/images/generations")
@app.post("/v1/image/generate")
async def image_generate(req: ImageRequest, _: None = Depends(require_access_token)):
    result = await _generate_image(req)
    image = result["image"]
    item: dict[str, Any] = {}
    if image.get("url"):
        item["url"] = image["url"]
        if image["url"].startswith("/media/"):
            item["url"] = image["url"]
    if image.get("b64_json"):
        item["b64_json"] = image["b64_json"]
    if image.get("revised_prompt"):
        item["revised_prompt"] = image["revised_prompt"]
    return {
        "created": int(time.time()), "data": [item],
        "model": result["model"], "provider_mode": "g4f-no-key-attempt",
        "note": "This is a real provider result; no sample image is substituted.",
    }


@app.post("/v1/video/generate")
async def video_generate(req: VideoRequest, _: None = Depends(require_access_token)):
    data = await get_catalog()
    rows = [row for row in data["rows"] if row["type"] == "video" and row.get("verified_by") == "g4f-working"]
    # g4f may not provide a stable videos.generate endpoint. If there is one,
    # use exactly the explicitly selected row or one Auto-selected row; never loop.
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
            "message": "No working no-auth video provider with a supported g4f video API is listed right now.",
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
        loop = asyncio.get_running_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(G4F_EXECUTOR, functools.partial(generate, **kwargs)), timeout=REQUEST_TIMEOUT * 3
        )
        output = _extract_media_url(response)
        if output:
            return {"status": "success", "id": uuid.uuid4().hex, "model": selected["model"],
                    "provider": selected["provider"], "video_url": output, "fallback_used": False}
        reason = "provider returned no usable video URL"
    except asyncio.TimeoutError:
        reason = f"timed out after {REQUEST_TIMEOUT * 3}s"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:200]}"
    raise HTTPException(status_code=502, detail={
        "error": "requested_video_model_failed",
        "message": f"Requested video route '{selected['provider']}|{selected['model']}' failed. No other model was tried.",
        "reason": reason, "fallback_used": False, "fake_media": False,
    })

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


@app.get("/v1/status")
async def status():
    data = await get_catalog()
    reported_rows = [row for row in data["rows"] if row.get("verified_by") == "g4f-working"]
    counts = {kind: sum(1 for row in reported_rows if row["type"] == kind) for kind in ALLOWED_TYPES}
    health_data = _health_info()
    return {
        "status": "ok",
        "service": APP_NAME,
        "health": health_data,
        "catalog_source": data["source"],
        "catalog_counts": counts,
        "feature_status": {
            "text": "official API routes, local Ollama, and experimental community routes; selection is single-route",
            "image": "experimental; actual provider must respond",
            "video": "unavailable until the live catalog and installed g4f expose a no-auth video provider",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")), reload=False)
