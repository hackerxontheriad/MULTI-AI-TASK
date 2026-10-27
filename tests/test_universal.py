"""MADX v18 integration tests: direct adapters, single-route execution and safe UI surfaces."""
import asyncio
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import project_builder
import static_re


def run(coro):
    return asyncio.run(coro)


def test_health_payload_is_low_information_and_uses_supported_adapters_only():
    payload = main._health_info()
    assert payload["status"] == "ok"
    assert payload["provider_adapters"] == "supported_api_routes_only"
    assert payload["official_provider_count"] >= 10
    assert "configured_provider_count" in payload
    assert not any(k.lower().endswith("key") for k in payload)
    assert not any("/mnt/" in str(v) or "sk-" in str(v) for v in payload.values())


def test_root_is_a_file_response():
    response = run(main.home())
    assert str(response.path).endswith("index.html")


def test_catalog_has_auto_and_only_supported_direct_routes(monkeypatch):
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "META_MODEL_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    main._cache.update({"at": 0, "rows": [], "source": None, "error": None})
    data = run(main.catalog(refresh=True))
    ids = {row["id"] for row in data["rows"]}
    assert "auto|auto" in ids
    assert any(x.startswith("Groq API|") for x in ids)
    assert any(x.startswith("Gemini API|") for x in ids)
    assert any(x.startswith("OpenAI API|") for x in ids)
    assert not any(x.lower().startswith("g4f:") for x in ids)
    assert not any("openrouter/free" in x.lower() for x in ids)


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


def test_identity_question_returns_only_madx_without_calling_a_provider(monkeypatch):
    async def must_not_call(*args, **kwargs):
        raise AssertionError("identity responses should be deterministic")
    monkeypatch.setattr(main, "_generate_chat", must_not_call)
    req = main.ChatRequest(model="Gemini API|gemini-3.8-flash", messages=[main.Message(role="user", content="Who are you?")])
    response = run(main.chat_completions(req, None))
    body = json.loads(response.body.decode())
    assert body["choices"][0]["message"]["content"] == "MADX"
    assert body["model"] == "MADX|identity"


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
    assert "stream mock" in text and "data: [DONE]" in text


def test_optional_access_token_and_enforced_token(monkeypatch):
    monkeypatch.delenv("API_ACCESS_TOKEN", raising=False)
    assert run(main.require_access_token(None)) is None
    monkeypatch.setenv("API_ACCESS_TOKEN", "unit-test-secret")
    with pytest.raises(HTTPException) as info:
        run(main.require_access_token(None))
    assert info.value.status_code == 401
    assert run(main.require_access_token("Bearer unit-test-secret")) is None


def test_image_endpoint_returns_real_image_result_only(monkeypatch):
    async def fake_image(req):
        return {"image": {"url": "https://images.example.org/real.png"}, "model": "flux-test", "attempts": 1}
    monkeypatch.setattr(main, "_generate_image", fake_image)
    body = run(main.image_generate(main.ImageRequest(prompt="blue flower"), None))
    assert body["data"][0]["url"].endswith("real.png")
    assert body["model"] == "flux-test"


def test_video_returns_503_when_no_video_provider(monkeypatch):
    async def no_video(refresh=False):
        return {"at": 1.0, "rows": [{"id": "P|text-model", "provider": "P", "model": "text-model", "type": "text"}], "source": "mock", "error": None}
    monkeypatch.setattr(main, "get_catalog", no_video)
    with pytest.raises(HTTPException) as info:
        run(main.video_generate(main.VideoRequest(prompt="cinematic mountain"), None))
    assert info.value.status_code == 503 and info.value.detail["fake_media"] is False


def test_model_and_prompt_validation():
    with pytest.raises(Exception):
        main.ImageRequest(prompt="")
    with pytest.raises(Exception):
        main.VideoRequest(prompt="a video", aspect_ratio="5:5")


def test_model_candidates_block_router_aliases_and_legacy_wrappers():
    with pytest.raises(HTTPException) as info:
        main._model_candidates("openrouter/free", [])
    assert info.value.status_code == 400
    with pytest.raises(HTTPException) as info:
        main._model_candidates("g4f: Gemini API|gemini-3.8-flash", [])
    assert info.value.status_code == 410
    assert info.value.detail["error"] == "unofficial_adapter_removed"


def test_model_candidates_are_exact_and_auto_must_resolve():
    assert main._model_candidates("Gemini API|gemini-3.8-flash", []) == [("gemini-3.8-flash", "Gemini API")]
    with pytest.raises(HTTPException) as info:
        main._model_candidates("UnknownProvider|model-a", [])
    assert info.value.status_code == 400
    with pytest.raises(HTTPException) as info:
        main._model_candidates("auto", [])
    assert info.value.detail["error"] == "auto_route_not_resolved"


