import asyncio
import json
import os
import sys
from pathlib import Path
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def run(coro):
    return asyncio.run(coro)


def test_parse_working_results_filters_routers_and_bad_lines():
    raw = """# heading
Blackbox|gpt-4o-mini|text
KiloCode|openrouter/free|text
BlackForestLabs_Flux1Dev|flux-dev|image
Bogus|bad|not-a-kind
missing-delimiter
Blackbox|gpt-4o-mini|text
"""
    rows = main.parse_working_results(raw)
    assert len(rows) == 2
    assert rows[0]["model"] == "gpt-4o-mini"
    assert rows[1]["type"] == "image"
    assert all("openrouter" not in row["id"].lower() for row in rows)


def test_health_payload_does_not_require_g4f_installed():
    payload = main._health_info()
    assert payload["status"] == "ok"
    assert payload["official_api_keys_supported"] is True
    assert payload["official_provider_count"] >= 7
    assert isinstance(payload["g4f_installed"], bool)


def test_root_is_a_file_response():
    response = run(main.home())
    assert str(response.path).endswith("index.html")


def test_catalog_falls_back_to_auto(monkeypatch):
    monkeypatch.setattr(main, "_fetch_catalog_sync", lambda: ([], None, "network unavailable"))
    main._cache.update({"at": 0, "rows": [], "source": None, "error": None})
    result = run(main.get_catalog(refresh=True))
    assert result["rows"]
    assert any(row["id"] == "auto|auto" for row in result["rows"])
    assert result["error"]


def test_catalog_and_models_exclude_router_aliases(monkeypatch):
    rows = main.parse_working_results(
        "ProviderA|model-a|text\nKiloCode|openrouter/free|text\nProviderB|flux-dev|image"
    )
    monkeypatch.setattr(main, "_fetch_catalog_sync", lambda: (rows, "https://example.org/working.txt", None))
    main._cache.update({"at": 0, "rows": [], "source": None, "error": None})
    result = run(main.catalog(refresh=True))
    assert all("openrouter" not in row["id"].lower() for row in result["rows"])
    model_result = run(main.models())
    body = model_result
    assert any(entry["id"] == "auto" for entry in body["data"])
    assert not any("openrouter" in entry["id"].lower() for entry in body["data"])


def test_chat_response_shape_with_stubbed_provider(monkeypatch):
    async def fake_generate(model, messages, temperature, max_tokens):
        assert messages[-1]["content"] == "hello"
        return "hi there", "model-x", "ProviderX", []
    monkeypatch.setattr(main, "_generate_chat", fake_generate)
    req = main.ChatRequest(model="auto", messages=[main.Message(role="user", content="hello")])
    response = run(main.chat_completions(req, None))
    body = json.loads(response.body.decode())
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hi there"
    assert body["model"] == "ProviderX|model-x"


def test_chat_sse_has_done_marker(monkeypatch):
    async def fake_generate(model, messages, temperature, max_tokens):
        return "stream mock", "model-x", None, []
    monkeypatch.setattr(main, "_generate_chat", fake_generate)
    req = main.ChatRequest(model="auto", messages=[main.Message(role="user", content="hello")], stream=True)
    response = run(main.chat_completions(req, None))
    assert response.media_type == "text/event-stream"
    async def consume():
        output = []
        async for part in response.body_iterator:
            output.append(part.decode() if isinstance(part, bytes) else part)
        return "".join(output)
    text = run(consume())
    assert "stream mock" in text
    assert "data: [DONE]" in text


def test_optional_token_allows_unprotected_mode(monkeypatch):
    monkeypatch.delenv("API_ACCESS_TOKEN", raising=False)
    assert run(main.require_access_token(None)) is None


def test_configured_token_is_enforced(monkeypatch):
    monkeypatch.setenv("API_ACCESS_TOKEN", "unit-test-secret")
    try:
        run(main.require_access_token(None))
        assert False, "should reject missing token"
    except HTTPException as exc:
        assert exc.status_code == 401
    assert run(main.require_access_token("Bearer unit-test-secret")) is None


def test_image_endpoint_returns_real_image_result_only(monkeypatch):
    async def fake_image(req):
        return {"image": {"url": "https://images.example.org/real.png"}, "model": "flux-test", "attempts": 0}
    monkeypatch.setattr(main, "_generate_image", fake_image)
    req = main.ImageRequest(prompt="blue flower")
    body = run(main.image_generate(req, None))
    assert body["data"][0]["url"].endswith("real.png")
    assert body["model"] == "flux-test"


def test_video_returns_503_when_no_keyless_video_provider(monkeypatch):
    async def no_video(refresh=False):
        return {"at": 1.0, "rows": [{"id": "P|text-model", "provider": "P", "model": "text-model", "type": "text"}], "source": "mock", "error": None}
    monkeypatch.setattr(main, "get_catalog", no_video)
    req = main.VideoRequest(prompt="cinematic mountain")
    try:
        run(main.video_generate(req, None))
        assert False, "video must not claim success without a real provider"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["fake_media"] is False


