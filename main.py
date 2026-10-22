"""MadEx Multi-AI Gateway.

Chat calls use LiteLLM (real provider APIs; no browser scraping). Video generation
uses Google's official Gemini Interactions REST API. Configure provider API keys
as environment variables; never commit real secrets.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("madex.gateway")

try:
    from litellm import acompletion as litellm_acompletion
except Exception:  # Allows health/tests to run before dependencies are installed.
    litellm_acompletion = None

APP_NAME = "MadEx Multi-AI Gateway"
APP_VERSION = "13.0.0"
VIDEO_DIR = Path(os.getenv("VIDEO_DIR", "generated_videos")).resolve()
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_JOBS = 100
VIDEO_JOB_TTL_SECONDS = 24 * 60 * 60
VIDEO_API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "OpenAI-compatible chat API with configurable multi-provider failover, "
        "plus an asynchronous Gemini Omni video-generation endpoint."
    ),
)
app.mount("/static/videos", StaticFiles(directory=str(VIDEO_DIR)), name="videos")

# Model IDs change over time. Override any default below in .env when needed.
MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "chatgpt": ("MODEL_CHATGPT", "openai/gpt-4o-mini"),
    "openai": ("MODEL_CHATGPT", "openai/gpt-4o-mini"),
    "gemini": ("MODEL_GEMINI", "gemini/gemini-2.5-flash"),
    "deepseek": ("MODEL_DEEPSEEK", "deepseek/deepseek-chat"),
    "meta": ("MODEL_META", "groq/llama-3.3-70b-versatile"),
    "llama": ("MODEL_META", "groq/llama-3.3-70b-versatile"),
    "claude": ("MODEL_CLAUDE", "anthropic/claude-sonnet-4-20250514"),
    "anthropic": ("MODEL_CLAUDE", "anthropic/claude-sonnet-4-20250514"),
    "grok": ("MODEL_GROK", "xai/grok-3-mini"),
    "perplexity": ("MODEL_PERPLEXITY", "perplexity/sonar"),
    "mistral": ("MODEL_MISTRAL", "mistral/mistral-small-latest"),
    "openrouter": ("MODEL_OPENROUTER", "openrouter/auto"),
    "ollama": ("MODEL_OLLAMA", "ollama/llama3.2"),
}

# LiteLLM provider prefixes -> credentials which normally configure them.
PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "perplexity": ("PERPLEXITYAI_API_KEY", "PERPLEXITY_API_KEY"),
    "together_ai": ("TOGETHERAI_API_KEY", "TOGETHER_API_KEY"),
    "fireworks_ai": ("FIREWORKS_API_KEY",),
    "deepinfra": ("DEEPINFRA_API_TOKEN", "DEEPINFRA_API_KEY"),
    "cerebras": ("CEREBRAS_API_KEY",),
    "sambanova": ("SAMBANOVA_API_KEY",),
    "azure": ("AZURE_API_KEY", "AZURE_API_BASE"),
    "bedrock": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
    "vertex_ai": ("VERTEXAI_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"),
    "ollama": ("OLLAMA_BASE_URL",),
}

# Automatic failover order. Only candidates with their own configured credentials
# are used; this does not bypass quotas or billing limits at any provider.
FALLBACK_DEFAULTS: dict[str, tuple[str, str]] = {
    "openrouter": ("MODEL_OPENROUTER_FALLBACK", "openrouter/auto"),
    "gemini": ("MODEL_GEMINI_FALLBACK", "gemini/gemini-2.5-flash"),
    "groq": ("MODEL_GROQ_FALLBACK", "groq/llama-3.3-70b-versatile"),
    "deepseek": ("MODEL_DEEPSEEK_FALLBACK", "deepseek/deepseek-chat"),
    "openai": ("MODEL_OPENAI_FALLBACK", "openai/gpt-4o-mini"),
    "mistral": ("MODEL_MISTRAL_FALLBACK", "mistral/mistral-small-latest"),
    "anthropic": ("MODEL_ANTHROPIC_FALLBACK", "anthropic/claude-sonnet-4-20250514"),
    "xai": ("MODEL_XAI_FALLBACK", "xai/grok-3-mini"),
    "perplexity": ("MODEL_PERPLEXITY_FALLBACK", "perplexity/sonar"),
    "together_ai": ("MODEL_TOGETHER_FALLBACK", "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "fireworks_ai": ("MODEL_FIREWORKS_FALLBACK", "fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct"),
    "deepinfra": ("MODEL_DEEPINFRA_FALLBACK", "deepinfra/meta-llama/Meta-Llama-3.3-70B-Instruct"),
    "cerebras": ("MODEL_CEREBRAS_FALLBACK", "cerebras/llama-3.3-70b"),
    "sambanova": ("MODEL_SAMBANOVA_FALLBACK", "sambanova/Meta-Llama-3.3-70B-Instruct"),
    "ollama": ("MODEL_OLLAMA", "ollama/llama3.2"),
}
FALLBACK_ORDER = [x.strip() for x in os.getenv(
    "FALLBACK_ORDER",
    "openrouter,gemini,groq,deepseek,openai,mistral,anthropic,xai,perplexity,together_ai,fireworks_ai,deepinfra,cerebras,sambanova,ollama",
).split(",") if x.strip()]


class Message(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    user_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=200)
    stream: bool = False
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)

    @field_validator("model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("model must be a single-line model alias or provider/model ID")
        return value


class VideoRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    user_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=3, max_length=10_000)
    model: str = "gemini-omni-1.1-flash"
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    resolution: Literal["360p", "720p", "1080p", "4k"] = "720p"
    image_url: Optional[str] = Field(default=None, max_length=2048)
    image_base64: Optional[str] = Field(default=None, max_length=15_000_000)
    image_mime_type: Literal["image/jpeg", "image/png", "image/webp"] = "image/jpeg"

    @model_validator(mode="after")
    def one_image_source(self) -> "VideoRequest":
        if self.image_url and self.image_base64:
            raise ValueError("Use either image_url or image_base64, not both")
        if self.model.lower() not in {
            "gemini-omni-1.1-flash", "google-flow", "veo-flow", "gemini-omni"
        }:
            raise ValueError(
                "Unsupported video model. Use gemini-omni-1.1-flash (aliases: google-flow, veo-flow)."
            )
        return self


VIDEO_JOBS: dict[str, dict[str, Any]] = {}
VIDEO_TASKS: set[asyncio.Task] = set()


async def require_api_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Optional bearer-token protection. Set API_ACCESS_TOKEN in production."""
    expected = os.getenv("API_ACCESS_TOKEN", "").strip()
    if not expected:
        return
    supplied = authorization or ""
    if not supplied.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer API token")
    provided = supplied[7:].strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid API token")


