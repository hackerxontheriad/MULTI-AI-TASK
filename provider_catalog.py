"""Explicit provider/model catalog and single-route official API adapters.

Official providers are called directly through their documented APIs. Community
(g4f) entries are best-effort and may require a provider-specific session or
other prerequisites. This module never falls back between providers/models.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote

import requests

# Model IDs are a curated starting catalog. When API keys are configured, the
# provider may expose additional or different IDs; API errors are surfaced as-is.
# Model IDs can be changed by upstream vendors, so this catalog is not an uptime promise.
STATIC_MODELS: dict[str, dict[str, Any]] = {
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
    "Gemini API": {
        "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "kind": "gemini",
        "models": [
            "gemini-4-argon", "gemini-3.8-flash", "gemini-3.6-flash",
            "gemini-3.5-flash-lite", "gemini-3.1-pro-preview", "gemini-3-flash-preview",
            "gemini-omni-1.1-flash",
        ],
        "docs": "https://ai.google.dev/gemini-api/docs/models",
    },
    "Claude API": {
        "key_env": ("ANTHROPIC_API_KEY",),
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
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
        # These names are examples/presets only; when a Meta key is configured,
        # the actual API model IDs should be checked in the provider dashboard.
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
    "Ollama Local": {
        "key_env": (),
        "kind": "ollama",
        "base_url_env": "OLLAMA_BASE_URL",
        "base_url": "http://127.0.0.1:11434",
        "models": ["llama3.3", "llama3.1:8b", "llama4:scout", "qwen3", "mistral"],
        "docs": "https://ollama.com/library",
    },
}

# Community adapter presets are deliberately displayed as experimental. The
# provider adapter may not exist in an installed g4f version, may need browser
# state, and the model ID may not be supported by that provider. A real request
# is attempted only when the user chooses that exact row.
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


def key_is_configured(provider: str) -> bool:
    config = STATIC_MODELS.get(provider, {})
    return any(os.getenv(name, "").strip() for name in config.get("key_env", ()))


def _first_key(provider: str) -> tuple[str | None, list[str]]:
    config = STATIC_MODELS[provider]
    names = list(config.get("key_env", ()))
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value, names
    return None, names


def catalog_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider, config in STATIC_MODELS.items():
        configured = key_is_configured(provider)
        for model in config["models"]:
            # All these entries are explicit single-provider routes, not auto aliases.
            rows.append({
                "id": f"{provider}|{model}",
                "provider": provider,
                "model": model,
                "type": "text",
                "verified_by": "official-model-preset",
                "route_kind": "local" if config["kind"] == "ollama" else "official_api",
                "auth_required": bool(config.get("key_env")),
                "auth_configured": configured if config.get("key_env") else None,
                "availability": (
                    "preset ID; provider availability/quota may vary"
                    if configured else "requires-provider-key; this is a model preset, not a live account check"
                ) if config.get("key_env") else "requires-local-ollama",
                "model_id_preset_unverified": bool(config.get("preset_ids_unverified", False)),
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}:
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        if "text" in value:
            return str(value["text"])
        return str(value)
    return str(value)


def call_official_chat(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: int = 60,
) -> str:
    """Call exactly one official/local provider. Never retry or change models."""
    if provider not in STATIC_MODELS:
        raise RuntimeError("unknown official provider")
    config = STATIC_MODELS[provider]
    kind = config["kind"]
    key, key_names = _first_key(provider)
    if key_names and not key:
        names = " or ".join(key_names)
        raise ProviderCredentialsMissing(
            f"{provider} requires {names}. Configure it in the server environment; no other provider was tried."
        )

    if kind == "ollama":
        base = os.getenv(config.get("base_url_env", ""), config["base_url"]).strip().rstrip("/")
        response = requests.post(
            f"{base}/api/chat",
            json={"model": model, "messages": messages, "stream": False,
                  "options": {"temperature": temperature, "num_predict": max_tokens}},
            timeout=timeout,
        )
        data = _raise_for_provider(response, provider)
        answer = _text(data.get("message", {}).get("content"))
    elif kind == "gemini":
        base = "https://generativelanguage.googleapis.com/v1beta/models/"
        system_parts = [_text(m.get("content")) for m in messages if m.get("role") in {"system", "developer"}]
        contents = []
        for message in messages:
            role = message.get("role", "user")
            if role in {"system", "developer"}:
                continue
            contents.append({"role": "model" if role == "assistant" else "user",
                             "parts": [{"text": _text(message.get("content"))}]})
        payload: dict[str, Any] = {"contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        if any(system_parts):
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(x for x in system_parts if x)}]}
        response = requests.post(
            f"{base}{quote(model, safe='')}:generateContent",
            params={"key": key}, json=payload, timeout=timeout,
        )
        data = _raise_for_provider(response, provider)
        candidates = data.get("candidates") or []
        answer = "\n".join(
            _text(part.get("text")) for candidate in candidates
            for part in candidate.get("content", {}).get("parts", []) if isinstance(part, dict)
        ).strip()
    elif kind == "anthropic":
        base = config["base_url"]
        system_parts = [_text(m.get("content")) for m in messages if m.get("role") in {"system", "developer"}]
        anthropic_messages = [
            {"role": "assistant" if m.get("role") == "assistant" else "user",
             "content": _text(m.get("content"))}
            for m in messages if m.get("role") not in {"system", "developer", "tool"}
        ]
        payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                                  "messages": anthropic_messages, "temperature": temperature}
        if any(system_parts):
            payload["system"] = "\n\n".join(x for x in system_parts if x)
        response = requests.post(
            f"{base}/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"},
            json=payload, timeout=timeout,
        )
        data = _raise_for_provider(response, provider)
        answer = "\n".join(_text(part.get("text")) for part in data.get("content", []) if isinstance(part, dict)).strip()
    elif kind == "openai_responses":
        input_messages = []
        for message in messages:
            role = message.get("role", "user")
            if role == "tool":
                # Tool results need tool-call context not carried by this simple UI.
                raise RuntimeError("OpenAI Responses adapter does not accept standalone tool-role messages")
            input_messages.append({"role": role, "content": _text(message.get("content"))})
        response = requests.post(
            f"{config['base_url']}/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "input": input_messages, "max_output_tokens": max_tokens},
            timeout=timeout,
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
    elif kind == "openai_compatible":
        response = requests.post(
            f"{config['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=timeout,
        )
        data = _raise_for_provider(response, provider)
        choices = data.get("choices") or []
        answer = _text(choices[0].get("message", {}).get("content")) if choices else ""
    else:
        raise RuntimeError(f"provider adapter kind is not implemented: {kind}")

    if not answer.strip():
        raise RuntimeError(f"{provider} returned an empty response")
    return answer.strip()


class ProviderCredentialsMissing(RuntimeError):
    """Selected provider needs a key that is not configured."""


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
            message = str(error) or data.get("message")
        message = message or response.text[:350] or "provider returned an error"
        raise RuntimeError(f"{provider} HTTP {response.status_code}: {str(message)[:350]}")
    return data if isinstance(data, dict) else {"data": data}


def _live_model_ids(provider: str) -> list[str]:
    """Query a provider's own model-list API if that provider key is configured."""
    config = STATIC_MODELS.get(provider, {})
    key, key_names = _first_key(provider) if provider in STATIC_MODELS else (None, [])
    if not key or provider == "Ollama Local":
        return []
    headers = {"Authorization": f"Bearer {key}"}
    params: dict[str, Any] = {}
    url = ""
    if provider == "Gemini API":
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        params = {"key": key}
        headers = {}
    elif provider == "Claude API":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        params = {"limit": 1000}
    elif provider == "OpenAI API":
        url = "https://api.openai.com/v1/models"
    elif provider == "xAI Grok API":
        url = "https://api.x.ai/v1/models"
    elif provider == "Meta Model API":
        url = "https://api.meta.ai/v1/models"
    elif provider == "DeepSeek API":
        url = "https://api.deepseek.com/models"
    elif provider == "Perplexity API":
        url = "https://api.perplexity.ai/models"
    else:
        return []
    try:
        response = requests.get(url, headers=headers, params=params, timeout=4)
        if not response.ok:
            return []
        payload = response.json()
    except Exception:
        return []

    if provider == "Gemini API":
        candidates = payload.get("models", []) if isinstance(payload, dict) else []
        ids = []
        for item in candidates:
            name = str(item.get("name", "")).removeprefix("models/")
            methods = item.get("supportedGenerationMethods", []) or []
            if not name or "generateContent" not in methods:
                continue
            if any(x in name.lower() for x in ("image", "audio", "live", "tts", "transcribe", "embedding", "veo", "video")):
                continue
            ids.append(name)
    else:
        candidates = payload.get("data", []) if isinstance(payload, dict) else []
        ids = [str(item.get("id", "")) for item in candidates if isinstance(item, dict) and item.get("id")]
        def chatish(model_id: str) -> bool:
            value = model_id.lower()
            denied = ("embedding", "moderation", "whisper", "transcribe", "tts", "realtime", "image", "video", "voice", "segmentation", "sam-")
            if any(part in value for part in denied):
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
        ids = [model_id for model_id in ids if chatish(model_id)]
    # Stable, unique, bounded model list; no user-provided values are accepted here.
    return sorted(set(ids))[:300]


