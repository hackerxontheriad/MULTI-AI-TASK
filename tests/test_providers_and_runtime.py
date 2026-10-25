"""Offline tests for the free-tier adapters, SSL/HTTP layer, Chromium helper and limits.

No network, no browser launch and no provider credits are used.
"""
import asyncio
import base64
import sys
from pathlib import Path

import pytest
import requests
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import http_client
import main
import provider_catalog as pc
import runtime_env

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def run(coro):
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, status=200, data=None, content=b"", headers=None):
        self.status_code = status
        self._data = data
        self.content = content
        self.headers = headers or {}
        self.text = str(data) if data is not None else ""

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def close(self):
        pass


# ----------------------------- redaction / hints ----------------------------- #
def test_redact_removes_keys_in_urls_headers_and_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_supersecretvalue12345")
    text = ("HTTPSConnectionPool: url=/v1beta/models/x:generateContent?key=AIzaSyA1234567890abcdefghijkl "
            "Authorization: Bearer sk-proj-abcdefghijklmnop gsk_supersecretvalue12345")
    cleaned = http_client.redact(text)
    for secret in ("AIzaSyA1234567890abcdefghijkl", "sk-proj-abcdefghijklmnop", "gsk_supersecretvalue12345"):
        assert secret not in cleaned


def test_explain_exception_gives_actionable_ssl_and_dns_hints():
    cert = requests.exceptions.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    assert "CA_BUNDLE" in http_client.explain_exception(cert)
    dns = requests.exceptions.ConnectionError("Name or service not known")
    assert "DNS" in http_client.explain_exception(dns)
    assert http_client.explain_exception(ValueError("plain")) is None


# --------------------------------- http retries --------------------------------- #
class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _patch_session(monkeypatch, outcomes):
    session = FakeSession(outcomes)
    monkeypatch.setattr(http_client, "_session", lambda: session)
    monkeypatch.setattr(http_client.time, "sleep", lambda s: None)
    return session


def test_http_retries_transient_connection_error_then_succeeds(monkeypatch):
    session = _patch_session(monkeypatch, [requests.exceptions.ConnectionError("reset"), FakeResponse(200, {"ok": 1})])
    response = http_client.post("https://example.org/x", json={})
    assert response.status_code == 200 and session.calls == 2


def test_http_never_retries_certificate_verification_failure(monkeypatch):
    err = requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
    session = _patch_session(monkeypatch, [err, FakeResponse(200, {})])
    with pytest.raises(requests.exceptions.SSLError):
        http_client.get("https://example.org/x")
    assert session.calls == 1


def test_http_retries_503_but_not_long_retry_after(monkeypatch):
    session = _patch_session(monkeypatch, [FakeResponse(503, {}), FakeResponse(200, {"ok": 1})])
    assert http_client.get("https://example.org/x").status_code == 200 and session.calls == 2
    session = _patch_session(monkeypatch, [FakeResponse(429, {}, headers={"Retry-After": "300"}), FakeResponse(200, {})])
    assert http_client.get("https://example.org/x").status_code == 429 and session.calls == 1


def test_post_read_timeout_is_not_resent(monkeypatch):
    session = _patch_session(monkeypatch, [requests.exceptions.ReadTimeout("slow"), FakeResponse(200, {})])
    with pytest.raises(requests.exceptions.ReadTimeout):
        http_client.post("https://example.org/x", json={})
    assert session.calls == 1


# ------------------------------- provider adapters ------------------------------- #
def test_gemini_key_is_sent_in_header_not_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTESTTESTTESTTESTTESTTEST12")
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}, {"text": "visible"}]}, "finishReason": "STOP"}]})

    monkeypatch.setattr(pc.http_client, "post", fake_post)
    msgs = [{"role": "developer", "content": "be brief"}, {"role": "assistant", "content": "hi"}, {"role": "user", "content": "q"}]
    assert pc.call_official_chat("Gemini API", "gemini-3.8-flash", msgs, 0.5, 100, 30) == "visible"
    assert "AIza" not in seen["url"] and "key=" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"].startswith("AIza")
    assert [c["role"] for c in seen["json"]["contents"]] == ["user", "model", "user"]
    assert seen["json"]["systemInstruction"]["parts"][0]["text"] == "be brief"