def test_failed_requested_model_does_not_fallback(monkeypatch):
    async def fail_once(*args, **kwargs):
        raise RuntimeError("selected model offline")
    monkeypatch.setattr(main, "_run_official_thread", fail_once)
    with pytest.raises(HTTPException) as info:
        run(main._generate_chat("Gemini API|gemini-3.8-flash", [{"role": "user", "content": "hello"}], 0.7, 100))
    assert info.value.status_code == 502
    assert info.value.detail["requested_model"] == "Gemini API|gemini-3.8-flash"
    assert info.value.detail["fallback_used"] is False
    assert "No other model was tried" in info.value.detail["message"]


def test_catalog_contains_named_provider_routes_without_wrapper_aliases(monkeypatch):
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "META_MODEL_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    main._cache.update({"at": 0, "rows": [], "source": None, "error": None})
    data = run(main.catalog(refresh=True))
    ids = {row["id"] for row in data["rows"]}
    for expected in (
        "OpenAI API|gpt-6-astra", "Gemini API|gemini-3.8-flash", "Claude API|claude-sonnet-4-6",
        "xAI Grok API|grok-4.7", "Meta Model API|muse-spark", "DeepSeek API|deepseek-chat",
        "Perplexity API|sonar-pro", "Ollama Local|llama3.3", "Groq API|llama-3.3-70b-versatile",
        "Cerebras API|gpt-oss-120b", "Mistral API|mistral-small-latest",
        "GitHub Models|openai/gpt-4.1-mini", "Hugging Face API|meta-llama/Llama-3.3-70B-Instruct",
        "Cloudflare Workers AI|@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    ):
        assert expected in ids, expected
    assert not any(x.lower().startswith("g4f:") for x in ids)
    assert data["free_route_count"] >= 8


def test_missing_provider_key_returns_424_and_never_falls_back(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(HTTPException) as info:
        run(main._generate_chat("Gemini API|gemini-3.8-flash", [{"role": "user", "content": "hi"}], 0.7, 100))
    assert info.value.status_code == 424
    assert info.value.detail["error"] == "provider_credentials_missing"
    assert info.value.detail["fallback_used"] is False


def test_official_route_calls_only_selected_provider(monkeypatch):
    calls = []
    async def fake_run(fn, *args, timeout):
        calls.append((fn.__name__, args))
        return "answer from selected provider"
    monkeypatch.setattr(main, "_run_official_thread", fake_run)
    result = run(main._generate_chat("Gemini API|gemini-3.8-flash", [{"role": "user", "content": "hi"}], 0.4, 120))
    assert result[0] == "answer from selected provider"
    assert result[1:3] == ("gemini-3.8-flash", "Gemini API")
    assert len(calls) == 1 and calls[0][0] == "call_official_chat"
    assert calls[0][1][0] == "Gemini API"


def test_project_builder_blocks_traversal_secrets_and_duplicates():
    assert project_builder.safe_relative_path("./src/index.html") == "src/index.html"
    for bad in ("../outside.txt", "/etc/passwd", "C:\\windows\\system.ini", ".env", "secrets.json"):
        with pytest.raises(project_builder.ProjectOutputError):
            project_builder.safe_relative_path(bad)
    with pytest.raises(project_builder.ProjectOutputError):
        project_builder.normalize_files([{"path": "a.txt", "content": "1"}, {"path": "a.txt", "content": "2"}])


def test_project_builder_makes_safe_zip(tmp_path):
    blob = project_builder.make_zip({"index.html": b"<h1>MADX</h1>", "src/main.js": b"console.log('ok')"}, "cafe-demo")
    file = tmp_path / "project.zip"
    file.write_bytes(blob)
    assert zipfile.is_zipfile(file)
    with zipfile.ZipFile(file) as zf:
        assert "cafe-demo/index.html" in zf.namelist()
        assert "cafe-demo/src/main.js" in zf.namelist()


def test_project_foundry_end_to_end_persists_tasks_and_downloads_zip(monkeypatch):
    monkeypatch.setenv("API_ACCESS_TOKEN", "test-app-access-token")
    monkeypatch.setenv("REQUIRE_LOGIN", "true")

    async def fake_generate(model, messages, temperature, max_tokens):
        system = str(messages[0].get("content", "")) if messages else ""
        if system.startswith("You plan software deliverables"):
            return json.dumps({
                "project_name": "Cafe QR Menu",
                "summary": "Minimal static menu with a QR code entry point.",
                "tasks": [{
                    "title": "Implement static menu",
                    "role": "Frontend",
                    "files": ["index.html"],
                    "prompt": "Create a responsive static cafe menu page with accessible menu sections and a QR-ready URL.",
                }],
            }), "gemini-3.8-flash", "Gemini API", []
        return json.dumps({"files": [{"path": "index.html", "content": "<!doctype html><title>MADX Cafe</title><h1>Cafe menu</h1>"}], "notes": "Static HTML generated."}), "gemini-3.8-flash", "Gemini API", []

    monkeypatch.setattr(main, "_generate_chat", fake_generate)
    client = TestClient(main.app, base_url="https://testserver")
    client.get("/")  # establish a separate browser owner cookie
    response = client.post("/api/projects/build", headers={"Authorization": "Bearer test-app-access-token"}, json={
        "project_name": "Cafe QR Menu",
        "prompt": "Create a static café menu website ZIP with a QR-ready menu entry page.",
        "planner_model": "Gemini API|gemini-3.8-flash",
        "worker_models": ["Gemini API|gemini-3.8-flash"],
        "max_tasks": 1,
        "worker_max_tokens": 1200,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed"
    assert result["file_count"] == 1
    assert result["tasks"][0]["status"] == "completed"
    assert result["assignments"][0]["work_prompt"]
    download = client.get(result["download_url"], headers={"Authorization": "Bearer test-app-access-token"})
    assert download.status_code == 200
    import io
    with zipfile.ZipFile(io.BytesIO(download.content)) as zf:
        assert "Cafe-QR-Menu/index.html" in zf.namelist()
        assert b"MADX Cafe" in zf.read("Cafe-QR-Menu/index.html")


def test_static_reverse_audit_never_executes_archive(tmp_path):
    archive = tmp_path / "review.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("app.py", "import subprocess\nsubprocess.run('echo hi', shell=True)\nAPI_KEY='sk-abcdefghijklmnop'\n")
        zf.writestr("../escape.txt", "bad")
    report = static_re.audit_archive(str(archive))
    types = {x["type"] for x in report["findings"]}
    assert "unsafe_archive_path" in types
    assert "possible_secret" in types
    assert "shell_execution_review" in types
    assert "No files were extracted or executed" in report["warning"]


def test_public_ui_exposes_auth_builder_reverse_but_not_diagnostics(monkeypatch):
    client = TestClient(main.app)
    for path in ("/", "/auth", "/builder", "/reverse"):
        assert client.get(path).status_code == 200, path
    assert client.get("/diagnostics").status_code == 404
    assert client.get("/static/diagnostics.html").status_code == 404
    assert client.get("/v1/diagnostics").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    health = client.get("/health").json()
    assert "database_path" not in health and "provider_keys" not in health


def test_admin_query_token_becomes_short_lived_cookie_and_is_removed_from_url(monkeypatch):
    monkeypatch.setenv("ADMIN_ACCESS_TOKEN", "A" * 48)
    monkeypatch.setattr(main, "COOKIE_SECURE", False)
    client = TestClient(main.app, base_url="http://testserver")
    response = client.get("/admin", params={"token": "A" * 48}, follow_redirects=False)
    assert response.status_code in (302, 303)
    assert "token=" not in response.headers.get("location", "")
    assert "madx_admin" in response.headers.get("set-cookie", "")
    assert client.get("/admin").status_code == 200
    assert client.get("/api/admin/overview").status_code == 200
    assert client.post("/api/admin/terminal", json={"command": "help"}).status_code == 200
    assert client.post("/api/admin/terminal", json={"command": "cat .env"}).status_code in (400, 403)


def test_admin_dashboard_is_not_accessible_without_unlock(monkeypatch):
    monkeypatch.setenv("ADMIN_ACCESS_TOKEN", "B" * 48)
    client = TestClient(main.app, base_url="http://testserver")
    assert client.get("/admin").status_code == 404
    assert client.get("/api/admin/overview").status_code in (401, 404)


def test_storage_owners_are_not_shared_by_the_common_api_token():
    from types import SimpleNamespace
    request_a = SimpleNamespace(
        cookies={"madx_anon_id": "A" * 43},
        headers={"user-agent": "MADX mobile"},
        client=SimpleNamespace(host="203.0.113.10"),
        method="GET",
    )
    request_b = SimpleNamespace(
        cookies={"madx_anon_id": "B" * 43},
        headers={"user-agent": "MADX mobile"},
        client=SimpleNamespace(host="203.0.113.10"),
        method="GET",
    )
    assert main._owner_subject(request_a) != main._owner_subject(request_b)
    assert main._upload_owner(request_a) != main._upload_owner(request_b)