def test_model_and_prompt_validation():
    try:
        main.ImageRequest(prompt="")
        assert False, "empty image prompt should fail validation"
    except Exception:
        pass
    try:
        main.VideoRequest(prompt="a video", aspect_ratio="5:5")
        assert False, "unsupported aspect ratio should fail validation"
    except Exception:
        pass


def test_model_candidates_reject_router_aliases():
    try:
        main._model_candidates("openrouter/free", [])
        assert False, "router aliases should be blocked"
    except HTTPException as exc:
        assert exc.status_code == 400



def test_model_candidates_returns_only_requested_route():
    rows = [
        {"type": "text", "verified_by": "g4f-working", "provider": "Cloudflare", "model": "model-a"},
        {"type": "text", "verified_by": "g4f-working", "provider": "DeepSeek", "model": "model-b"},
    ]
    assert main._model_candidates("Cloudflare|model-a", rows) == [("model-a", "Cloudflare")]
    assert main._model_candidates("DeepSeek|model-b", rows) == [("model-b", "DeepSeek")]
    assert main._model_candidates("gemini-2.5-flash", rows) == [("gemini-2.5-flash", None)]
    assert main._model_candidates("auto", rows) == [("auto", None)]


def test_failed_requested_model_does_not_fallback(monkeypatch):
    async def fake_catalog():
        return {"rows": [
            {"type": "text", "verified_by": "g4f-working", "provider": "Cloudflare", "model": "model-a"},
            {"type": "text", "verified_by": "g4f-working", "provider": "DeepSeek", "model": "model-b"},
        ]}
    async def fail_once(*args, **kwargs):
        raise RuntimeError("selected model offline")
    monkeypatch.setattr(main, "_run_g4f_thread", fail_once)
    try:
        run(main._generate_chat("Cloudflare|model-a", [{"role": "user", "content": "hello"}], 0.7, 100))
        assert False, "expected selected route failure"
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail["requested_model"] == "Cloudflare|model-a"
        assert exc.detail["fallback_used"] is False
        assert "No other model was tried" in exc.detail["message"]



def test_catalog_contains_requested_providers_and_explicit_routes(monkeypatch):
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "META_MODEL_API_KEY", "MODEL_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(main, "_fetch_catalog_sync", lambda: ([], None, "network unavailable"))
    main._cache.update({"at": 0, "rows": [], "source": None, "error": None})
    data = run(main.catalog(refresh=True))
    ids = {row["id"] for row in data["rows"]}
    assert "OpenAI API|gpt-6-astra" in ids
    assert "Gemini API|gemini-3.8-flash" in ids
    assert "Claude API|claude-sonnet-4-6" in ids
    assert "xAI Grok API|grok-4.7" in ids
    assert "Meta Model API|muse-spark" in ids
    assert "DeepSeek API|deepseek-chat" in ids
    assert "Perplexity API|sonar-pro" in ids
    assert "Ollama Local|llama3.3" in ids
    assert "g4f:ChatGPT|gpt-4o" in ids


def test_official_missing_key_returns_error_and_never_falls_back(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    try:
        run(main._generate_chat("Gemini API|gemini-3.8-flash", [{"role": "user", "content": "hi"}], 0.7, 100))
        assert False, "missing Gemini key should fail before calling any provider"
    except HTTPException as exc:
        assert exc.status_code == 424
        assert exc.detail["error"] == "provider_credentials_missing"
        assert exc.detail["fallback_used"] is False
        assert "no other provider was tried" in exc.detail["message"].lower()


def test_official_route_calls_only_the_requested_provider(monkeypatch):
    calls = []
    async def fake_run(fn, *args, timeout):
        calls.append((fn.__name__, args))
        return "answer from selected provider"
    monkeypatch.setattr(main, "_run_g4f_thread", fake_run)
    async def go():
        return await main._generate_chat("Gemini API|gemini-3.8-flash", [{"role": "user", "content": "hi"}], 0.4, 120)
    result = run(go())
    assert result[0] == "answer from selected provider"
    assert result[1] == "gemini-3.8-flash"
    assert result[2] == "Gemini API"
    assert len(calls) == 1
    assert calls[0][0] == "call_official_chat"
    assert calls[0][1][0] == "Gemini API"


def test_requested_g4f_catalog_rows_are_namespaced_explicitly():
    rows = main.parse_working_results("Gemini|gemini-2.5-flash|text")
    assert len(rows) == 1
    assert rows[0]["id"] == "g4f:Gemini|gemini-2.5-flash"
    assert rows[0]["route_kind"] == "g4f_community"



def test_provider_catalog_live_list_filters_non_chat_models(monkeypatch):
    import provider_catalog
    class FakeResponse:
        ok = True
        def json(self):
            return {"data": [
                {"id": "gpt-6-astra"}, {"id": "text-embedding-3-small"},
                {"id": "gpt-image-2"}, {"id": "gpt-5.5"}, {"id": "whisper-1"},
            ]}
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-test-key")
    monkeypatch.setattr(provider_catalog.requests, "get", lambda *args, **kwargs: FakeResponse())
    assert provider_catalog._live_model_ids("OpenAI API") == ["gpt-5.5", "gpt-6-astra"]
