"""Shared HTTP helpers: CA/SSL setup, bounded retries and secret redaction.

Design rules
------------
* TLS verification is never disabled. If certificates are broken the error says
  how to fix the environment (CA bundle) instead of hiding the problem.
* Retries go to the *same* URL only (transient network/SSL/429/5xx). This is not
  provider/model fallback, so the single-route guarantee still holds.
* Every error string that can reach a client passes through ``redact``.
"""
from __future__ import annotations

import os
import re
import ssl
import threading
import time
from typing import Any, Optional

import requests

# --------------------------------------------------------------------------- #
# CA bundle / SSL
# --------------------------------------------------------------------------- #
_ca_lock = threading.Lock()
_ca_state: dict[str, Any] = {"configured": False, "bundle": None, "source": None}


def configure_ca_bundle() -> dict[str, Any]:
    """Point requests/urllib3/aiohttp/curl at one valid CA bundle (idempotent).

    Order: CA_BUNDLE env -> already-set REQUESTS_CA_BUNDLE/SSL_CERT_FILE (if the
    file exists) -> certifi -> system default. Never turns verification off.
    """
    with _ca_lock:
        if _ca_state["configured"]:
            return dict(_ca_state)
        candidates: list[tuple[str, Optional[str]]] = [
            ("CA_BUNDLE", os.getenv("CA_BUNDLE")),
            ("REQUESTS_CA_BUNDLE", os.getenv("REQUESTS_CA_BUNDLE")),
            ("SSL_CERT_FILE", os.getenv("SSL_CERT_FILE")),
        ]
        chosen: Optional[str] = None
        source: Optional[str] = None
        for name, value in candidates:
            if value and os.path.isfile(value):
                chosen, source = value, name
                break
        if chosen is None:
            try:
                import certifi  # type: ignore

                path = certifi.where()
                if os.path.isfile(path):
                    chosen, source = path, "certifi"
            except Exception:
                pass
        if chosen is None:
            paths = ssl.get_default_verify_paths()
            for path in (paths.cafile, "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
                if path and os.path.isfile(path):
                    chosen, source = path, "system"
                    break
        if chosen:
            # setdefault would keep a *broken* inherited path, so assign explicitly.
            os.environ["REQUESTS_CA_BUNDLE"] = chosen
            os.environ["SSL_CERT_FILE"] = chosen
            os.environ["CURL_CA_BUNDLE"] = chosen
        _ca_state.update({"configured": True, "bundle": chosen, "source": source})
        return dict(_ca_state)


def ca_info() -> dict[str, Any]:
    return configure_ca_bundle()


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
_SECRET_ENV_NAMES = (
    "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY",
    "META_MODEL_API_KEY", "MODEL_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY",
    "GROQ_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN",
    "HF_TOKEN", "HUGGINGFACE_API_KEY", "CLOUDFLARE_API_TOKEN", "POLLINATIONS_API_KEY",
    "API_ACCESS_TOKEN",
)
_PATTERNS = (
    re.compile(r"([?&](?:key|api_key|apikey|access_token|token)=)[^&\s'\"]+", re.I),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-~+/=]{8,}", re.I),
    re.compile(r"((?:x-api-key|x-goog-api-key|authorization)['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+", re.I),
    re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{12,}|gsk_[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_\-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{20,}|csk-[A-Za-z0-9]{12,})"),
)


def redact(text: Any, limit: int = 400) -> str:
    """Remove API keys/tokens from any string before logging or returning it."""
    value = str(text)
    for name in _SECRET_ENV_NAMES:
        secret = os.getenv(name, "").strip()
        if len(secret) >= 8:
            value = value.replace(secret, "***")
    for pattern in _PATTERNS:
        if pattern.groups:
            value = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "***", value)
        else:
            value = pattern.sub("***", value)
    value = value.replace("\r", " ").replace("\n", " ")
    return value[:limit]


