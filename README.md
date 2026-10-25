# MADEX Single-Model AI Hub v15.2

A mobile-friendly FastAPI gateway where **you choose the exact provider/model for every request**. Version 15.1 adds
zero-cost routes (free-tier APIs + local open-source models), real Chromium/SSL handling, secret-safe errors, and
**multi-agent modes** (Compare, Council, Planner).

## Single-route guarantee (unchanged)

- A request calls only the provider/model you selected. If it fails you get an error with `fallback_used: false`.
- Multi-agent runs follow the same rule: every agent is bound to a route **you** ticked. A failed agent reports its own
  error; it is never re-routed and its answer is never invented.
- The gateway only retries the **same URL** on transient network/TLS/429/5xx errors. That is not model fallback.

## Zero-cost operation

Set any of these keys on the server (`.env` or host environment). All were free-tier at the time of writing; limits and
terms change, so re-check each provider. **Free tiers may use your prompts to improve products — do not send private data.**

| Route | Env var(s) | Get a key | Notes |
|---|---|---|---|
| Groq API | `GROQ_API_KEY` | console.groq.com/keys | free tier, per-model rate limits |
| Cerebras API | `CEREBRAS_API_KEY` | cloud.cerebras.ai | small context caps on free keys |
| Mistral API | `MISTRAL_API_KEY` | console.mistral.ai | "Experiment" plan |
| Gemini API | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | aistudio.google.com/apikey | free tier; not offered in EEA/UK/CH |
| GitHub Models | `GITHUB_MODELS_TOKEN` / `GITHUB_TOKEN` | fine-grained token with `models:read` | prototyping limits |
| Hugging Face API | `HF_TOKEN` | huggingface.co/settings/tokens | monthly free credits |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | dash.cloudflare.com | daily free allowance; also image route |
| Pollinations API | `POLLINATIONS_API_KEY` | enter.pollinations.ai | text + **image** |
| Ollama Local | `OLLAMA_BASE_URL` | install Ollama | open-source models on your own hardware |

Paid/other official routes remain: OpenAI, Claude, xAI Grok, Meta Model API, DeepSeek, Perplexity.
When a key is set the provider's own model list replaces the preset IDs (installed models for Ollama), so stale preset
IDs are harmless. OpenRouter/KiloCode aliases stay blocked by design.

## Multi-agent modes (`POST /v1/agents/run`, UI tab "Agents")

Patterns inspired by the GitHub topics *multi-ai-agents* / *ai-agents*, implemented natively with no extra dependencies:

| Mode | What happens | Calls |
|---|---|---|
| `compare` | same prompt to 2–6 models, side by side | N |
| `council` | members answer; with `rounds: 2` they critique each other; a **judge** merges | N (+N) +1 |
| `plan` | **planner** returns JSON subtasks → workers (round-robin over your list) → **synthesiser** | 1 + subtasks + 1 |

Safeguards: max 6 routes and 16 model calls per run, 3 concurrent calls (free tiers), peer text is marked untrusted
before being shown to other models, an invalid planner plan returns an error instead of a made-up plan.

```bash
curl -X POST http://127.0.0.1:10000/v1/agents/run -H 'Content-Type: application/json' -d '{
  "mode":"council","prompt":"Is SQLite fine for a small SaaS?",
  "routes":["Groq API|llama-3.3-70b-versatile","Mistral API|mistral-small-latest"],
  "judge":"Groq API|openai/gpt-oss-120b","rounds":2}'
```

## Optional compatible proxies

The catalog includes two **user-configured** OpenAI-compatible routes; neither points to a bundled public endpoint:

- `LiteLLM Proxy`: set `LITELLM_BASE_URL` (for example your own `http://127.0.0.1:4000/v1` proxy), `LITELLM_API_KEY`, and optionally `LITELLM_MODELS` as a comma-separated list.
- `PawanOsman Compatible API`: set `PAWANOSMAN_BASE_URL`, `PAWANOSMAN_API_KEY`, and optionally `PAWANOSMAN_MODELS`. This only works if the endpoint you control/are authorized to use exposes the OpenAI-compatible `/chat/completions` API.

These routes never guess a public service URL and never silently switch models. `DuckDuckGo AI Chat` does not have a stable, supported public chat API in this project; it is not scraped or reverse-engineered here. Use a documented search API or a provider route you are authorized to call instead. The project does not claim that every community/browser provider is reliable or production-ready.

## Fixes in 15.2

