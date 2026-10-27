from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

import main


def _client(monkeypatch):
    monkeypatch.delenv("API_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("REQUIRE_LOGIN", "false")
    monkeypatch.delenv("DIAGNOSTICS_PASSWORD", raising=False)
    return TestClient(main.app)


def test_hybrid_pages_security_headers_docs_and_diagnostics_hidden(monkeypatch):
    client = _client(monkeypatch)
    for path in ("/", "/chat", "/agents", "/studio", "/files", "/settings"):
        response = client.get(path)
        assert response.status_code == 200
        assert "MAD X" in response.text
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/v1/diagnostics").status_code == 404


def test_upload_accepts_arbitrary_bytes_and_scopes_library(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    payload = b"\x00\x01binary\xffpayload"
    response = client.post(
        "/v1/files/upload",
        content=payload,
        headers={"X-File-Name": "%2e%2e%2Fhello.bin", "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    meta = response.json()
    assert meta["name"] == "hello.bin"
    assert meta["size"] == len(payload)
    assert len(meta["sha256"]) == 64
    listed = client.get("/v1/files")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    download = client.get(meta["download_url"])
    assert download.status_code == 200
    assert download.content == payload
    assert download.headers.get("x-content-type-options") == "nosniff"
    deleted = client.delete(f"/v1/files/{meta['id']}")
    assert deleted.status_code == 200
    assert client.get("/v1/files").json()["count"] == 0


def test_six_agent_pipeline_uses_explicit_free_fallback_and_reports_it(monkeypatch):
    client = _client(monkeypatch)
    primary = "Groq API|llama-3.3-70b-versatile"
    free = "Gemini API|gemini-2.5-flash"
    async def fallback_route(exclude_routes=None):
        return None if exclude_routes and free in exclude_routes else free
    async def configured(route):
        return route == free
    async def fake_generate(route, messages, temperature, max_tokens):
        if route == primary:
            raise HTTPException(status_code=502, detail={"error": "test_primary_failure", "message": "mock outage"})
        assert route == free
        return ("mocked free response", "gemini-2.5-flash", "Gemini API", [])
    monkeypatch.setattr(main, "_free_fallback_route", fallback_route)
    monkeypatch.setattr(main, "_is_configured_free_route", configured)
    monkeypatch.setattr(main, "_generate_chat", fake_generate)
    response = client.post("/v1/tasks/run", json={
        "task": "Build a secure sample endpoint with tests.",
        "routes": [primary],
        "fallback_route": free,
        "temperature": 0.2,
        "max_tokens": 300,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "six_agent_task_pipeline"
    assert data["agents_expected"] == 6
    assert data["agents_completed"] == 6
    assert data["fallback_route"] == free
    assert data["fallbacks_used"] == 6
    assert data["final"] == "mocked free response"
    assert "PROFESSIONAL TASK BRIEF" in data["professional_prompt"]
    assert all(agent["ok"] for agent in data["agents"])
    assert all(agent["fallback_used"] for agent in data["agents"])


def test_diagnostics_require_admin_session(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("ADMIN_ACCESS_TOKEN", "D" * 48)
    monkeypatch.setattr(main, "COOKIE_SECURE", False)
    response = client.get("/v1/diagnostics", params={"probe": "false"})
    assert response.status_code == 404
    unlocked = client.get("/admin", params={"token": "D" * 48}, follow_redirects=False)
    assert unlocked.status_code in (302, 303)
    assert client.get("/api/admin/diagnostics").status_code == 200


def test_public_health_is_minimal_and_catalog_requires_login(monkeypatch):
    monkeypatch.delenv("API_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("REQUIRE_LOGIN", "true")
    monkeypatch.delenv("DIAGNOSTICS_PASSWORD", raising=False)
    client = TestClient(main.app)
    health = client.get("/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert "max_upload_mb" in payload
    assert "configured_providers" not in payload
    assert "chromium_path" not in payload
    assert client.get("/v1/catalog").status_code == 401
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/status").status_code == 404


def test_ported_task_planner_returns_a_non_execution_plan(monkeypatch):
    client = _client(monkeypatch)
    response = client.post("/api/agents/plan", json={
        "task": "Create an Android APK build workflow and test the code",
        "requested_agent": "general",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["agent"] == "coding"
    assert "professional_prompt" in data
    assert "does not call a model" in data["note"]


def test_v18_landing_assets_and_robots_are_served(monkeypatch):
    client = _client(monkeypatch)
    landing = client.get("/")
    assert landing.status_code == 200
    assert "Build beyond" in landing.text
    assert "/static/assets/logo-mark.svg" in landing.text
    assert "/static/assets/mad-x-logo.svg" in landing.text
    assert "/static/assets/logo-demo.mp4" in landing.text
    assert client.get("/static/assets/logo-demo.mp4").status_code == 200
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Disallow: /api/" in robots.text
    diagnostics = client.get("/diagnostics")
    assert diagnostics.status_code == 404
    assert client.get("/auth").status_code == 200
    assert client.get("/builder").status_code == 200
    assert client.get("/reverse").status_code == 200
    assert client.get("/health").json()["version"] == "18.0.0"


def test_gateway_adapters_require_both_url_and_key(monkeypatch):
    import provider_catalog as pc
    for name, url_env, key_env in (
        ("OmniRoute Gateway", "OMNIROUTE_BASE_URL", "OMNIROUTE_API_KEY"),
        ("9Router Compatible Gateway", "NINE_ROUTER_BASE_URL", "NINE_ROUTER_API_KEY"),
        ("New-API Compatible Gateway", "NEW_API_BASE_URL", "NEW_API_API_KEY"),
        ("One-API Compatible Gateway", "ONE_API_BASE_URL", "ONE_API_API_KEY"),
    ):
        monkeypatch.delenv(url_env, raising=False)
        monkeypatch.delenv(key_env, raising=False)
        assert not pc.key_is_configured(name)
        monkeypatch.setenv(url_env, "https://gateway.example/v1")
        assert not pc.key_is_configured(name)
        monkeypatch.setenv(key_env, "test-only-not-a-real-secret")
        assert pc.key_is_configured(name)


def test_connector_status_requires_auth_in_hosted_mode_and_redacts_secrets(monkeypatch):
    monkeypatch.setenv("REQUIRE_LOGIN", "true")
    monkeypatch.setenv("API_ACCESS_TOKEN", "test-only-access-secret")
    monkeypatch.delenv("DIAGNOSTICS_PASSWORD", raising=False)
    client = TestClient(main.app)
    assert client.get("/api/connectors/status?probe=false").status_code == 401
    response = client.get("/api/connectors/status?probe=false", headers={
        "Authorization": "Bearer test-only-access-secret"
    })
    assert response.status_code == 200, response.text
    assert "test-only-access-secret" not in response.text
    assert "OmniRoute Gateway" in response.text
    assert response.json()["note"].startswith("Configured is not the same as verified working.")