def test_provider_error_text_never_contains_the_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_leakcheckleakcheck1234")
    monkeypatch.setattr(pc.http_client, "post", lambda url, **kw: FakeResponse(401, {"error": {"message": "bad key gsk_leakcheckleakcheck1234"}}))
    with pytest.raises(pc.ProviderHTTPError) as info:
        pc.call_official_chat("Groq API", "llama-3.3-70b-versatile", [{"role": "user", "content": "x"}], 0.7, 50, 30)
    assert "gsk_leakcheckleakcheck1234" not in str(info.value)
    assert info.value.status == 401


def test_temperature_is_clamped_per_provider(monkeypatch):
    sent = []
    monkeypatch.setattr(pc.http_client, "post", lambda url, **kw: (sent.append(kw["json"]), FakeResponse(200, {"content": [{"type": "text", "text": "ok"}], "choices": [{"message": {"content": "ok"}}]}))[1])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-aaaaaaaaaaaaaaaa")
    monkeypatch.setenv("MISTRAL_API_KEY", "m" * 16)
    pc.call_official_chat("Claude API", "claude-sonnet-4-6", [{"role": "user", "content": "x"}], 1.9, 50, 30)
    pc.call_official_chat("Mistral API", "mistral-small-latest", [{"role": "user", "content": "x"}], 2.0, 50, 30)
    assert sent[0]["temperature"] == 1.0 and sent[1]["temperature"] == 1.5


def test_anthropic_messages_alternate_and_start_with_user(monkeypatch):
    sent = []
    monkeypatch.setattr(pc.http_client, "post", lambda url, **kw: (sent.append(kw["json"]), FakeResponse(200, {"content": [{"type": "text", "text": "ok"}]}))[1])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-aaaaaaaaaaaaaaaa")
    msgs = [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}, {"role": "user", "content": "c"}]
    pc.call_official_chat("Claude API", "claude-sonnet-4-6", msgs, 0.5, 50, 30)
    assert [m["role"] for m in sent[0]["messages"]] == ["user", "assistant", "user"]


def test_cloudflare_requires_a_valid_account_id(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token-abcdef")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    with pytest.raises(pc.ProviderCredentialsMissing):
        pc.call_official_chat("Cloudflare Workers AI", "@cf/meta/llama-3.1-8b-instruct", [{"role": "user", "content": "x"}], 0.5, 50, 30)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "not-hex!")
    with pytest.raises(pc.ProviderCredentialsMissing):
        pc.call_official_chat("Cloudflare Workers AI", "@cf/meta/llama-3.1-8b-instruct", [{"role": "user", "content": "x"}], 0.5, 50, 30)