def has_provider_credentials(provider: str) -> bool:
    keys = PROVIDER_ENV.get(provider)
    if keys is None:
        # Unknown LiteLLM prefixes may be configured by custom/provider-specific env.
        return True
    if provider == "azure":
        return bool(os.getenv("AZURE_API_KEY") and os.getenv("AZURE_API_BASE"))
    if provider == "bedrock":
        return bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))
    return any(os.getenv(key, "").strip() for key in keys)


def resolve_model_name(requested: str) -> tuple[Optional[str], bool]:
    key = requested.strip().lower()
    if key in {"auto", "automatic", "fallback"}:
        return None, False
    if key in MODEL_ALIASES:
        env_name, default = MODEL_ALIASES[key]
        return os.getenv(env_name, default).strip(), True
    if "/" not in requested:
        raise HTTPException(
            status_code=400,
            detail=("Unknown model alias. Use one of: " + ", ".join(sorted(MODEL_ALIASES)) +
                    ", auto, or a LiteLLM provider/model ID such as openrouter/provider/model."),
        )
    return requested.strip(), False


def provider_for_model(model: str) -> str:
    return model.split("/", 1)[0].strip().lower()


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def build_model_candidates(requested: str) -> list[str]:
    primary, was_alias = resolve_model_name(requested)
    candidates: list[str] = []
    if primary:
        provider = provider_for_model(primary)
        # Known providers without credentials are skipped; an unknown prefix is
        # still attempted to support other LiteLLM integrations.
        if provider not in PROVIDER_ENV or has_provider_credentials(provider):
            candidates.append(primary)
    for provider in FALLBACK_ORDER:
        if provider not in FALLBACK_DEFAULTS or not has_provider_credentials(provider):
            continue
        env_name, default = FALLBACK_DEFAULTS[provider]
        candidate = os.getenv(env_name, default).strip()
        if candidate:
            candidates.append(candidate)
    return _unique(candidates)


def configured_provider_names() -> list[str]:
    providers = set(PROVIDER_ENV)
    return sorted(provider for provider in providers if has_provider_credentials(provider))


