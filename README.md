# MADX Hybrid AI Studio v18.1.0

A deployable FastAPI + static frontend workspace for explicit single-provider AI calls, multi-step project planning, safe ZIP packaging, private administration, and non-executing reverse-engineering reviews.

## Included

- **User workspace** at `/` and `/chat`: chat, configured model catalogue, agent workflows, media tools, private file upload and Google sign-in support.
- **Project Foundry** at `/builder`: prompt → planner JSON → task assignments → explicit worker calls → file/path validation → downloadable ZIP. Each worker task records its selected route, prompt, status and error. An incomplete run is never reported as a complete ZIP.
- **Reverse Audit** at `/reverse`: static ZIP/APK/AAB/JAR inventory, URL/dependency extraction, Android permission-string inspection, suspicious-pattern heuristics and path traversal checks. The archive is not extracted to disk or executed.
- **Owner console** at `/admin?token=YOUR_ADMIN_ACCESS_TOKEN`: the query token is exchanged for a short-lived signed, HttpOnly cookie and the server redirects to a clean URL. Admin assets and APIs require the admin cookie. Runtime diagnostics and terminal functions do not appear in the user UI.
- **Restricted hosted terminal** at `/terminal`: an allowlist of workspace and runtime status commands, provider catalog refresh, Ollama diagnostics and storage status. No arbitrary shell, shell operators, `sudo` or secret-file reads. Full Kali is a separate local-only container under `security-lab/` and is not exposed as a web shell.
- **Database and artifacts**: SQLAlchemy models for users, projects, task records and audit events. Local development falls back to SQLite. Configure `DATABASE_URL` to use PostgreSQL in hosted deployments. By default ZIP archives are database blobs; when Firebase is configured, generated ZIP bytes and uploads use Firebase Storage, with project/task metadata and the private artifact reference retained in the application database. Google subject IDs scope signed-in users; anonymous browser sessions receive separate HttpOnly IDs, and a shared API token is not treated as a tenant identity.
- **Official/provider-approved API adapters**: direct HTTP/API integrations and user-operated compatible endpoints only. No browser-session scraper, unofficial GPT4Free/G4F wrapper, or silently substituted provider is bundled in the production runtime.
- **MADX identity**: the user-facing chat gets an application system instruction so the assistant identifies the workspace as MADX without claiming to be the official model provider.
- **Emerald / metallic green / gold liquid UI**: responsive glass UI, animated 3D orb, reduced-motion handling and mobile layouts.

## Important architecture boundaries

1. Gmail is connected through Google's official web identity flow. This project does **not** collect Gmail passwords in the terminal, store Gmail passwords, bypass multi-factor verification, copy Cloudflare challenge cookies, or use one website's session cookies to impersonate a session on another provider. Configure a Google OAuth web client and add the exact HTTPS origin to its allowed origins.
2. Every ordinary model request selects one direct provider/model route. `auto` resolves once to a configured route before the call; a failed route is reported, not silently retried against another model. The existing explicit task-agent endpoint can report a separately configured fallback, including which route was used.
3. “Free” means that a provider may offer a free tier/credit; quotas, regions, model access and terms vary. A provider key must be configured server-side. The UI never sends provider keys to the browser.
4. Output files are path-validated and size-limited, but generated applications are **not executed** in the server process. Review files and run them in a separate sandbox before deployment.
5. Static reverse-audit heuristics can produce false positives and false negatives; findings are not proof that a vulnerability exists.
6. A URL query token may be captured by infrastructure outside this application. Open the admin URL only over HTTPS, rotate a token if exposed, and prefer a secret manager or a short-lived admin session. Uvicorn access logs are disabled in the bundled command, but platform-level proxy logging is controlled by the host.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Generate independent tokens and a Fernet session key:

```bash
python -c "import secrets; print('API_ACCESS_TOKEN=', secrets.token_urlsafe(48)); print('ADMIN_ACCESS_TOKEN=', secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Place the generated values into `.env`. Set at minimum:

- `API_ACCESS_TOKEN`: app API bearer token; never reuse the admin token.
- `ADMIN_ACCESS_TOKEN`: a random, independent token with at least 32 characters.
- `GOOGLE_CLIENT_ID`, `SESSION_ENCRYPTION_KEY` and optionally `ALLOWED_LOGIN_EMAILS` for Google sign-in.
- One or more provider API keys from `.env.example` for chat and project building.
- `DATABASE_URL` for persistent PostgreSQL if you need the database to survive a host restart/redeploy.

Start the server:

```bash
uvicorn main:app --host 127.0.0.1 --port 10000 --reload
```

Open `http://127.0.0.1:10000`. The admin console is `http://127.0.0.1:10000/admin?token=YOUR_ADMIN_ACCESS_TOKEN` while testing locally with `COOKIE_SECURE=false`. Use HTTPS and `COOKIE_SECURE=true` on a public deployment.

