"""MadEx Universal AI & Media API Server.

Google credentials are exchanged for an encrypted, HttpOnly session cookie.
Chat uses community-maintained free-provider adapters through g4f. These providers
are not guaranteed and may be rate-limited or unavailable; hosting limits still apply.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote, unquote

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    google_requests = None
    id_token = None
    GOOGLE_AUTH_AVAILABLE = False
from pydantic import BaseModel, Field

import provider_gateway as gateway  # merged provider catalog, HTTP adapters, agents and diagnostics

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "").rstrip("/")
COOKIE_NAME = "madex_session"
SESSION_DAYS = max(1, min(int(os.getenv("SESSION_DAYS", "30")), 30))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}
FERNET_KEY = os.getenv("SESSION_ENCRYPTION_KEY", "").strip()

app = FastAPI(title="MadEx Universal AI & Media API Server", version="1.1.0", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    response.headers.setdefault("Cache-Control", "no-store")
    if COOKIE_SECURE:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def session_cipher() -> Fernet:
    if not FERNET_KEY:
        raise HTTPException(status_code=503, detail="Server session encryption is not configured.")
    try:
        return Fernet(FERNET_KEY.encode())
    except Exception:
        raise HTTPException(status_code=503, detail="Server session encryption key is invalid.")


def issue_session(response: Response, user: dict) -> None:
    payload = json.dumps({"sub": user["id"], "email": user.get("email", ""), "name": user.get("name", "")}, separators=(",", ":")).encode()
    token = session_cipher().encrypt(payload).decode()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=COOKIE_SECURE, samesite="lax", path="/")


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in with Google to continue.")
    try:
        payload = session_cipher().decrypt(token.encode())
        user = json.loads(payload)
        if not user.get("sub"):
            raise ValueError("missing subject")
        return user
    except (InvalidToken, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Session is invalid. Please sign in again.")


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=30, max_length=10000)

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=30000)

class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=80)
    model: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = True

class VideoRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    drive_access_token: Optional[str] = Field(default=None, max_length=10000)
    aspect_ratio: str = Field(default="16:9", pattern=r"^(16:9|9:16|1:1)$")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "landing.html")

@app.get("/terms")
def terms_page():
    return FileResponse(STATIC_DIR / "terms.html")

@app.get("/privacy")
def privacy_page():
    return FileResponse(STATIC_DIR / "privacy.html")

@app.get("/chat")
def chat_page():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/config.js")
def config_js():
    # Google Client IDs are public identifiers, not secrets.
    safe_id = json.dumps(GOOGLE_CLIENT_ID)
    return Response(f"window.MADX_CONFIG = {{ googleClientId: {safe_id} }};", media_type="application/javascript", headers={"Cache-Control": "no-store"})

@app.post("/api/agents/plan")
async def agents_plan(body: dict, request: Request):
    current_user(request)
    from agent_router import plan_task
    task = str(body.get("task", "")).strip()
    if not task or len(task) > 12000:
        raise HTTPException(status_code=400, detail="Provide a task between 1 and 12000 characters.")
    requested_agent = str(body.get("agent", "general")).strip().lower()
    return plan_task(task, requested_agent)

@app.get("/health")
def health():
    return {"status": "ok", "service": "MadEx Universal AI & Media API Server", "chat_provider": "hybrid multi-provider gateway with configured-route fallback", "api_key_required": False, "browser_automation": "Chromium diagnostics available; Google Flow generation is not implemented"}

@app.post("/api/auth/google")
def google_login(body: GoogleCredential, response: Response):
    if not GOOGLE_AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Google authentication libraries are not installed. Install requirements.txt and redeploy.")
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on the server.")
    try:
        claims = id_token.verify_oauth2_token(body.credential, google_requests.Request(), GOOGLE_CLIENT_ID)
        if not claims.get("sub") or claims.get("email_verified") is not True:
            raise ValueError("Unverified Google account")
        user = {"id": claims["sub"], "email": claims.get("email", ""), "name": claims.get("name", "")}
        issue_session(response, user)
        response.headers["Cache-Control"] = "no-store"
        return {"user": {"id": user["id"], "email": user["email"], "name": user["name"]}}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Google credential is invalid or expired. Please try again.")

@app.get("/api/me")
def me(request: Request):
    user = current_user(request)
    return {"id": user["sub"], "email": user.get("email", ""), "name": user.get("name", "")}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return {"ok": True}

# No paid provider API key is required. g4f uses community-maintained provider
# adapters; availability can change and providers may rate-limit or block hosting IPs.
MODEL_MAPPING = {
    "chatgpt": "gpt-4o",
    "gemini": "gemini-pro",
    "deepseek": "deepseek-v3",
    "meta": "llama-3-70b",
    "claude": "claude-3-5-sonnet",
    "grok": "grok-2",
    "perplexity": "sonar",
    "x1-lite-pro-flash": "gemini-2.0-flash",
}

@app.get("/api/models")
def api_models(request: Request):
    current_user(request)
    labels = {"chatgpt":"C", "gemini":"G", "deepseek":"D", "meta":"M", "claude":"C", "grok":"X", "perplexity":"P", "x1-lite-pro-flash":"X1 Lite Pro Flash"}
    return {"data": [{"id": key, "provider": "community adapter (availability varies)", "label": labels.get(key, key[:1].upper())} for key in MODEL_MAPPING]}

async def g4f_stream(messages: list[dict], requested_model: Optional[str], temperature: float):
    """Yield OpenAI-compatible SSE chunks from keyless community providers.

    This is not an official or guaranteed free API. It tries the requested mapped
    model and then g4f's default model if the first provider fails before output.
    """
    try:
        import g4f
    except Exception:
        yield "data: " + json.dumps({"error": {"message": "Free AI adapter is not installed. Redeploy after installing requirements."}}) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    model_key = (requested_model or "chatgpt").lower().strip()
    preferred = MODEL_MAPPING.get(model_key, model_key)
    candidates = [preferred]
    # Try a different configured alias before the library default; providers/models are not guaranteed.
    for fallback_key in ("gemini", "grok", "deepseek"):
        fallback_model = MODEL_MAPPING[fallback_key]
        if fallback_model not in candidates:
            candidates.append(fallback_model)
    try:
        default_model = getattr(g4f.models, "default", None)
        if default_model is not None and default_model not in candidates:
            candidates.append(default_model)
    except Exception:
        pass

    for candidate_index, model in enumerate(candidates):
        emitted = False
        try:
            result = await g4f.ChatCompletion.create_async(
                model=model,
                messages=messages,
                stream=True,
                temperature=temperature,
            )
            if hasattr(result, "__aiter__"):
                async for piece in result:
                    if not piece:
                        continue
                    emitted = True
                    chunk = {"id": "chatcmpl-madex", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": str(piece)}, "finish_reason": None}]}
                    yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
            else:
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, str) and result:
                    emitted = True
                    for offset in range(0, len(result), 48):
                        chunk = {"id": "chatcmpl-madex", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": result[offset:offset+48]}, "finish_reason": None}]}
                        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
            if emitted:
                yield "data: " + json.dumps({"id": "chatcmpl-madex", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
                yield "data: [DONE]\n\n"
                return
            raise RuntimeError("Provider returned an empty response")
        except Exception as exc:
            # Log server-side diagnostics without exposing tokens or internal details to the browser.
            print(f"[madex-chat] model={model!s} failed: {type(exc).__name__}: {str(exc)[:240]}", flush=True)
            if emitted or candidate_index == len(candidates) - 1:
                yield "data: " + json.dumps({"error": {"message": "All configured community AI routes failed before a response. Check Render logs for the provider error, then retry or switch model."}}) + "\n\n"
                yield "data: [DONE]\n\n"
                return
            # Try the fallback only when no text was sent, to avoid duplicating output.
            continue

@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatRequest, request: Request):
    return await hybrid_chat_stream(req, request)

@app.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request):
    current_user(request)
    chunks = []
    async for event in g4f_stream([m.model_dump() for m in req.messages], req.model, req.temperature):
        if not event.startswith("data: "):
            continue
        raw = event[6:].strip()
        if raw == "[DONE]":
            break
        try:
            data = json.loads(raw)
            if data.get("error"):
                raise HTTPException(status_code=502, detail=data["error"]["message"])
            chunks.append(data.get("choices", [{}])[0].get("delta", {}).get("content", ""))
        except json.JSONDecodeError:
            continue
    answer = "".join(chunks)
    if not answer:
        raise HTTPException(status_code=502, detail="Free AI provider did not return a response. Please retry.")
    return {"id": "madex-chat", "model": req.model or "chatgpt", "message": answer}

@app.get("/v1/models")
def openai_models(request: Request):
    current_user(request)
    return {"object": "list", "data": [{"id": key, "object": "model", "owned_by": "community-provider"} for key in MODEL_MAPPING]}

@app.post("/v1/chat/completions")
async def openai_chat(req: ChatRequest, request: Request):
    current_user(request)
    if req.stream:
        return StreamingResponse(g4f_stream([m.model_dump() for m in req.messages], req.model, req.temperature), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
    return await api_chat(req, request)


AGENT_TEAM = [
    {"id":"planner", "name":"Planner", "role":"Decompose the task into concrete deliverables, dependencies, and acceptance criteria."},
    {"id":"researcher", "name":"Researcher", "role":"Identify facts that need verification, likely approaches, risks, and unknowns. Never invent research."},
    {"id":"builder", "name":"Builder", "role":"Propose the implementation or concrete solution with actionable details."},
    {"id":"reviewer", "name":"Reviewer", "role":"Critique the proposed solution for correctness, missing requirements, security, and edge cases."},
    {"id":"optimizer", "name":"Optimizer", "role":"Improve simplicity, speed, accessibility, maintainability, and cost."},
    {"id":"tester", "name":"Tester", "role":"Create a verification checklist and distinguish tests actually run from tests merely recommended."},
]

class TeamTask(BaseModel):
    task: str = Field(min_length=1, max_length=12000)
    power: Literal["low", "medium", "fast"] = "medium"
    model: str = "x1-lite-pro-flash"

async def _agent_completion(prompt: str, role: str, model_key: str, timeout_s: float = 55) -> str:
    import asyncio
    import g4f
    model = MODEL_MAPPING.get(model_key, MODEL_MAPPING["gemini"])
    messages = [
        {"role":"system", "content":"You are a specialist agent inside MadEx AI. Be concrete, honest about uncertainty, and do not claim tools/tests were run unless they were."},
        {"role":"user", "content":f"TASK: {prompt}\n\nYOUR SPECIALIST ROLE: {role}\nReturn a concise, useful result with assumptions and risks."},
    ]
    async def run():
        result = await g4f.ChatCompletion.create_async(model=model, messages=messages, stream=False, temperature=0.3)
        if isinstance(result, str): return result.strip()
        if isinstance(result, dict): return str(result.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
        return str(result).strip()
    return await asyncio.wait_for(run(), timeout=timeout_s)

@app.get("/api/agents")
def list_agents(request: Request):
    current_user(request)
    return {"agents": AGENT_TEAM, "video_agent": {"name":"Flow Media Agent", "status":"experimental; real generation requires authenticated supported Flow session"}, "backup_agent": {"name":"Provider Backup Agent", "status":"enabled for chat fallback routes"}}

@app.post("/api/tasks/run")
async def run_team_task(body: TeamTask, request: Request):
    current_user(request)
    import asyncio
    try:
        import g4f  # noqa: F401
    except Exception:
        raise HTTPException(status_code=503, detail="The community AI adapter is not installed on the server.")
    model_key = body.model if body.model in MODEL_MAPPING else "x1-lite-pro-flash"
    # Low power uses 3 specialists, medium/fast run all six; the coordinator consolidates outputs.
    team = AGENT_TEAM[:3] if body.power == "low" else AGENT_TEAM
    results = await asyncio.gather(*[
        _agent_completion(body.task, agent["role"], model_key, 45)
        for agent in team
    ], return_exceptions=True)
    reports = []
    for agent, result in zip(team, results):
        reports.append({"agent":agent["name"], "status":"complete" if isinstance(result, str) and result else "failed", "result":result if isinstance(result, str) and result else f"Agent unavailable: {type(result).__name__}"})
    successful = [r for r in reports if r["status"] == "complete"]
    if not successful:
        raise HTTPException(status_code=502, detail="None of the specialist agents returned a result. Check provider availability in Render logs.")
    combined = "\n\n".join(f"### {r['agent']}\n{r['result']}" for r in successful)
    try:
        final = await _agent_completion("Produce one final deliverable for the user using these specialist reports. Resolve contradictions, remove repetition, state limitations, and include a short verification checklist.\n\n" + combined, "Coordinator: synthesize the six agent reports into one user-ready answer", model_key, 40)
    except Exception:
        final = "Team results (coordinator fallback; synthesis provider unavailable):\n\n" + combined
    return {"task":body.task, "power":body.power, "agents_expected":len(team), "agents_completed":len(successful), "agents":reports, "final":final, "note":"Agents use community-provider adapters; model labels are app aliases, not guarantees of access to official branded models."}

@app.post("/v1/video/generate")
async def video_generate(req: VideoRequest, request: Request):
    current_user(request)
    # No video model/provider was supplied in the project. Do not fake a completed generation.
    # Once VIDEO_GENERATOR_URL is configured, this endpoint can be connected to that provider.
    if not req.drive_access_token:
        raise HTTPException(status_code=400, detail="Connect Google Drive first. A Drive OAuth access token is required for BYOS storage.")
    if not os.getenv("VIDEO_GENERATOR_URL", "").strip():
        raise HTTPException(status_code=503, detail="Video generation provider is not configured. Chat is available; set VIDEO_GENERATOR_URL to a real video-generation service before enabling this endpoint.")
    raise HTTPException(status_code=501, detail="A provider-specific streaming adapter is required for VIDEO_GENERATOR_URL; no video has been generated or uploaded.")


@app.put("/v1/video/upload")
async def upload_video_to_drive(request: Request, x_drive_access_token: Optional[str] = Header(default=None)):
    """Stream an existing MP4 directly to Google Drive using resumable upload.

    The file is never written to Render's ephemeral disk. The caller must have
    granted the Google Drive `drive.file` scope through the Google OAuth flow.
    """
    current_user(request)
    if not x_drive_access_token:
        raise HTTPException(status_code=400, detail="Connect Google Drive first.")
    content_type = request.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
    if content_type not in {"video/mp4", "video/quicktime", "video/webm", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload an MP4, MOV, or WebM video file.")
    try:
        total = int(request.headers.get("content-length", "0"))
    except ValueError:
        total = 0
    if total <= 0:
        raise HTTPException(status_code=411, detail="Content-Length is required for resumable Drive upload.")
    if total > 500 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Video exceeds the 500 MB upload limit.")
    name = request.headers.get("x-video-filename", "madex-video.mp4")
    name = Path(unquote(name).replace("\\", "/")).name[:180] or "madex-video.mp4"
    metadata = {"name": name, "mimeType": content_type}
    init_headers = {"Authorization": f"Bearer {x_drive_access_token}", "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": content_type, "X-Upload-Content-Length": str(total)}
    timeout = httpx.Timeout(connect=20.0, read=None, write=None, pool=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            init = await client.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,mimeType,webViewLink,size", headers=init_headers, json=metadata)
            if init.status_code >= 400:
                raise HTTPException(status_code=401 if init.status_code in (401, 403) else 502, detail="Google Drive could not start the upload. Reconnect Drive and check permissions.")
            upload_url = init.headers.get("location")
            if not upload_url:
                raise HTTPException(status_code=502, detail="Google Drive did not return an upload session.")
            chunk_size = 8 * 1024 * 1024
            buffer = bytearray()
            sent = 0
            result = None
            async for incoming in request.stream():
                if not incoming:
                    continue
                buffer.extend(incoming)
                while len(buffer) >= chunk_size:
                    chunk = bytes(buffer[:chunk_size]); del buffer[:chunk_size]
                    end = sent + len(chunk) - 1
                    put = await client.put(upload_url, content=chunk, headers={"Content-Type": content_type, "Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{total}"})
                    if put.status_code not in (200, 201, 308):
                        raise HTTPException(status_code=502, detail="Google Drive upload failed before completion.")
                    sent = end + 1
                    if put.status_code in (200, 201): result = put.json()
            if buffer:
                end = sent + len(buffer) - 1
                put = await client.put(upload_url, content=bytes(buffer), headers={"Content-Type": content_type, "Content-Length": str(len(buffer)), "Content-Range": f"bytes {sent}-{end}/{total}"})
                if put.status_code not in (200, 201):
                    raise HTTPException(status_code=502, detail="Google Drive did not complete the video upload.")
                result = put.json()
            if sent + len(buffer) != total:
                raise HTTPException(status_code=400, detail="Upload ended before all declared bytes were received.")
            if not result or not result.get("id"):
                raise HTTPException(status_code=502, detail="Google Drive did not confirm the uploaded file.")
            return {"ok": True, "stored_in": "google_drive", "file": {"id": result.get("id"), "name": result.get("name", name), "mimeType": result.get("mimeType", content_type), "webViewLink": result.get("webViewLink") or f"https://drive.google.com/file/d/{quote(result['id'])}/view", "size": result.get("size", str(total))}}
        except HTTPException:
            raise
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Google Drive connection failed during upload. Reconnect and retry.")


@app.get("/robots.txt")
def robots():
    origin = PUBLIC_SITE_URL or "https://example.onrender.com"
    return Response(f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /v1/\nSitemap: {origin}/sitemap.xml\n", media_type="text/plain")

@app.get("/sitemap.xml")
def sitemap():
    origin = PUBLIC_SITE_URL or "https://example.onrender.com"
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{origin}/</loc></url><url><loc>{origin}/chat</loc></url></urlset>'
    return Response(xml, media_type="application/xml")


# Hybrid workspace + multi-provider gateway.
def _workspace_route(requested: str) -> str:
    value = (requested or "auto|auto").strip()
    aliases = {"chatgpt", "gemini", "deepseek", "meta", "claude", "grok", "perplexity", "x1-lite-pro-flash"}
    if value.lower() in aliases:
        return "auto|auto"
    return value or "auto|auto"


async def _hybrid_generate(route: str, messages: list[dict], temperature: float, max_tokens: int):
    """Try the selected route first, then up to three configured free-tier API routes."""
    import asyncio
    attempts = [route]
    try:
        catalog = await gateway.get_catalog()
        for row in catalog.get("rows", []):
            provider = str(row.get("provider", ""))
            candidate = str(row.get("id", ""))
            if not candidate or candidate in attempts or row.get("type", "text") != "text":
                continue
            # Only fail over to provider APIs whose credentials are actually configured.
            if provider in gateway.STATIC_MODELS and gateway.key_is_configured(provider):
                attempts.append(candidate)
            if len(attempts) >= 4:
                break
    except Exception:
        pass
    last_error = None
    for candidate in attempts:
        try:
            result = await gateway._generate_chat(candidate, messages, temperature, max_tokens)
            return (*result[:3], attempts[:attempts.index(candidate)])
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("No provider routes are available.")


@app.get("/chat", include_in_schema=False)
def chat_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/providers")
async def workspace_providers(request: Request):
    current_user(request)
    try:
        catalog = await gateway.get_catalog()
        rows = catalog.get("rows", [])
        # Keep model identifiers explicit so the frontend never implies all routes are free/available.
        return {"providers": rows, "source": catalog.get("source"), "error": catalog.get("error"),
                "configured": gateway._configured_free_routes(), "health": gateway._health_info()}
    except Exception as exc:
        return {"providers": [{"id":"auto|auto","provider":"Auto (community route)","model":"auto",
                               "type":"text","availability":"Experimental; may be unavailable"}],
                "error": str(exc)[:240]}


@app.get("/api/diagnostics")
async def workspace_diagnostics(request: Request, probe: bool = False):
    current_user(request)
    info = gateway._health_info()
    info["tls"] = gateway.http_client.ca_info()
    info["browser"] = await __import__("asyncio").to_thread(gateway.runtime_env.probe_browser, False) if probe else {"skipped": True, "reason": "Use probe=true for a Chromium launch probe"}
    import importlib.util, importlib.metadata, shutil
    def lib_status(module, distribution=None):
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            present = False
        version = None
        if present and distribution:
            try: version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError: pass
        return {"installed": present, "version": version}
    info["libraries"] = {
        "fastapi": lib_status("fastapi", "fastapi"),
        "uvicorn": lib_status("uvicorn", "uvicorn"),
        "pydantic": lib_status("pydantic", "pydantic"),
        "httpx": lib_status("httpx", "httpx"),
        "requests": lib_status("requests", "requests"),
        "certifi": lib_status("certifi", "certifi"),
        "cryptography": lib_status("cryptography", "cryptography"),
        "google_auth": {"installed": GOOGLE_AUTH_AVAILABLE, "version": (lib_status("google.auth", "google-auth")["version"] if GOOGLE_AUTH_AVAILABLE else None)},
        "g4f": lib_status("g4f", "g4f"),
        "playwright": lib_status("playwright", "playwright"),
        "provider_catalog": {"installed": True, "version": "bundled"},
        "agents": {"installed": True, "version": "bundled"},
    }
    info["executables"] = {name: shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome", "php", "java", "docker", "ollama")}
    info["notes"] = [
        "A detected executable/library does not prove an upstream provider is reachable.",
        "Chromium launch probing is opt-in because it can be memory intensive on free-tier hosts.",
        "Provider API keys are reported as configured/not configured only; secret values are never returned."
    ]
    return info


async def hybrid_chat_stream(req: ChatRequest, request: Request):
    current_user(request)
    import asyncio, json
    messages = [msg.model_dump() for msg in req.messages]
    route = _workspace_route(req.model)
    async def events():
        try:
            text, used_model, used_provider, failed_before_success = await _hybrid_generate(
                route, messages, float(req.temperature), 2048
            )
            # SSE chunking keeps the existing workspace streaming UI compatible.
            for i in range(0, len(text), 48):
                chunk = text[i:i+48]
                payload = {"choices":[{"delta":{"content":chunk},"index":0}]}
                yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"madex":{"provider":used_provider,"model":used_model,"fallback_used":bool(failed_before_success),"failed_routes":failed_before_success}}) + "\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            message = gateway.redact(exc, 400)
            yield "data: " + json.dumps({"error":{"message":message}}, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no","Connection":"keep-alive"
    })


@app.post("/api/tasks/run")
async def hybrid_task_run(body: dict, request: Request):
    current_user(request)
    import agents as agent_engine
    task = str(body.get("task", "")).strip()
    if not task or len(task) > 12000:
        raise HTTPException(status_code=400, detail="Provide a task between 1 and 12000 characters.")
    power = str(body.get("power", "medium")).lower()
    route = _workspace_route(str(body.get("model", "auto|auto")))
    async def chat(route_id, messages, temperature, max_tokens):
        return await _hybrid_generate(route_id, messages, temperature, max_tokens)
    try:
        result = await agent_engine.run_agents(
            mode="plan", prompt=task, routes=[route] * 6, judge=route, planner=route,
            rounds=1 if power == "fast" else (2 if power == "medium" else 1),
            max_subtasks=3 if power == "fast" else 5,
            temperature=0.2 if power == "low" else 0.6, max_tokens=1800,
            chat=chat, describe_error=gateway._describe_agent_error
        )
        return result
    except agent_engine.AgentPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error":"agent_task_failed","message":gateway.redact(exc,300)}) from exc


@app.get("/api/chat-link")
def chat_link():
    return {"url": os.getenv("CHAT_PUBLIC_URL", "https://chat.mysitelink.com").rstrip("/")}