- Canonicalise copied g4f provider IDs with accidental whitespace after `g4f:`.
- Improve shared-Chrome/DBus error hints so diagnostics distinguish a browser warning from a confirmed browser startup failure.
- Ignore and remove stale Chrome environment paths so they cannot mask a usable browser executable.
- Add configurable LiteLLM Proxy and PawanOsman-compatible OpenAI API routes, requiring explicit user-supplied base URLs and keys.
- Add regression tests for provider-ID normalisation, compatible-proxy configuration, and shared-Chrome diagnostics.

## Fixes in 15.1

- **Chromium**: no more hard-coded `/usr/bin/chromium`; a real binary is detected (env → wrapper → PATH → known paths),
  stale env paths are removed, containers get `--no-sandbox`/`--disable-dev-shm-usage`/headless via `scripts/chromium-safe`,
  and `/v1/diagnostics` actually launches the browser once and reports why it fails (root, missing libs, low RAM).
- **SSL/network**: CA bundle auto-configured (certifi/system/`CA_BUNDLE`), bounded same-URL retries with backoff and
  `Retry-After`, actionable hints (certificate vs DNS vs proxy vs timeout). TLS verification is **never** disabled.
- **Secret leak**: Gemini used `?key=` in the URL and raw exception text was returned to clients. The key is now a header and
  every client-visible string is redacted.
- **`.env` was never loaded** despite the old README. A dependency-free loader now reads it (real env vars win).
- Stuck community calls no longer exhaust the worker pool silently (separate pools, `503 g4f_workers_busy`).
- Per-provider fixes: Anthropic temperature cap and role alternation, Gemini thinking-token/empty-answer errors,
  `developer`/`tool` role normalisation, Mistral/Cerebras temperature caps, `max_completion_tokens` where required.
- `/health` no longer imports g4f (fast health checks); failed community-catalog fetches retry after 60 s, not 15 min.
- Optional per-client rate limit (`RATE_LIMIT_PER_MIN`) protects your free quotas; constant-time token comparison.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-lite.txt                    # free-tier APIs + Ollama, no browser
# pip install -r requirements.txt                       # + community g4f adapters (needs Chromium)
cp .env.example .env                                    # add at least one free key
uvicorn main:app --host 0.0.0.0 --port 10000
```

Open `http://127.0.0.1:10000/`, press **Run diagnostics**, then pick routes marked "Free & ready".

### Docker / Render

```bash
docker build -t madex .                                                    # full: Chromium + g4f
docker build -t madex-lite --build-arg INSTALL_BROWSER=0 --build-arg REQUIREMENTS_FILE=requirements-lite.txt .
```

`render.yaml` builds the **lite** image (free Render plans have 512 MB RAM — too little for Chromium). Set
`API_ACCESS_TOKEN` before exposing the service. For community adapters use a paid plan with ≥1 GB RAM and set
`INSTALL_BROWSER=1`, `REQUIREMENTS_FILE=requirements.txt`.

### Android / Termux

`pkg install python chromium`, then `pip install -r requirements-mobile.txt`. Pydroid cannot run browser providers.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | UI (Chat, Agents, Image, Video) |
| `GET /health` | fast status (never returns keys) |
| `GET /v1/diagnostics` | CA bundle, real Chromium launch probe, g4f worker slots, configured free routes |
| `GET /v1/catalog[?refresh=true]` · `GET /v1/models` | catalog (free/ready flags) |
| `POST /v1/chat/completions` | OpenAI-compatible chat (one route) |
| `POST /v1/agents/run` | compare / council / plan |
| `POST /v1/images/generations` | `Pollinations API\|flux`, `Cloudflare Workers AI\|@cf/black-forest-labs/flux-1-schnell`, or a g4f row |
| `POST /v1/video/generate` | only if g4f exposes a real video API; otherwise 503, never fake media |

Error codes: `424` missing/rejected key, `429` provider or gateway rate limit (with `Retry-After`), `503` busy workers,
`504` timeout, `502` provider failure. Responses include `hint` with the likely fix.

## Tests

```bash
pip install -r requirements-dev.txt && pytest -q
```
All tests are offline (mocked HTTP, stub models, fake browser binary).

## What I could not verify

Real provider calls, a Docker build and the full FastAPI/pytest run were not possible in the sandbox (no network).
Model IDs marked "verify ID" are presets; the live model list is the source of truth once a key is set.
The Pollinations (`gen.pollinations.ai`) and Cloudflare image/chat endpoints follow current docs but were not called live.

## Project notes

Not affiliated with OpenAI, Google, Anthropic, xAI, Meta, DeepSeek, Perplexity, Groq, Mistral or the g4f project.
Community adapters are unofficial; respect each provider's terms and do not use them to bypass access controls.
Upstream g4f: https://github.com/xtekky/gpt4free · list: https://github.com/Free-AI-Things/g4f-working
