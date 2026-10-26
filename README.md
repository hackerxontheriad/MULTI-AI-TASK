# MAD X Hybrid AI Studio — v17.0.0

A free-first AI workspace built from the two supplied project ZIPs. The current runtime uses the v16.1 single-route FastAPI backend, while preserving the original browser/preview materials, brand assets and legacy gateway as an isolated reference. The landing page has been redesigned with emerald/metallic-gold animation; a TSX React source version is included separately.

## What is actually included

- **Single selected-model requests:** `POST /v1/chat/completions` calls the named provider/model route and reports errors instead of silently swapping providers. A task workflow can use explicit configured fallback routes; its results report which routes were used.
- **Six-agent workflow:** planner, researcher, builder, reviewer, optimizer and tester. Results depend on the selected/configured routes, quotas and host resources.
- **Chat + code tools:** assistant code blocks support Copy and Download. HTML/SVG adds Run and Preview in a sandboxed iframe. This is a browser preview, not a general Python/Java/PHP code execution engine.
- **Files and media:** authenticated, session-scoped upload/list/download/delete endpoints; local previews for supported formats; a real MP4 asset is retained.
- **Authentication:** server verification of Google ID tokens with `email_verified == true`, encrypted HttpOnly session cookies, API access-token mode, rate limits and separate admin diagnostics password.
- **Connector status:** `/api/connectors/status?probe=true` (requires a verified Google session or valid bearer token) reports configuration and probes the configured OpenAI-compatible gateway `/models` endpoints. A successful probe is not a promise that text generation or quota is available.
- **Provider adapters:** official/free-tier API adapters, local/hosted Ollama, LiteLLM/PawanOsman-compatible URLs, and configurable OmniRoute, 9Router, New-API and One-API compatible gateways.
- **MCP setup:** OmniRoute MCP configuration example and guide are included. The OmniRoute process must run separately; the Python app does not start, provision or extend OmniRoute tokens. Current upstream installation requirements specify Node.js `>=22.22.2 <23` or `>=24 <27`; the build environment here has Node `22.16.0`, so OmniRoute itself was not installed or launched during validation. See the [upstream setup guide](https://github.com/cheaper-inference/OmniRoute/wiki/Setup-Guide) and [MCP guide](https://github.com/cheaper-inference/OmniRoute/wiki/mcp-server).
- **Android source wrapper:** Gradle, Java, manifest and resources are included. This package contains Android source code, **not a compiled/signed APK**.
- **Preview runner examples:** HTML, Java, PHP and Python example folders plus Dockerfiles are present.
- **Static RE/audit utility:** `scripts/audit_project.py` inventories a folder/ZIP/APK/AAB and flags review candidates without executing archive contents.
- **Both logos:** current `mad-x-logo.svg`, legacy `logo-mark.svg`, and both old/new icon PNG paths are preserved. The original landing page is stored as `legacy/static/landing-v1.html`.

## Start locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\\Scripts\\activate
pip install -r requirements-lite.txt
cp .env.example .env
```

Generate three independent secrets/configuration values:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the first value as `API_ACCESS_TOKEN`, the second as `DIAGNOSTICS_PASSWORD`, and the Fernet key as `SESSION_ENCRYPTION_KEY`. Set `GOOGLE_CLIENT_ID` to a Google Cloud **Web application** OAuth client ID and add the correct public HTTPS origin to its authorized JavaScript origins. Set `PUBLIC_SITE_URL` to your canonical deployed HTTPS URL. Provider keys belong only in `.env` or your hosting provider's secret environment. On local plain HTTP only, `COOKIE_SECURE=false` may be needed for development; keep `COOKIE_SECURE=true` in public HTTPS deployment.

```bash
uvicorn main:app --host 127.0.0.1 --port 10000
```

Open `http://127.0.0.1:10000/` for the new landing page or `/chat` for the workspace. Use the token you created in the workspace Settings only for a private/owner-controlled installation; never publish that token or embed it in a public APK/frontend.

## Provider configuration

Free-first API options (quotas, access and terms vary):

- `GEMINI_API_KEY` / `GOOGLE_API_KEY`
- `GROQ_API_KEY`
- `CEREBRAS_API_KEY`
- `MISTRAL_API_KEY`
- `GITHUB_MODELS_TOKEN`
- `HF_TOKEN`
- `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`
- `POLLINATIONS_API_KEY`
- `OLLAMA_BASE_URL` for an Ollama instance you control

For compatible gateways, configure each separately:

| Gateway | Required settings | Notes |
|---|---|---|
| OmniRoute | `OMNIROUTE_BASE_URL`, `OMNIROUTE_API_KEY`, optional `OMNIROUTE_MODELS` | Run OmniRoute separately; create an endpoint key in its dashboard. |
| 9Router | `NINE_ROUTER_BASE_URL`, `NINE_ROUTER_API_KEY`, optional `NINE_ROUTER_MODELS` | Exact upstream repository/API URL still needs verification. |
| New-API | `NEW_API_BASE_URL`, `NEW_API_API_KEY`, optional `NEW_API_MODELS` | Separate service, channels and account configuration required. |
| One-API | `ONE_API_BASE_URL`, `ONE_API_API_KEY`, optional `ONE_API_MODELS` | Separate service and account setup required. |
| LiteLLM | `LITELLM_BASE_URL`, `LITELLM_API_KEY`, optional `LITELLM_MODELS` | Authorized proxy you control. |
| PawanOsman-compatible | `PAWANOSMAN_BASE_URL`, `PAWANOSMAN_API_KEY`, optional `PAWANOSMAN_MODELS` | Authorized OpenAI-compatible endpoint only. |

Use exact model IDs returned by your own gateway's `/v1/models` or its dashboard. The starter examples are not an uptime guarantee. No endpoint/key is filled with a made-up live value.

## OmniRoute MCP setup

See [`mcp/README.md`](mcp/README.md) and [`mcp/omniroute.mcp.example.json`](mcp/omniroute.mcp.example.json). The MCP server is provided by the separate OmniRoute project (for example `omniroute --mcp` for a local install). Use the transport your MCP client supports and configure the right URL/key. MAD X cannot mint or extend OmniRoute account tokens automatically.

## Frontend / TSX

The production `/` route currently serves `static/landing.html` so the Python app works without a Node build step. The matching React/TSX source is in `frontend/src/main.tsx`; see `frontend/README.md` to build the separate TSX preview. TSX and minification do not stop reverse engineering: browser-delivered code is inspectable, so secrets must stay server-side.

## External repositories and source files

`integrations/registry.json` lists the user-requested projects and older ecosystem candidates with a clear status. The separate upstream projects are **not all bundled into this ZIP**. GitHub access failed in this build environment, and some projects are separate Node apps, GPU services, API gateways or have license/dependency requirements incompatible with installing wholesale into this FastAPI runtime. The safe opt-in fetcher `scripts/fetch_upstreams.py` can shallow-clone the explicitly listed repositories where you have network access; it only fetches files and does not install or execute them. Inspect the source license and dependencies before using. `9Router` still needs the exact owner/repository URL.

Two ZIPs were provided in this turn; no extra 10–14 individual report attachments were available in this workspace. Previously present `UPSTREAM_RESEARCH-v1.md` and `UPSTREAM_INTEGRATIONS-v1.md` are preserved.

## Reverse-engineering/static audit

```bash
python scripts/audit_project.py /path/to/project-or-archive.zip --json reports/audit.json
```

This is a heuristic static inventory tool, not a complete security guarantee. It does not run code in uploaded archives. Use it only for assets you own or are authorized to inspect.

## Render deployment

`render.yaml` and the Dockerfile are retained. The default deployment selects `requirements-lite.txt` and skips Chromium to fit small hosts; community browser-backed adapters may not be available in that mode. Add the environment secrets in Render's dashboard and set `PUBLIC_SITE_URL`. If the Render service is stopped, its hosted API is not reachable; local operation is possible only when dependencies and provider endpoints are configured locally. A free plan does not mean provider inference or cloud compute is unlimited.

## Android wrapper

Open `android-wrapper/` in Android Studio, configure the correct HTTPS service URL in `MainActivity.java`, then build and sign the APK with your own Android signing key. This environment has no Android SDK/Gradle installation available, so an APK has not been compiled or signed in this ZIP. Do not put provider or app access tokens into the APK.

## Checks

```bash
pip install -r requirements-dev.txt
pytest -q
python -m py_compile main.py agents.py provider_catalog.py runtime_env.py http_client.py agent_router.py scripts/audit_project.py scripts/fetch_upstreams.py
node --check static/app.js
node --check static/landing.js
node --check static/diagnostics.js
```

Source/license references are listed in [`integrations/registry.json`](integrations/registry.json). A configured or reachable route is not the same thing as verified model generation.