def litellm_kwargs(model: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if provider_for_model(model) == "ollama":
        kwargs["api_base"] = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
    return kwargs


def _get_choice_content(response: Any) -> tuple[str, Optional[str], Optional[dict[str, Any]]]:
    try:
        choice = response.choices[0]
        message = choice.message
        content = getattr(message, "content", None)
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                else:
                    text_value = getattr(part, "text", None)
                    if text_value:
                        parts.append(str(text_value))
            content = "".join(parts)
        text_content = str(content or "").strip()
        finish_reason = getattr(choice, "finish_reason", None)
        usage_obj = getattr(response, "usage", None)
        if hasattr(usage_obj, "model_dump"):
            usage = usage_obj.model_dump(exclude_none=True)
        elif isinstance(usage_obj, dict):
            usage = usage_obj
        else:
            usage = None
        return text_content, finish_reason, usage
    except Exception as exc:
        raise RuntimeError("Provider returned an unexpected response format") from exc


def _sse(data: dict[str, Any] | str) -> str:
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n"


def _extract_chunk_text(chunk: Any) -> tuple[str, Optional[str]]:
    try:
        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        content = getattr(delta, "content", None)
        if isinstance(content, list):
            content = "".join(
                str(getattr(part, "text", "") or (part.get("text", "") if isinstance(part, dict) else ""))
                for part in content
            )
        return str(content or ""), getattr(choice, "finish_reason", None)
    except Exception:
        return "", None


def _raise_no_provider(candidates: list[str]) -> None:
    if litellm_acompletion is None:
        raise HTTPException(
            status_code=503,
            detail="LiteLLM is not installed. Install dependencies with: pip install -r requirements.txt",
        )
    if not candidates:
        raise HTTPException(
            status_code=503,
            detail=("No configured AI provider credentials were found. Add at least one provider API key "
                    "to .env; use a separate provider key for fallback when another provider hits quota."),
        )


@app.get("/")
def home() -> dict[str, Any]:
    return {
        "status": "online",
        "service": APP_NAME,
        "version": APP_VERSION,
        "chat_aliases": sorted(MODEL_ALIASES),
        "configured_providers": configured_provider_names(),
        "auth_required": bool(os.getenv("API_ACCESS_TOKEN", "").strip()),
        "video_model": os.getenv("GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash"),
        "browser_required": False,
        "endpoints": {
            "chat": "POST /v1/chat/completions",
            "models": "GET /v1/models",
            "video_submit": "POST /v1/video/generate",
            "video_job_status": "GET /v1/video/jobs/{job_id}",
            "health": "GET /health",
            "docs": "/docs",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "chat_engine_installed": litellm_acompletion is not None,
        "configured_providers": configured_provider_names(),
        "video_api_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
    }


@app.get("/v1/models", dependencies=[Depends(require_api_token)])
def list_models() -> dict[str, Any]:
    data = []
    for alias, (env_name, default) in sorted(MODEL_ALIASES.items()):
        resolved = os.getenv(env_name, default).strip()
        provider = provider_for_model(resolved)
        configured = has_provider_credentials(provider) if provider in PROVIDER_ENV else True
        data.append({
            "id": alias,
            "object": "model",
            "owned_by": "madex",
            "provider_model": resolved,
            "configured": configured,
        })
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_token)])
async def chat_completions(req: ChatRequest):
    candidates = build_model_candidates(req.model)
    _raise_no_provider(candidates)
    messages = [{"role": msg.role, "content": msg.content} for msg in req.messages]
    request_id = f"chatcmpl-{uuid.uuid4().hex}"

    if req.stream:
        async def stream_response():
            for model in candidates:
                emitted = False
                try:
                    response = await litellm_acompletion(
                        model=model,
                        messages=messages,
                        temperature=req.temperature,
                        max_tokens=req.max_tokens,
                        stream=True,
                        **litellm_kwargs(model),
                    )
                    async for chunk in response:
                        content, finish_reason = _extract_chunk_text(chunk)
                        if content:
                            emitted = True
                            yield _sse({
                                "id": request_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
                            })
                        if finish_reason:
                            yield _sse({
                                "id": request_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                            })
                    yield _sse("[DONE]")
                    return
                except Exception as exc:
                    logger.warning("Chat candidate failed: provider=%s error=%s", provider_for_model(model), type(exc).__name__)
                    # Fallback is safe only before any content has been sent.
                    if emitted:
                        yield _sse({
                            "error": {"message": "Provider stream failed after partial output; retry the request.", "type": "provider_stream_error"}
                        })
                        yield _sse("[DONE]")
                        return
                    continue
            yield _sse({
                "error": {"message": "All configured providers failed. Check provider quotas, keys, and model IDs.", "type": "provider_error"}
            })
            yield _sse("[DONE]")

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    resolved_requested, _ = resolve_model_name(req.model)
    failures: list[tuple[str, str]] = []
    for model in candidates:
        try:
            response = await litellm_acompletion(
                model=model,
                messages=messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=False,
                **litellm_kwargs(model),
            )
            content, finish_reason, usage = _get_choice_content(response)
            if not content:
                failures.append((provider_for_model(model), "EmptyResponse"))
                continue
            return {
                "id": getattr(response, "id", None) or request_id,
                "object": "chat.completion",
                "created": getattr(response, "created", None) or int(time.time()),
                "model": getattr(response, "model", None) or model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason or "stop",
                }],
                "usage": usage,
                "madex": {
                    "requested_model": req.model,
                    "served_by": model,
                    "fallback_used": bool(resolved_requested and model != resolved_requested),
                },
            }
        except Exception as exc:
            error_type = type(exc).__name__
            failures.append((provider_for_model(model), error_type))
            logger.warning("Chat candidate failed: provider=%s error=%s", provider_for_model(model), error_type)

    providers_tried = _unique([provider for provider, _ in failures])
    error_types = _unique([kind for _, kind in failures])
    raise HTTPException(
        status_code=502,
        detail={
            "message": "All configured AI providers failed. Check API quota/billing, credentials, and model IDs.",
            "providers_tried": providers_tried,
            "error_types": error_types,
            "hint": "Configure a second provider's own API key or use a local Ollama model for independent fallback.",
        },
    )