## Render deployment

See [`API_CONNECTORS_RENDER_FREE.md`](API_CONNECTORS_RENDER_FREE.md) for the free-tier limitations, all gateway environment variables, official provider key portals, and connector setup.

1. Push this project to your own Git repository and create a Render Web Service from the repository. `render.yaml` describes the Docker service and secret env vars.
2. Set `API_ACCESS_TOKEN`, `ADMIN_ACCESS_TOKEN`, `GOOGLE_CLIENT_ID`, `SESSION_ENCRYPTION_KEY`, `PUBLIC_SITE_URL`, and at least one provider API key in the Render environment.
3. For persistence, set `DATABASE_URL` to a managed PostgreSQL instance you intentionally selected. The default local SQLite file and uploaded-file blobs use the service filesystem; they are not durable on Render Free. Render's free web service filesystem is ephemeral, and its free PostgreSQL plan expires after 30 days, so use a suitable persistent database/storage plan for real production retention.
4. Add the deployed HTTPS origin to Google OAuth client configuration. Keep `COOKIE_SECURE=true`.
5. Visit `/health` to check host health; sign in and configure the model routes; test `/builder` with a small project before relying on larger builds.
6. Admin URL form: `https://YOUR-DOMAIN/admin?token=YOUR_ADMIN_ACCESS_TOKEN`. The service exchanges the token for a short-lived HttpOnly cookie and redirects to `/admin`. Treat the query token like a password.

## Environment and provider adapters

Provider credentials are environment variables only. The main direct adapters cover providers listed in `provider_catalog.py`; configurable OpenAI-compatible integrations are usable only when you supply an authorized endpoint and credentials. For an API not represented in the catalogue, implement and test a direct adapter in `provider_catalog.py` with a clear model ID, response validation, timeouts, error redaction and provider terms review. Do not add unofficial wrappers or use browser cookies as a substitute for a documented API.

The Google Flow product is not automatically a generic video API. The `/v1/videos/generations` route reports a clear unavailable response until a supported video-provider adapter is implemented and configured; it does not fabricate a generated MP4. Image generation is available only for configured image API routes.

## Slash commands

The authenticated `POST /api/commands` endpoint accepts JSON. For example:

```json
{"command":"/plan","prompt":"Create a static café website with QR menu scanning","model":"auto"}
```

Available commands: `/help`, `/status`, `/plan`, `/build`, `/audit`. `/build` points to Project Foundry; `/audit` reviews an uploaded archive by file ID. Commands are API routes—not operating-system shell commands.

## Local Kali security lab (separate)

See `security-lab/README.md`. That disposable Kali container is for authorized local testing and static triage only. It is not needed by the hosted app and is deliberately not wired into the public web terminal.

## Validation

Run:

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q .
```

Tests use mock provider calls; a green test suite does not mean your API keys, provider quotas, OAuth application, or Render deployment have been externally verified.

## Free Edition deployment profile

For the selected Render-free configuration (hybrid hosted free-tier models + optional user-owned Ollama, Google sign-in, temporary storage, single selected model, no fallback), see [`FREE_EDITION_RENDER_SETUP.md`](FREE_EDITION_RENDER_SETUP.md) and `.env.free.example`. `render.yaml` enables `MADX_FREE_EDITION=true` and `MADX_DISABLE_FALLBACK=true` by default. Provider keys and Google OAuth client ID must be supplied by the operator in Render's Environment settings; no credentials are bundled.

## v18.1.0: Web Terminal, single-route Auto resolution, and Firebase file storage

- `GET /terminal` adds the hosted allow-list command console; arbitrary shell commands, `sudo`, and shell operators are not supported.
- The Agent Lab now selects one real configured model route. Auto is resolved once before task execution; the selected route is not swapped after failure.
- Unreachable Ollama presets are no longer treated as a ready local model in the task selector.
- Optional Firebase Storage + Firestore persistence for uploaded files and generated project ZIPs is enabled by `FIREBASE_SERVICE_ACCOUNT_JSON` plus `FIREBASE_STORAGE_BUCKET`. Project/task metadata and the storage reference still require a persistent `DATABASE_URL` to survive Render restarts; without Firebase, uploads use temporary local storage and generated ZIP bytes are stored in the app database.
- See `WEB_TERMINAL_AND_FIREBASE.md` for setup and limits.