def test_free_provider_without_key_never_reaches_the_network(monkeypatch):
    for name in ("GROQ_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN", "HF_TOKEN", "HUGGINGFACE_API_KEY", "POLLINATIONS_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def boom(*args, **kwargs):
        raise AssertionError("network must not be touched without a key")

    monkeypatch.setattr(pc.http_client, "post", boom)
    for provider in ("Groq API", "Cerebras API", "Mistral API", "GitHub Models", "Hugging Face API", "Pollinations API"):
        with pytest.raises(pc.ProviderCredentialsMissing):
            pc.call_official_chat(provider, "m", [{"role": "user", "content": "x"}], 0.5, 50, 30)


def test_image_adapter_rejects_non_image_bytes_and_unknown_models(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "pk-aaaaaaaaaaaa")
    monkeypatch.setattr(pc.http_client, "get", lambda url, **kw: FakeResponse(200, content=b"<html>oops</html>"))
    with pytest.raises(RuntimeError, match="valid image"):
        pc.call_official_image("Pollinations API", "flux", "a cat", "1024x1024")
    with pytest.raises(RuntimeError, match="not in this route"):
        pc.call_official_image("Pollinations API", "other", "a cat", "1024x1024")
    monkeypatch.setattr(pc.http_client, "get", lambda url, **kw: FakeResponse(200, content=PNG))
    data, ext = pc.call_official_image("Pollinations API", "flux", "a cat", "1024x1536")
    assert ext == "png" and data == PNG


def test_cloudflare_image_decodes_base64(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token-abcdef")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "0123456789abcdef0123456789abcdef")
    body = {"success": True, "result": {"image": base64.b64encode(PNG).decode()}}
    monkeypatch.setattr(pc.http_client, "post", lambda url, **kw: FakeResponse(200, body))
    data, ext = pc.call_official_image("Cloudflare Workers AI", "@cf/black-forest-labs/flux-1-schnell", "x", None)
    assert ext == "png"


def test_ollama_live_models_replace_guessed_presets(monkeypatch):
    monkeypatch.setattr(pc.http_client, "get", lambda url, **kw: FakeResponse(200, {"models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text"}]}))
    assert pc._live_model_ids("Ollama Local") == ["llama3.2:3b"]


# --------------------------------- gateway layer --------------------------------- #
def test_provider_http_errors_map_to_clear_statuses(monkeypatch):
    async def raise_429(fn, *args, timeout):
        raise pc.ProviderHTTPError("Groq API HTTP 429: slow down", 429, 7.0)

    monkeypatch.setattr(main, "_run_official_thread", raise_429)
    with pytest.raises(HTTPException) as info:
        run(main._generate_chat("Groq API|llama-3.3-70b-versatile", [{"role": "user", "content": "x"}], 0.5, 50))
    assert info.value.status_code == 429
    assert info.value.headers["Retry-After"] == "7"
    assert info.value.detail["fallback_used"] is False

    async def raise_401(fn, *args, timeout):
        raise pc.ProviderHTTPError("Groq API HTTP 401: nope", 401)

    monkeypatch.setattr(main, "_run_official_thread", raise_401)
    with pytest.raises(HTTPException) as info:
        run(main._generate_chat("Groq API|x", [{"role": "user", "content": "x"}], 0.5, 50))
    assert info.value.status_code == 424 and info.value.detail["error"] == "provider_auth_failed"


def test_secret_never_leaks_through_generic_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-leak-leak-leak-1234")

    async def boom(fn, *args, timeout):
        raise requests.exceptions.ConnectionError("failed https://x/y?key=sk-leak-leak-leak-leak-1234")

    monkeypatch.setattr(main, "_run_official_thread", boom)
    with pytest.raises(HTTPException) as info:
        run(main._generate_chat("OpenAI API|gpt-5.5", [{"role": "user", "content": "x"}], 0.5, 50))
    assert "sk-leak-leak-leak-leak-1234" not in str(info.value.detail)
    assert info.value.detail["hint"]


def test_g4f_busy_returns_503_instead_of_queueing(monkeypatch):
    monkeypatch.setattr(main, "_g4f_active", main.G4F_MAX_WORKERS)
    with pytest.raises(HTTPException) as info:
        run(main._generate_chat("g4f:Gemini|gemini-2.5-flash", [{"role": "user", "content": "x"}], 0.5, 50))
    assert info.value.status_code == 503
    assert info.value.detail["error"] == "g4f_workers_busy"


def test_g4f_slot_is_released_after_success_and_failure(monkeypatch):
    monkeypatch.setattr(main, "_g4f_active", 0)
    assert run(main._run_g4f_thread(lambda: "ok", timeout=5)) == "ok"
    assert main._g4f_active == 0

    def fail():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        run(main._run_g4f_thread(fail, timeout=5))
    assert main._g4f_active == 0