# --------------------------------------------------------------------------- #
# Error classification (actionable hints, never secrets)
# --------------------------------------------------------------------------- #
def explain_exception(exc: BaseException) -> Optional[str]:
    """Return a short, actionable hint for common environment failures."""
    text = f"{type(exc).__name__} {exc}".lower()
    if "certificate_verify_failed" in text or "unable to get local issuer" in text or "self signed certificate" in text:
        return ("TLS certificate verification failed. Install ca-certificates (Docker image does this), "
                "or set CA_BUNDLE=/path/to/ca.pem if you are behind a corporate/mobile proxy. "
                "Verification is intentionally not disabled.")
    if isinstance(exc, requests.exceptions.SSLError) or "sslerror" in text or "ssl:" in text or "eof occurred in violation" in text:
        return "Transient TLS/SSL error talking to the provider; retry shortly. If it persists, check the host clock, proxy or CA bundle."
    if "name or service not known" in text or "temporary failure in name resolution" in text or "nodename nor servname" in text or "getaddrinfo" in text:
        return "DNS lookup failed. The host has no outbound network access or a blocked/bad DNS resolver."
    if isinstance(exc, requests.exceptions.ProxyError) or "proxyerror" in text:
        return "Proxy error. Check HTTP_PROXY/HTTPS_PROXY/NO_PROXY settings."
    if isinstance(exc, (requests.exceptions.ConnectTimeout,)) or "connecttimeout" in text:
        return "Timed out connecting to the provider (host blocks egress or provider is down)."
    if isinstance(exc, requests.exceptions.ReadTimeout) or "readtimeout" in text:
        return "Provider accepted the connection but did not answer in time. Try again or pick a faster model."
    if isinstance(exc, requests.exceptions.ConnectionError) or "connection refused" in text or "connection reset" in text:
        return "Could not connect to the provider (connection refused/reset). Check network egress and base URL."
    if "missingautherror" in text or ("login" in text and "required" in text) or ("api key" in text and "missing" in text):
        return "This provider needs a server-side API key or authorized endpoint configuration. Use a supported provider route."
    if "missingautherror" in text or ("login" in text and "required" in text) or ("api key" in text and "missing" in text):
        return "This adapter needs a login/cookie/API key; it cannot run anonymously. Use an official free-tier API route instead."
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return "Provider rate limit reached (free tiers are rate limited). Wait a bit or choose another provider yourself."
    return None


_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


_session_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_session_local, "session", None)
    if session is None:
        configure_ca_bundle()
        session = requests.Session()
        session.headers.update({"User-Agent": "MADX-Hybrid-AI-Studio/18.0"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session_local.session = session
    return session


def request(
    method: str,
    url: str,
    *,
    timeout: float = 30.0,
    retries: int = 2,
    deadline: Optional[float] = None,
    **kwargs: Any,
) -> requests.Response:
    """HTTP request with bounded retries on the SAME url.

    * Retries: connection errors, TLS EOF/handshake errors, read timeouts on
      idempotent GETs, and 429/5xx (honouring a short Retry-After).
    * Never retries certificate-verification failures (cannot succeed).
    * ``deadline`` is an absolute ``time.monotonic()`` budget so retries cannot
      outlive the caller's own timeout (prevents stuck worker threads).
    """
    if deadline is None:
        deadline = time.monotonic() + max(timeout, 1.0) * (retries + 1)
    session = _session()
    attempt = 0
    last_exc: Optional[BaseException] = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            if last_exc is not None:
                raise last_exc
            raise requests.exceptions.Timeout("request budget exhausted before the provider answered")
        connect_timeout = min(10.0, remaining)
        read_timeout = max(1.0, min(timeout, remaining))
        try:
            response = session.request(method, url, timeout=(connect_timeout, read_timeout), **kwargs)
        except requests.exceptions.SSLError as exc:
            if "certificate_verify_failed" in str(exc).lower() or attempt >= retries:
                raise
            last_exc = exc
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as exc:
            if attempt >= retries:
                raise
            last_exc = exc
        except requests.exceptions.ReadTimeout as exc:
            # Re-sending a completion POST after a read timeout could double-bill; GET only.
            if method.upper() != "GET" or attempt >= retries:
                raise
            last_exc = exc
        else:
            if response.status_code in _TRANSIENT_STATUS and attempt < retries:
                wait = _retry_after_seconds(response)
                budget_left = deadline - time.monotonic()
                if wait is None:
                    wait = 0.8 * (2 ** attempt)
                if wait <= min(4.0, budget_left - 1.0):
                    response.close()
                    attempt += 1
                    time.sleep(wait)
                    continue
            return response
        attempt += 1
        time.sleep(min(0.8 * (2 ** (attempt - 1)), max(0.0, deadline - time.monotonic() - 1.0)))


def get(url: str, **kwargs: Any) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    return request("POST", url, **kwargs)
