"""Explicit provider/model catalog and single-route API adapters.

Every provider here is called through its own documented HTTP API. Community
(g4f) entries are best-effort and live in main.py. This module never falls back
between providers/models; it only retries the *same* URL on transient errors.

Free / zero-cost routes (set the key on the server; no card needed at the time of
writing - always re-check the provider's current terms):

* Groq, Cerebras, Mistral (Experiment plan), Google Gemini (free tier),
  GitHub Models, Hugging Face Inference Providers (monthly free credits),
  Cloudflare Workers AI (daily free allowance), Pollinations (free key),
  and Ollama (open-source models running on your own machine).

Free tiers can use your prompts for product improvement and can be restricted in
some regions; do not send private data through them.
"""
from __future__ import annotations

import base64
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from urllib.parse import quote

import requests

import http_client
from http_client import redact


class ProviderCredentialsMissing(RuntimeError):
    """Selected provider needs a key/setting that is not configured."""


class ProviderHTTPError(RuntimeError):
    """Provider answered with an HTTP error. ``status`` carries the code."""

    def __init__(self, message: str, status: int = 502, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


# --------------------------------------------------------------------------- #
# Static catalog
# --------------------------------------------------------------------------- #
# Model IDs are a curated starting catalog. When a key is configured the provider's
# own model-list endpoint replaces the presets, so stale IDs here are never fatal.
STATIC_MODELS: dict[str, dict[str, Any]] = {
    # ---------------------------- free / zero-cost ---------------------------- #
    "Groq API": {
        "key_env": ("GROQ_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "token_param": "max_completion_tokens",
        "free_tier": True,
        "free_note": "Free tier, no card; per-model rate limits (about 30 RPM).",
        "signup": "https://console.groq.com/keys",
        "live_deny": ("whisper", "tts", "guard", "orpheus", "playai", "distil-whisper"),
        "docs": "https://console.groq.com/docs/models",
    },
    "Cerebras API": {
        "key_env": ("CEREBRAS_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://api.cerebras.ai/v1",
        "models": ["gpt-oss-120b", "llama-3.3-70b", "qwen-3-32b"],
        "token_param": "max_completion_tokens",
        "temperature_max": 1.5,
        "preset_ids_unverified": True,
        "free_tier": True,
        "free_note": "Free tier, no card; small context caps on free keys.",
        "signup": "https://cloud.cerebras.ai/",
        "docs": "https://inference-docs.cerebras.ai/models/overview",
    },
    "Mistral API": {
        "key_env": ("MISTRAL_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "open-mistral-nemo", "codestral-latest"],
        "temperature_max": 1.5,
        "free_tier": True,
        "free_note": "Free 'Experiment' plan (phone verification); prompts may be used for training on it.",
        "signup": "https://console.mistral.ai/api-keys",
        "live_deny": ("embed", "moderation", "ocr", "voxtral", "transcribe"),
        "docs": "https://docs.mistral.ai/getting-started/models/",
    },
    "GitHub Models": {
        "key_env": ("GITHUB_MODELS_TOKEN", "GITHUB_TOKEN"),
        "kind": "openai_compatible",
        "base_url": "https://models.github.ai/inference",
        "extra_headers": {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        "models": ["openai/gpt-4.1-mini", "openai/gpt-4.1", "meta/Llama-3.3-70B-Instruct", "microsoft/Phi-4"],
        "no_live_list": True,
        "free_tier": True,
        "free_note": "Free prototyping limits with a GitHub token that has the models:read permission.",
        "signup": "https://github.com/settings/personal-access-tokens",
        "docs": "https://docs.github.com/en/github-models",
    },
    "Hugging Face API": {
        "key_env": ("HF_TOKEN", "HUGGINGFACE_API_KEY"),
        "kind": "openai_compatible",
        "base_url": "https://router.huggingface.co/v1",
        "models": ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen3-32B", "openai/gpt-oss-120b"],
        "preset_ids_unverified": True,
        "free_tier": True,
        "free_note": "Monthly free credits on a free account (token needs Inference Providers permission).",
        "signup": "https://huggingface.co/settings/tokens",
        "docs": "https://huggingface.co/docs/inference-providers",
    },
    "Cloudflare Workers AI": {
        "key_env": ("CLOUDFLARE_API_TOKEN",),
        "extra_env": ("CLOUDFLARE_ACCOUNT_ID",),
        "kind": "cloudflare",
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "models": ["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/openai/gpt-oss-120b", "@cf/meta/llama-3.1-8b-instruct"],
        "preset_ids_unverified": True,
        "no_live_list": True,
        "free_tier": True,
        "free_note": "Daily free allowance on the free Workers plan; needs CLOUDFLARE_ACCOUNT_ID too.",
        "signup": "https://dash.cloudflare.com/profile/api-tokens",
        "docs": "https://developers.cloudflare.com/workers-ai/",
    },
    "Pollinations API": {
        "key_env": ("POLLINATIONS_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://gen.pollinations.ai/v1",
        "models": ["openai", "mistral"],
        "preset_ids_unverified": True,
        "free_tier": True,
        "free_note": "Free key from enter.pollinations.ai; also provides free image generation.",
        "signup": "https://enter.pollinations.ai",
        "docs": "https://gen.pollinations.ai/",
    },
    # User-managed OpenAI-compatible endpoints. These adapters do not assume or
    # hard-code third-party service URLs: set the URL and key you are authorized to use.
    "LiteLLM Proxy": {
        "key_env": ("LITELLM_API_KEY",),
        "base_url_env": "LITELLM_BASE_URL",
        "base_url_required": True,
        "kind": "openai_compatible",
        "models": ["openai/gpt-4o-mini"],
        "models_env": "LITELLM_MODELS",
        "free_tier": False,
        "free_note": "Connects to your own LiteLLM Proxy; upstream costs/limits depend on its configured provider.",
        "docs": "https://docs.litellm.ai/docs/",
    },
    "PawanOsman Compatible API": {
        "key_env": ("PAWANOSMAN_API_KEY",),
        "base_url_env": "PAWANOSMAN_BASE_URL",
        "base_url_required": True,
        "kind": "openai_compatible",
        "models": ["default"],
        "models_env": "PAWANOSMAN_MODELS",
        "free_tier": False,
        "free_note": "Only works with a user-configured, authorized OpenAI-compatible endpoint; service URL/model IDs vary.",
        "docs": None,
    },
    "Ollama Local": {
        "key_env": (),
        "kind": "ollama",
        "base_url_env": "OLLAMA_BASE_URL",
        "base_url": "http://127.0.0.1:11434",
        "models": ["llama3.3", "llama3.1:8b", "llama4:scout", "qwen3", "mistral"],
        "free_tier": True,
        "free_note": "Open-source models on your own hardware: zero cost, fully private.",
        "docs": "https://ollama.com/library",
    },
    # ------------------------------- paid / mixed ------------------------------ #
    "Gemini API": {
        "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "kind": "gemini",
        "models": [
            "gemini-4-argon", "gemini-3.8-flash", "gemini-3.6-flash",
            "gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3-flash-preview",
            "gemini-omni-1.1-flash",
        ],
        "free_tier": True,
        "free_note": "Has a free tier (key from AI Studio). Free-tier prompts may be used by Google; not offered in EEA/UK/CH.",
        "signup": "https://aistudio.google.com/apikey",
        "docs": "https://ai.google.dev/gemini-api/docs/models",
    },
    "OpenAI API": {
        "key_env": ("OPENAI_API_KEY",),
        "kind": "openai_responses",
        "base_url": "https://api.openai.com/v1",
        "models": [
            "gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-5.6", "gpt-5.5",
            "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.2", "gpt-5-mini",
            "gpt-5-nano", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
            "gpt-oss-120b", "gpt-oss-20b",
        ],
        "docs": "https://developers.openai.com/api/docs/models",
    },
    "Claude API": {
        "key_env": ("ANTHROPIC_API_KEY",),
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "temperature_max": 1.0,
        "models": [
            "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5",
            "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-4-5",
        ],
        "docs": "https://platform.claude.com/docs/en/api/messages",
    },
    "xAI Grok API": {
        "key_env": ("XAI_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://api.x.ai/v1",
        "models": [
            "grok-4.7", "grok-4.6", "grok-4.5", "grok-4.3", "grok-4.20-0309-reasoning",
            "grok-4-1-fast", "grok-3", "grok-3-mini",
        ],
        "docs": "https://docs.x.ai/developers/models",
    },
    "Meta Model API": {
        "key_env": ("META_MODEL_API_KEY", "MODEL_API_KEY"),
        "kind": "openai_compatible",
        "base_url": "https://api.meta.ai/v1",
        # Presets only; when a Meta key is configured the live model list replaces them.
        "models": ["muse-spark", "muse-wonder"],
        "preset_ids_unverified": True,
        "docs": "https://dev.meta.ai/docs/models",
    },
    "DeepSeek API": {
        "key_env": ("DEEPSEEK_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "docs": "https://api-docs.deepseek.com/",
    },
    "Perplexity API": {
        "key_env": ("PERPLEXITY_API_KEY",),
        "kind": "openai_compatible",
        "base_url": "https://api.perplexity.ai",
        "models": ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"],
        "docs": "https://docs.perplexity.ai/",
    },
}

# Image routes that call a real API directly (no g4f, no browser).
IMAGE_PROVIDERS: dict[str, dict[str, Any]] = {
    "Pollinations API": {
        "key_env": ("POLLINATIONS_API_KEY",),
        "kind": "pollinations_image",
        "models": ["flux", "turbo"],
        "free_tier": True,
        "docs": "https://gen.pollinations.ai/",
    },
    "Cloudflare Workers AI": {
        "key_env": ("CLOUDFLARE_API_TOKEN",),
        "extra_env": ("CLOUDFLARE_ACCOUNT_ID",),
        "kind": "cloudflare_image",
        "models": ["@cf/black-forest-labs/flux-1-schnell"],
        "free_tier": True,
        "docs": "https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/",
    },
}

# Community adapter presets are deliberately displayed as experimental. The
# provider adapter may not exist in an installed g4f version, may need browser
# state, and the model ID may not be supported by that provider.
COMMUNITY_PRESETS: list[tuple[str, str, str]] = [
    ("Gemini", "gemini-2.5-flash", "text"),
    ("GoogleAiMode", "gemini-2.5-flash", "text"),
    ("GoogleSearch", "gemini-2.5-flash", "text"),
    ("ChatGPT", "gpt-4o", "text"),
    ("OpenaiChat", "gpt-4o", "text"),
    ("Claude", "claude-sonnet-4-6", "text"),
    ("Grok", "grok-4", "text"),
    ("MetaAI", "llama", "text"),
    ("DeepSeek", "deepseek-chat", "text"),
    ("Perplexity", "sonar-pro", "text"),
    ("Blackbox", "blackbox", "text"),
    ("Copilot", "copilot", "text"),
    ("HuggingChat", "meta-llama/Llama-3.3-70B-Instruct", "text"),
    ("Qwen", "qwen3", "text"),
    ("Mistral", "mistral-large-latest", "text"),
    ("Kimi", "kimi-k2", "text"),
]


# --------------------------------------------------------------------------- #
# Keys / settings
# --------------------------------------------------------------------------- #
def _config(provider: str) -> dict[str, Any]:
    return STATIC_MODELS.get(provider) or IMAGE_PROVIDERS.get(provider) or {}


def key_is_configured(provider: str) -> bool:
    config = STATIC_MODELS.get(provider, {})
    if not any(os.getenv(name, "").strip() for name in config.get("key_env", ())):
        return False
    if config.get("base_url_required") and not os.getenv(config.get("base_url_env", ""), "").strip():
        return False
    return all(os.getenv(name, "").strip() for name in config.get("extra_env", ()))


def _configured_models(config: dict[str, Any]) -> list[str]:
    """Read a comma-separated model allow-list for configurable compatible proxies."""
    env_name = config.get("models_env")
    raw = os.getenv(env_name, "").strip() if env_name else ""
    if raw:
        return list(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))[:100]
    return list(config.get("models", []))


def _first_key(provider: str) -> tuple[Optional[str], list[str]]:
    config = _config(provider)
    names = list(config.get("key_env", ()))
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value, names
    return None, names


def _require_key(provider: str) -> str:
    key, names = _first_key(provider)
    if names and not key:
        raise ProviderCredentialsMissing(
            f"{provider} requires {' or '.join(names)}. Configure it in the server environment; no other provider was tried."
        )
    for extra in _config(provider).get("extra_env", ()):
        if not os.getenv(extra, "").strip():
            raise ProviderCredentialsMissing(
                f"{provider} also requires {extra}. Configure it in the server environment; no other provider was tried."
            )
    return key or ""


def _base_url(provider: str) -> str:
    config = STATIC_MODELS[provider]
    if config["kind"] == "cloudflare":
        account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{16,64}", account):
            raise ProviderCredentialsMissing(
                "CLOUDFLARE_ACCOUNT_ID looks invalid (expected the hex account ID from the Cloudflare dashboard)."
            )
        return config["base_url"].format(account_id=account)
    env_name = config.get("base_url_env")
    value = os.getenv(env_name, "").strip() if env_name else ""
    if config.get("base_url_required") and not value:
        raise ProviderCredentialsMissing(f"{provider} requires {env_name}; configure the authorized OpenAI-compatible base URL.")
    return (value or config["base_url"]).rstrip("/")


def catalog_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider, config in STATIC_MODELS.items():
        configured = key_is_configured(provider)
        needs_key = bool(config.get("key_env"))
        for model in _configured_models(config):
            rows.append({
                "id": f"{provider}|{model}",
                "provider": provider,
                "model": model,
                "type": "text",
                "verified_by": "official-model-preset",
                "route_kind": "local" if config["kind"] == "ollama" else "official_api",
                "auth_required": needs_key,
                "auth_configured": configured if needs_key else None,
                "availability": (
                    "preset ID; provider availability/quota may vary" if configured else
                    (f"requires-{config.get('base_url_env')}-and-provider-key" if config.get("base_url_required") and not os.getenv(config.get("base_url_env", ""), "").strip()
                     else "requires-provider-key; this is a model preset, not a live account check")
                ) if needs_key else "requires-local-ollama",
                "model_id_preset_unverified": bool(config.get("preset_ids_unverified", False)),
                "free_tier": bool(config.get("free_tier", False)),
                "free_note": config.get("free_note"),
                "signup": config.get("signup"),
                "docs": config.get("docs"),
            })
    for provider, config in IMAGE_PROVIDERS.items():
        configured = all(os.getenv(n, "").strip() for n in (*config["key_env"], *config.get("extra_env", ())))
        for model in config["models"]:
            rows.append({
                "id": f"{provider}|{model}",
                "provider": provider,
                "model": model,
                "type": "image",
                "verified_by": "official-model-preset",
                "route_kind": "official_api",
                "auth_required": True,
                "auth_configured": configured,
                "availability": "preset ID; needs provider key" if not configured else "preset ID; quota may vary",
                "free_tier": bool(config.get("free_tier", False)),
                "docs": config.get("docs"),
            })
    for provider, model, kind in COMMUNITY_PRESETS:
        rows.append({
            "id": f"g4f:{provider}|{model}",
            "provider": f"{provider} · community/experimental",
            "route_provider": f"g4f:{provider}",
            "model": model,
            "type": kind,
            "verified_by": "experimental-preset-not-live-verified",
            "route_kind": "g4f_community",
            "auth_required": None,
            "auth_configured": None,
            "availability": "unverified; provider may need session/cookies or may be offline",
        })
    return rows


# --------------------------------------------------------------------------- #
# Message normalisation
# --------------------------------------------------------------------------- #
def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}:
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        if "text" in value:
            return str(value["text"])
        return str(value)
    return str(value)


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return messages with roles system/user/assistant and plain-text content.

    * developer -> system, tool -> user (labelled) because most providers reject them.
    * empty messages are dropped (Anthropic/Gemini reject empty content).
    """
    clean: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "user")).lower()
        content = _text(message.get("content")).strip()
        if not content:
            continue
        if role == "developer":
            role = "system"
        elif role == "tool":
            role, content = "user", f"[tool result]\n{content}"
        elif role not in {"system", "user", "assistant"}:
            role = "user"
        clean.append({"role": role, "content": content})
    return clean


def _merge_alternating(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge consecutive same-role turns and make sure the first turn is a user turn."""
    merged: list[dict[str, str]] = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n\n" + message["content"]}
        else:
            merged.append(dict(message))
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "(conversation start)"})
    return merged


def _system_text(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(m["content"] for m in messages if m["role"] == "system")


# --------------------------------------------------------------------------- #
# HTTP result handling
# --------------------------------------------------------------------------- #
def _raise_for_provider(response: requests.Response, provider: str) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        data = {"message": response.text[:500]}
    if not response.ok:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or data.get("message")
        else:
            message = str(error) or (data.get("message") if isinstance(data, dict) else None)
        message = message or response.text[:350] or "provider returned an error"
        status = response.status_code
        hint = ""
        if status in (401, 403):
            hint = " (key rejected or missing permission; check the key/token scope)"
        elif status == 404:
            hint = " (model ID not found for this provider; refresh the catalog and pick a listed ID)"
        elif status == 429:
            hint = " (rate limit/quota reached; free tiers are limited)"
        retry_after: Optional[float] = None
        try:
            retry_after = float(response.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = None
        raise ProviderHTTPError(f"{provider} HTTP {status}: {redact(message, 300)}{hint}", status, retry_after)
    return data if isinstance(data, dict) else {"data": data}


def _clamp_temperature(config: dict[str, Any], temperature: float) -> float:
    return max(0.0, min(float(temperature), float(config.get("temperature_max", 2.0))))


# --------------------------------------------------------------------------- #
# Chat adapters
# --------------------------------------------------------------------------- #
def call_official_chat(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: int = 60,
) -> str:
    """Call exactly one official/local provider. Never changes provider or model."""
    if provider not in STATIC_MODELS:
        raise RuntimeError("unknown official provider")
    config = STATIC_MODELS[provider]
    kind = config["kind"]
    key = _require_key(provider)
    deadline = time.monotonic() + max(5, timeout)
    msgs = normalize_messages(messages)
    if not msgs or not any(m["role"] != "system" for m in msgs):
        raise RuntimeError("no non-empty user message to send")
    temp = _clamp_temperature(config, temperature)

    if kind == "ollama":
        base = _base_url(provider)
        ollama_headers = {"Content-Type": "application/json"}
        # Optional auth is used for hosted Ollama endpoints. Keep the secret in a
        # header; never put it into a URL or a log message. Local Ollama needs no key.
        ollama_api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        if ollama_api_key:
            ollama_headers["Authorization"] = f"Bearer {ollama_api_key}"
        try:
            response = http_client.post(
                f"{base}/api/chat",
                headers=ollama_headers,
                json={"model": model, "messages": msgs, "stream": False,
                      "options": {"temperature": temp, "num_predict": max_tokens}},
                timeout=timeout, deadline=deadline, retries=0,
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                f"Ollama is not reachable at {base}. On Render, 127.0.0.1 points to the Render container, "
                f"not your phone or PC. Set OLLAMA_BASE_URL to a reachable Ollama server; set OLLAMA_API_KEY "
                f"if that server requires bearer auth; then ensure model '{model}' is installed there."
            ) from exc
        data = _raise_for_provider(response, provider)
        answer = _text((data.get("message") or {}).get("content"))

    elif kind == "gemini":
        system = _system_text(msgs)
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in _merge_alternating([m for m in msgs if m["role"] != "system"])
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temp, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        # Key travels in a header: URLs (and therefore exception text) never contain it.
        response = http_client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=payload, timeout=timeout, deadline=deadline,
        )
        data = _raise_for_provider(response, provider)
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise RuntimeError(f"{provider} blocked the prompt ({block}).")
        candidates = data.get("candidates") or []
        pieces: list[str] = []
        finish = None
        for candidate in candidates:
            finish = finish or candidate.get("finishReason")
            for part in (candidate.get("content") or {}).get("parts", []) or []:
                if isinstance(part, dict) and not part.get("thought") and part.get("text"):
                    pieces.append(str(part["text"]))
        answer = "\n".join(pieces).strip()
        if not answer and finish == "MAX_TOKENS":
            raise RuntimeError(f"{provider} hit max_tokens before producing text (thinking models spend tokens on reasoning); raise max_tokens.")
        if not answer and finish:
            raise RuntimeError(f"{provider} returned no text (finishReason={finish}).")

    elif kind == "anthropic":
        system = _system_text(msgs)
        turns = _merge_alternating([m for m in msgs if m["role"] != "system"])
        payload = {"model": model, "max_tokens": max_tokens, "messages": turns, "temperature": temp}
        if system:
            payload["system"] = system
        response = http_client.post(
            f"{config['base_url']}/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=payload, timeout=timeout, deadline=deadline,
        )
        data = _raise_for_provider(response, provider)
        answer = "\n".join(
            _text(part.get("text")) for part in data.get("content", []) or []
            if isinstance(part, dict) and part.get("type", "text") == "text"
        ).strip()

    elif kind == "openai_responses":
        response = http_client.post(
            f"{config['base_url']}/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "input": msgs, "max_output_tokens": max(16, max_tokens)},
            timeout=timeout, deadline=deadline,
        )
        data = _raise_for_provider(response, provider)
        answer = _text(data.get("output_text"))
        if not answer:
            blocks = []
            for output_item in data.get("output", []) or []:
                for part in output_item.get("content", []) or []:
                    if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                        blocks.append(_text(part.get("text")))
            answer = "\n".join(blocks).strip()
        if not answer and data.get("status") == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason", "unknown")
            raise RuntimeError(f"{provider} response incomplete ({reason}); raise max_tokens.")

    elif kind in {"openai_compatible", "cloudflare"}:
        base = _base_url(provider)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        headers.update(config.get("extra_headers", {}))
        body: dict[str, Any] = {"model": model, "messages": msgs, "temperature": temp}
        body[config.get("token_param", "max_tokens")] = max_tokens
        response = http_client.post(f"{base}/chat/completions", headers=headers, json=body,
                                    timeout=timeout, deadline=deadline)
        data = _raise_for_provider(response, provider)
        choices = data.get("choices") or []
        first = choices[0] if choices else {}
        answer = _text((first.get("message") or {}).get("content")) if isinstance(first, dict) else ""
        if not answer.strip() and isinstance(first, dict) and first.get("finish_reason") == "length":
            raise RuntimeError(f"{provider} hit max_tokens before producing text; raise max_tokens.")
    else:
        raise RuntimeError(f"provider adapter kind is not implemented: {kind}")

    # Some reasoning models inline their chain of thought; strip complete <think> blocks only.
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()
    if not answer:
        raise RuntimeError(f"{provider} returned an empty response")
    return answer


# --------------------------------------------------------------------------- #
# Image adapters (real HTTP APIs; no mock output)
# --------------------------------------------------------------------------- #
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_SIZE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")


def _dims(size: Optional[str]) -> tuple[int, int]:
    match = _SIZE_RE.match(size or "")
    if not match:
        return 1024, 1024
    width, height = int(match.group(1)), int(match.group(2))
    return max(256, min(width, 2048)), max(256, min(height, 2048))


def _sniff_image(data: bytes) -> Optional[str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def call_official_image(provider: str, model: str, prompt: str, size: Optional[str], timeout: int = 90) -> tuple[bytes, str]:
    """Generate one image through one official API. Returns (bytes, extension)."""
    config = IMAGE_PROVIDERS.get(provider)
    if not config:
        raise RuntimeError("unknown image provider")
    if model not in config["models"]:
        # Image model IDs are fixed per route; refuse instead of guessing another one.
        raise RuntimeError(f"{provider} image model '{model}' is not in this route's list: {', '.join(config['models'])}")
    key = _require_key(provider)
    deadline = time.monotonic() + max(10, timeout)
    width, height = _dims(size)

    if config["kind"] == "pollinations_image":
        if len(prompt) > 1500:
            raise RuntimeError("Pollinations image prompts are sent in the URL; keep them under 1500 characters.")
        response = http_client.get(
            f"https://gen.pollinations.ai/image/{quote(prompt, safe='')}",
            params={"model": model, "width": width, "height": height, "nologo": "true"},
            headers={"Authorization": f"Bearer {key}"}, timeout=timeout, deadline=deadline, retries=1,
        )
        if not response.ok:
            _raise_for_provider(response, provider)
        data = response.content
    else:  # cloudflare_image
        account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{16,64}", account):
            raise ProviderCredentialsMissing("CLOUDFLARE_ACCOUNT_ID looks invalid.")
        response = http_client.post(
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"prompt": prompt[:2000], "steps": 4}, timeout=timeout, deadline=deadline,
        )
        body = _raise_for_provider(response, provider)
        if body.get("success") is False:
            errors = "; ".join(str(e.get("message", e)) for e in (body.get("errors") or []) if e)
            raise RuntimeError(f"{provider} reported failure: {redact(errors or 'unknown error', 250)}")
        encoded = (body.get("result") or {}).get("image")
        if not encoded:
            raise RuntimeError(f"{provider} returned no image data")
        try:
            data = base64.b64decode(encoded, validate=False)
        except Exception as exc:
            raise RuntimeError(f"{provider} returned undecodable image data") from exc

    if len(data) > _MAX_IMAGE_BYTES:
        raise RuntimeError("image larger than the 15MB safety limit")
    ext = _sniff_image(data)
    if not ext:
        raise RuntimeError(f"{provider} did not return a valid image (got {len(data)} bytes of non-image data)")
    return data, ext


# --------------------------------------------------------------------------- #
# Live model discovery
# --------------------------------------------------------------------------- #
def _chat_model_ok(provider: str, model_id: str) -> bool:
    value = model_id.lower()
    denied = ("embedding", "embed", "moderation", "whisper", "transcribe", "tts", "realtime", "image", "video",
              "voice", "segmentation", "sam-", "rerank", "dall-e", "stable-diffusion", "flux")
    if any(part in value for part in denied):
        return False
    extra = STATIC_MODELS.get(provider, {}).get("live_deny", ())
    if any(part in value for part in extra):
        return False
    if provider == "OpenAI API":
        return value.startswith(("gpt-", "o1", "o3", "o4", "chatgpt", "gpt-oss"))
    if provider == "Claude API":
        return value.startswith("claude-")
    if provider == "xAI Grok API":
        return value.startswith("grok-")
    if provider == "Meta Model API":
        return any(part in value for part in ("muse", "llama", "wonder", "spark"))
    if provider == "DeepSeek API":
        return value.startswith("deepseek-")
    if provider == "Perplexity API":
        return value.startswith("sonar")
    return True


def _live_model_ids(provider: str) -> list[str]:
    """Query a provider's own model-list API if that provider is configured."""
    config = STATIC_MODELS.get(provider, {})
    if not config or config.get("no_live_list"):
        return []
    if provider == "Ollama Local":
        try:
            base = _base_url(provider)
            response = http_client.get(f"{base}/api/tags", timeout=2, retries=0, deadline=time.monotonic() + 3)
            if not response.ok:
                return []
            names = [str(m.get("name", "")) for m in (response.json().get("models") or []) if isinstance(m, dict)]
            return sorted({n for n in names if n and "embed" not in n.lower()})[:300]
        except Exception:
            return []
    if not key_is_configured(provider):
        return []
    key, _ = _first_key(provider)
    headers: dict[str, str] = {"Authorization": f"Bearer {key}"}
    params: dict[str, Any] = {}
    if provider == "Gemini API":
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {"x-goog-api-key": key or ""}
        params = {"pageSize": 200}
    elif provider == "Claude API":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
        params = {"limit": 1000}
    elif config.get("kind") in {"openai_responses", "openai_compatible"}:
        try:
            url = f"{_base_url(provider) if config['kind'] == 'openai_compatible' else config['base_url']}/models"
        except ProviderCredentialsMissing:
            return []
        headers.update(config.get("extra_headers", {}))
    else:
        return []
    try:
        response = http_client.get(url, headers=headers, params=params, timeout=4, retries=1, deadline=time.monotonic() + 8)
        if not response.ok:
            return []
        payload = response.json()
    except Exception:
        return []

    if provider == "Gemini API":
        ids = []
        for item in (payload.get("models", []) if isinstance(payload, dict) else []):
            name = str(item.get("name", "")).removeprefix("models/")
            methods = item.get("supportedGenerationMethods", []) or []
            if not name or "generateContent" not in methods:
                continue
            if any(x in name.lower() for x in ("image", "audio", "live", "tts", "transcribe", "embedding", "veo", "video")):
                continue
            ids.append(name)
    else:
        if isinstance(payload, dict):
            candidates = payload.get("data", [])
        elif isinstance(payload, list):
            candidates = payload
        else:
            candidates = []
        ids = [str(item.get("id", "")) for item in candidates if isinstance(item, dict) and item.get("id")]
        ids = [model_id for model_id in ids if _chat_model_ok(provider, model_id)]
    return sorted(set(ids))[:300]


def get_runtime_provider_catalog() -> list[dict[str, Any]]:
    """Return model rows plus live provider catalogs and adapter availability."""
    rows = catalog_rows()
    to_query = [name for name, cfg in STATIC_MODELS.items()
                if (key_is_configured(name) or name == "Ollama Local") and not cfg.get("no_live_list")]
    live_ids_by_provider: dict[str, list[str]] = {}
    if to_query:
        with ThreadPoolExecutor(max_workers=min(8, len(to_query))) as pool:
            futures = {pool.submit(_live_model_ids, name): name for name in to_query}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    live_ids = future.result()
                except Exception:
                    live_ids = []
                if live_ids:
                    live_ids_by_provider[provider] = live_ids
                config = STATIC_MODELS[provider]
                for model_id in live_ids:
                    local = config["kind"] == "ollama"
                    rows.append({
                        "id": f"{provider}|{model_id}", "provider": provider, "model": model_id,
                        "type": "text",
                        "verified_by": "provider-live-models-api",
                        "route_kind": "local" if local else "official_api",
                        "auth_required": not local, "auth_configured": True if not local else None,
                        "availability": ("installed in the local Ollama service" if local else
                                         "returned by provider model-list API; generation permission/quota may still vary"),
                        "free_tier": bool(config.get("free_tier", False)),
                        "free_note": config.get("free_note"),
                        "docs": config.get("docs"),
                    })
    # When a provider returns live IDs, hide its guessed presets and rely on its own list.
    rows = [row for row in rows if not (
        row.get("verified_by") == "official-model-preset" and row.get("type") == "text"
        and row.get("provider") in live_ids_by_provider
    )]
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["id"] not in deduped or row.get("verified_by") == "provider-live-models-api":
            deduped[row["id"]] = row
    rows = list(deduped.values())
    try:
        import g4f

        providers = getattr(g4f, "Provider", None)
    except Exception:
        providers = None
    for row in rows:
        if row.get("route_kind") != "g4f_community":
            continue
        name = row.get("route_provider", "").split(":", 1)[-1]
        available = False
        if providers is not None:
            for variant in (name, name.replace("-", "_"), name.replace("_", ""), re.sub(r"[^A-Za-z0-9]", "", name)):
                if getattr(providers, variant, None) is not None:
                    available = True
                    break
        row["adapter_installed"] = available
        if not available:
            row["availability"] = "adapter not detected in installed g4f; request will return an error, no fallback"
    return rows