def get_runtime_provider_catalog() -> list[dict[str, Any]]:
    """Return model rows plus dynamic provider catalogs and adapter availability."""
    rows = catalog_rows()
    # Only make requests for providers for which the operator configured credentials.
    # Query in parallel, so a slow model-list endpoint doesn't block every other one.
    configured = [name for name in STATIC_MODELS if key_is_configured(name) and name != "Ollama Local"]
    live_ids_by_provider: dict[str, list[str]] = {}
    if configured:
        with ThreadPoolExecutor(max_workers=min(7, len(configured))) as pool:
            futures = {pool.submit(_live_model_ids, name): name for name in configured}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    live_ids = future.result()
                except Exception:
                    live_ids = []
                if live_ids:
                    live_ids_by_provider[provider] = live_ids
                for model_id in live_ids:
                    rows.append({
                        "id": f"{provider}|{model_id}", "provider": provider, "model": model_id,
                        "type": "text", "verified_by": "provider-live-models-api",
                        "route_kind": "official_api", "auth_required": True,
                        "auth_configured": True, "availability": "returned by provider model-list API; generation permission/quota may still vary",
                        "docs": STATIC_MODELS[provider].get("docs"),
                    })
    # When a provider returns live IDs, hide its guessed presets and rely on its
    # provider-reported list. This is especially important for model APIs with
    # account-specific model names.
    rows = [row for row in rows if not (
        row.get("verified_by") == "official-model-preset" and row.get("provider") in live_ids_by_provider
    )]
    # Prefer the live row's metadata where the ID overlaps with a static preset.
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
        route_provider = row.get("route_provider", "")
        name = route_provider.split(":", 1)[-1]
        available = False
        if providers is not None:
            for variant in (name, name.replace("-", "_"), name.replace("_", "")):
                if getattr(providers, variant, None) is not None:
                    available = True
                    break
        row["adapter_installed"] = available
        if not available:
            row["availability"] = "adapter not detected in installed g4f; request will return an error, no fallback"
    return rows