def test_official_image_route_saves_a_real_file(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(main, "call_official_image", lambda *a, **k: (PNG, "png"))
    req = main.ImageRequest(prompt="a cat", model="Pollinations API|flux")
    body = run(main.image_generate(req, None))
    assert body["provider_mode"] == "official-api"
    url = body["data"][0]["url"]
    assert url.startswith("/media/img-") and (tmp_path / url.split("/")[-1]).read_bytes() == PNG


def test_image_route_missing_key_is_424_not_a_fake_image(monkeypatch):
    monkeypatch.delenv("POLLINATIONS_API_KEY", raising=False)
    with pytest.raises(HTTPException) as info:
        run(main.image_generate(main.ImageRequest(prompt="a cat", model="Pollinations API|flux"), None))
    assert info.value.status_code == 424
    assert info.value.detail["fake_media"] is False


def test_rate_limiter_blocks_after_limit(monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT_PER_MIN", 2)
    main._rate_hits.clear()

    class Req:
        client = type("C", (), {"host": "1.2.3.4"})()
        headers = {}

    run(main.rate_limit(Req()))
    run(main.rate_limit(Req()))
    with pytest.raises(HTTPException) as info:
        run(main.rate_limit(Req()))
    assert info.value.status_code == 429 and "Retry-After" in info.value.headers


def test_failed_catalog_fetch_is_retried_sooner(monkeypatch):
    monkeypatch.setattr(main, "_fetch_catalog_sync", lambda: ([], None, "offline"))
    main._cache.update({"at": 0, "rows": [], "source": None, "error": None})
    result = run(main.get_catalog(refresh=True))
    assert result["ttl"] <= 60


# ------------------------------------ chromium ------------------------------------ #
def test_stale_chrome_env_is_removed_and_real_binary_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BIN", "/definitely/not/here/chromium")
    monkeypatch.setenv("CHROMIUM_PATH", "/definitely/not/here/chromium")
    monkeypatch.delenv("GOOGLE_CHROME_BIN", raising=False)
    monkeypatch.setattr(runtime_env.shutil, "which", lambda name: None)
    monkeypatch.setattr(runtime_env, "_CANDIDATE_PATHS", ())
    info = runtime_env.configure_runtime()
    assert info["chrome"] is None
    import os
    assert "CHROME_BIN" not in os.environ and "CHROMIUM_PATH" not in os.environ

    fake = tmp_path / "chromium"
    fake.write_text("#!/bin/sh\necho Chromium 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CHROME_BIN", str(fake))
    assert runtime_env.configure_runtime()["chrome"] == str(fake)
    assert os.environ["CHROMIUM_PATH"] == str(fake)


def test_browser_flags_include_container_safety(monkeypatch):
    monkeypatch.setenv("BROWSER_NO_SANDBOX", "1")
    flags = runtime_env.browser_flags()
    assert "--no-sandbox" in flags and "--disable-dev-shm-usage" in flags and "--headless=new" in flags
    monkeypatch.setenv("BROWSER_NO_SANDBOX", "0")
    assert "--no-sandbox" not in runtime_env.browser_flags()


def test_probe_reports_missing_browser_clearly(monkeypatch):
    monkeypatch.setattr(runtime_env, "find_chrome", lambda: None)
    result = runtime_env.probe_browser(force=True)
    assert result["found"] is False and result["launch_ok"] is False and result["hint"]


def test_probe_reports_real_launch_result(monkeypatch, tmp_path):
    fake = tmp_path / "chromium"
    fake.write_text("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Chromium 140'; else echo '<html><head></head><body></body></html>'; fi\n")
    fake.chmod(0o755)
    monkeypatch.setattr(runtime_env, "find_chrome", lambda: str(fake))
    result = runtime_env.probe_browser(force=True)
    assert result["launch_ok"] is True and "Chromium" in result["version"]


def test_dotenv_is_loaded_without_overriding_real_env(monkeypatch, tmp_path):
    import os
    env = tmp_path / ".env"
    env.write_text('# comment\nGROQ_API_KEY=gsk_fromfile123456\nMISTRAL_API_KEY=\nexport CEREBRAS_API_KEY="csk-quoted-value-1"\nOLLAMA_BASE_URL=http://box:11434 # trailing\nNOT VALID LINE\n')
    for name in ("GROQ_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://real-env:1")  # real env wins
    loaded = runtime_env.load_dotenv(env)
    assert os.environ["GROQ_API_KEY"] == "gsk_fromfile123456"
    assert os.environ["CEREBRAS_API_KEY"] == "csk-quoted-value-1"
    assert os.environ["OLLAMA_BASE_URL"] == "http://real-env:1"
    assert "MISTRAL_API_KEY" not in os.environ  # blank template values are skipped
    assert "GROQ_API_KEY" in loaded and "OLLAMA_BASE_URL" not in loaded
    os.environ.pop("GROQ_API_KEY", None); os.environ.pop("CEREBRAS_API_KEY", None)


def test_compatible_proxy_requires_explicit_url_and_key(monkeypatch):
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    assert not pc.key_is_configured("LiteLLM Proxy")
    monkeypatch.setenv("LITELLM_API_KEY", "test-local-key-12345")
    assert not pc.key_is_configured("LiteLLM Proxy")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
    assert pc.key_is_configured("LiteLLM Proxy")
    monkeypatch.setenv("LITELLM_MODELS", "team/model-a,team/model-b")
    rows = [r for r in pc.catalog_rows() if r["provider"] == "LiteLLM Proxy"]
    assert {r["model"] for r in rows} == {"team/model-a", "team/model-b"}


def test_shared_chrome_error_has_actionable_hint():
    exc = RuntimeError("Failed to start shared Chrome on port 33857; dbus/bus.cc")
    hint = http_client.explain_exception(exc)
    assert hint and "server-side Chrome" in hint and "/v1/diagnostics" in hint


def test_litellm_proxy_uses_explicit_base_url_and_selected_model(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "local-test-key-123456")
    seen = {}
    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse(200, {"choices": [{"message": {"content": "proxy response"}, "finish_reason": "stop"}]})
    monkeypatch.setattr(pc.http_client, "post", fake_post)
    answer = pc.call_official_chat("LiteLLM Proxy", "team/model-a", [{"role": "user", "content": "hello"}], 0.4, 100, 10)
    assert answer == "proxy response"
    assert seen["url"] == "http://127.0.0.1:4000/v1/chat/completions"
    assert seen["json"]["model"] == "team/model-a"
    assert seen["headers"]["Authorization"] == "Bearer local-test-key-123456"


def test_ollama_hosted_api_key_is_sent_as_bearer_header(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.example")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-test-secret")
    captured = {}
    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return FakeResponse(data={"message": {"content": "ok"}})
    monkeypatch.setattr(pc.http_client, "post", fake_post)
    result = pc.call_official_chat("Ollama Local", "llama3.1:8b", [{"role":"user","content":"hi"}], 0.2, 64, timeout=5)
    assert result == "ok"
    assert captured["url"] == "https://ollama.example/api/chat"
    assert captured["headers"]["Authorization"] == "Bearer ollama-test-secret"

def test_ollama_diagnostic_does_not_expose_api_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.example")
    monkeypatch.setenv("OLLAMA_API_KEY", "super-secret-ollama-key")
    class Response:
        status_code = 200
        content = b'{"models":[{"name":"llama3.1:8b"}]}'
        def json(self): return {"models":[{"name":"llama3.1:8b"}]}
    monkeypatch.setattr(main.requests, "get", lambda *a, **kw: Response())
    result = main._ollama_diagnostic()
    assert result["reachable"] is True
    assert result["installed_models"] == ["llama3.1:8b"]
    assert "super-secret-ollama-key" not in repr(result)