def _prune_video_jobs() -> None:
    now = time.time()
    expired = [
        job_id for job_id, item in VIDEO_JOBS.items()
        if item.get("created_at_epoch", now) < now - VIDEO_JOB_TTL_SECONDS
    ]
    for job_id in expired:
        VIDEO_JOBS.pop(job_id, None)
    if len(VIDEO_JOBS) > MAX_VIDEO_JOBS:
        finished = sorted(
            ((item.get("created_at_epoch", 0), job_id) for job_id, item in VIDEO_JOBS.items()
             if item.get("status") in {"completed", "failed"})
        )
        while len(VIDEO_JOBS) > MAX_VIDEO_JOBS and finished:
            _, job_id = finished.pop(0)
            VIDEO_JOBS.pop(job_id, None)


async def fetch_public_image(url: str) -> tuple[str, str]:
    """Fetch an HTTPS image while blocking obvious private-network SSRF targets."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="image_url must be a public HTTPS URL")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Private or local image hosts are not allowed")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, host, parsed.port or 443, type=socket.SOCK_STREAM
        )
        ips = {ipaddress.ip_address(item[4][0]) for item in addresses}
        if not ips or any(not ip.is_global for ip in ips):
            raise HTTPException(status_code=400, detail="Private-network image URLs are not allowed")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not resolve image_url host") from exc

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise HTTPException(status_code=400, detail="Could not fetch image_url (HTTP request failed)")
                mime_type = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
                    raise HTTPException(status_code=400, detail="image_url must return JPEG, PNG, or WebP image data")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=413, detail="Image is too large (max 10 MB)")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_IMAGE_BYTES:
                        raise HTTPException(status_code=413, detail="Image is too large (max 10 MB)")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Image fetch failed: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Image download failed") from exc
    return base64.b64encode(bytes(chunks)).decode("ascii"), mime_type


async def get_video_input(req: VideoRequest) -> tuple[str | list[dict[str, str]], bool]:
    if req.image_base64:
        try:
            raw = base64.b64decode(req.image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="image_base64 must be valid base64") from exc
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is too large (max 10 MB)")
        image_b64, mime_type = req.image_base64, req.image_mime_type
    elif req.image_url:
        image_b64, mime_type = await fetch_public_image(req.image_url)
    else:
        return req.prompt, False
    return [
        {"type": "image", "data": image_b64, "mime_type": mime_type},
        {"type": "text", "text": req.prompt},
    ], True


async def generate_video_file(req: VideoRequest) -> tuple[str, str]:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    video_input, is_image_to_video = await get_video_input(req)
    model = os.getenv("GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash").strip()
    body: dict[str, Any] = {
        "model": model,
        "input": video_input,
        "response_format": {
            "type": "video",
            "aspect_ratio": req.aspect_ratio,
            "resolution": req.resolution,
        },
        "generation_config": {
            "video_config": {"task": "image_to_video" if is_image_to_video else "text_to_video"}
        },
    }
    timeout = float(os.getenv("GEMINI_VIDEO_TIMEOUT_SECONDS", "240"))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False, trust_env=True
        ) as client:
            response = await client.post(
                VIDEO_API_URL,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise RuntimeError("Google video API timed out; check the job status and try a shorter prompt") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Could not connect to Google video API") from exc

    if response.status_code == 429:
        raise RuntimeError("Google video API rate limit/quota reached; check AI Studio quota and billing")
    if response.status_code in (401, 403):
        raise RuntimeError("Google video API rejected the key or the project lacks access to this model")
    if not response.is_success:
        raise RuntimeError(f"Google video API returned HTTP {response.status_code}")
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("Google video API returned invalid JSON") from exc

    video_data: Optional[str] = None
    output = result.get("output_video")
    if isinstance(output, dict):
        video_data = output.get("data")
    if not video_data:
        for step in result.get("steps", []):
            for part in step.get("content", []):
                if isinstance(part, dict) and part.get("type") == "video":
                    video_data = part.get("data")
                    if video_data:
                        break
            if video_data:
                break
    if not video_data:
        # Explicitly refuse to fake a file: provider output must contain MP4 bytes.
        raise RuntimeError("Google API returned no inline video bytes; no MP4 was fabricated")
    try:
        video_bytes = base64.b64decode(video_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("Google API video data was not valid base64") from exc
    if len(video_bytes) < 1024 or b"ftyp" not in video_bytes[:64]:
        raise RuntimeError("Google API response did not contain a valid MP4 video")
    file_name = f"{uuid.uuid4().hex}.mp4"
    file_path = VIDEO_DIR / file_name
    file_path.write_bytes(video_bytes)
    return file_name, "image-to-video" if is_image_to_video else "text-to-video"


async def run_video_job(job_id: str, req_data: dict[str, Any]) -> None:
    item = VIDEO_JOBS.get(job_id)
    if item is None:
        return
    item["status"] = "running"
    item["started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        req = VideoRequest.model_validate(req_data)
        file_name, mode = await generate_video_file(req)
        public_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not public_base:
            public_base = str(item.get("base_url", "")).rstrip("/")
        item.update({
            "status": "completed",
            "generation_mode": mode,
            "video_model": os.getenv("GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash"),
            "player_ready_url": f"{public_base}/static/videos/{file_name}",
            "file_name": file_name,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "message": "Video generated by the configured Google Gemini video API.",
        })
    except HTTPException as exc:
        item.update({
            "status": "failed",
            "error": exc.detail if isinstance(exc.detail, str) else "Video input validation failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("Video job failed: %s", type(exc).__name__)
        item.update({
            "status": "failed",
            "error": str(exc) if isinstance(exc, RuntimeError) else "Video generation failed due to a provider/network error",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })


@app.post("/v1/video/generate", status_code=202, dependencies=[Depends(require_api_token)])
async def generate_video(request: Request, req: VideoRequest) -> dict[str, Any]:
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        raise HTTPException(
            status_code=503,
            detail="Real video generation needs GEMINI_API_KEY or GOOGLE_API_KEY. No sample/dummy MP4 is returned.",
        )
    _prune_video_jobs()
    if len(VIDEO_JOBS) >= MAX_VIDEO_JOBS:
        raise HTTPException(status_code=429, detail="Too many recent video jobs; try again after old jobs expire")
    job_id = uuid.uuid4().hex
    VIDEO_JOBS[job_id] = {
        "job_id": job_id,
        "user_id": req.user_id,
        "status": "queued",
        "prompt": req.prompt,
        "model": os.getenv("GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_at_epoch": time.time(),
        "base_url": str(request.base_url).rstrip("/"),
        "player_ready_url": None,
    }
    task = asyncio.create_task(run_video_job(job_id, req.model_dump()))
    VIDEO_TASKS.add(task)
    task.add_done_callback(VIDEO_TASKS.discard)
    return {
        "status": "queued",
        "job_id": job_id,
        "status_url": f"/v1/video/jobs/{job_id}",
        "message": "Video job queued. Poll status_url; generation is asynchronous.",
    }


@app.get("/v1/video/jobs/{job_id}", dependencies=[Depends(require_api_token)])
def get_video_job(job_id: str) -> dict[str, Any]:
    _prune_video_jobs()
    item = VIDEO_JOBS.get(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Video job not found or expired")
    # Don't expose the server-local path or internal epoch timestamp.
    return {key: value for key, value in item.items() if key not in {"file_name", "created_at_epoch", "base_url"}}
