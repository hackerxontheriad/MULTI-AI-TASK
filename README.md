# MadEx Free Multi-AI Hub — v14.1

A mobile-friendly FastAPI wrapper built around the public GPT4Free (`g4f`) Python client. It adds a simple Chat / Image / Video interface, an OpenAI-style chat endpoint, a live keyless-provider catalog, fallback attempts, diagnostics, tests, and Docker/Render files.

## Free-mode promise (and its limits)

- This project does **not** configure an OpenAI, Anthropic/Claude, Gemini, DeepSeek, OpenRouter, or other paid model-provider API key. Chat and image requests use `g4f` provider adapters directly.
- The public [`g4f-working`](https://github.com/Free-AI-Things/g4f-working) list is fetched dynamically and cached for 15 minutes. It reports model/provider pairs that a community tester found working without API keys/tokens/cookies. A result can stop working at any time.
- The app deliberately excludes OpenRouter and KiloCode aliases from its catalog; it is meant to try direct g4f adapters rather than require a router account/key.
- **There is no promise of unlimited or continuous free inference.** Public providers can rate-limit, be unavailable, change their behavior, require browser support, or change their terms. A live text row can still fail for your specific request.
- **Video is not falsely advertised as always available.** The live `g4f-working` report fetched on 22 Oct 2026 listed text capability rows but no verified image/video rows. Image mode still tries genuine g4f image adapters experimentally. Video checks the live catalog and the installed g4f client; if a verified keyless video provider/API is absent, it returns HTTP 503 without inventing an MP4 or returning a sample clip.
- If you need reliable image/video service every time, a provider with official API access or a sufficiently powerful local model may be necessary. This is separate from the wrapper.

## Features and endpoints

| Feature | Endpoint | Behavior |
|---|---|---|
| Responsive web UI | `/` | Phone/desktop interface with Chat, Image, Video tabs |
| Health diagnostics | `GET /health` | FastAPI, g4f install status, Chromium path |
| Service status | `GET /v1/status` | Catalog counts and capability caveats |
| Keyless catalog | `GET /v1/catalog` | Current `provider|model|type` list; use `?refresh=true` to refresh |
| OpenAI-like models | `GET /v1/models` | Auto plus discovered provider/model names |
| Text chat | `POST /v1/chat/completions` | g4f client with bounded keyless provider fallback; optional SSE response |
| Image generation | `POST /v1/images/generations` or `/v1/image/generate` | Tries actual g4f image adapters; never returns a fake stock image |
| Video generation | `POST /v1/video/generate` | Works only if an actual no-auth video route is reported and the installed g4f exposes a supported API; otherwise HTTP 503 |
| API docs | `/docs` | Swagger UI |

## Run locally

Python 3.11 is recommended. Browser providers need extra OS dependencies; Docker below handles Chromium on Debian Linux.

### Windows, Linux, or macOS

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
# Optional local configuration: copy .env.example to .env; set API_ACCESS_TOKEN only if you want app-level protection.
uvicorn main:app --host 0.0.0.0 --port 10000
```

Open `http://127.0.0.1:10000/` or `http://127.0.0.1:10000/docs`. The AI provider service itself does not require a commercial API key, but internet access is required.

### Android / Termux

Termux is generally more suitable than Pydroid for g4f and browser-oriented dependencies. Not every provider or Chrome-based adapter will work on Android.

```bash
pkg update
pkg install python clang rust ffmpeg flac
python -m pip install --upgrade pip
pip install -r requirements-mobile.txt
python -m uvicorn main:app --host 127.0.0.1 --port 10000
```

Then open `http://127.0.0.1:10000/` in your phone browser. If installation fails on your Android/Python version, the error may be from a dependency that does not support that platform. A keyless provider working on a Linux server does not guarantee it will work on Android.

### Environment settings

Copy `.env.example` to `.env` for local reference, or enter values in the host's environment settings:

- `API_ACCESS_TOKEN`: optional secret for protecting your own public gateway; it is **not** a provider API key. If unset, generation endpoints are unprotected, so set it before deploying publicly.
- `G4F_WORKING_RESULTS_URLS`: comma-separated HTTPS URLs to the provider list.
- `CATALOG_TTL_SECONDS`: catalog cache lifetime (default `900`).
- `G4F_REQUEST_TIMEOUT`: seconds per provider attempt (default `60`).
- `G4F_FALLBACK_LIMIT`: number of model/provider candidates to try (default `4`).
- `G4F_MAX_WORKERS`: shared cap for blocking g4f operations (default `4`), helping limit runaway provider calls after a timeout.
- `CHROME_BIN` and `CHROMIUM_PATH`: paths to Chromium if a selected provider needs a browser.

## Docker

This image installs Chromium and Chromium Driver to address the `Google Chrome/Chromium not found` type of error. Some g4f adapters may use other helper libraries and still fail independently.

```bash
docker build -t madex-free-ai .
docker run --rm -p 10000:10000 -e PORT=10000 -e API_ACCESS_TOKEN='use-a-long-random-secret' madex-free-ai
```

## Render free hosting

1. Upload the **extracted project files**, not the ZIP itself, to a GitHub repository. Do not upload `.env` or any secret.
2. In Render choose **New → Blueprint** and select the repo to use `render.yaml`, or create a Web Service with Docker runtime and use the root `Dockerfile`.
3. Ensure `healthCheckPath` is `/health`.
4. Add `API_ACCESS_TOKEN` in Render Environment settings before exposing the service publicly.
5. After deploy, open the `*.onrender.com` URL, then `/health` and `/docs`.

Render's free service can sleep and has limited RAM/disk/build capacity. Chromium + provider dependencies may be too heavy for some free instances; if the Docker build or memory limit fails, try local/Termux or a smaller host. Files in the container can be lost when the instance restarts/redeploys.

## API examples

```bash
curl http://127.0.0.1:10000/health
curl http://127.0.0.1:10000/v1/catalog

curl -X POST http://127.0.0.1:10000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"Explain Python lists simply."}]}'

curl -X POST http://127.0.0.1:10000/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{"model":"auto","prompt":"A blue butterfly on a flower, detailed digital art","size":"1024x1024"}'

curl -X POST http://127.0.0.1:10000/v1/video/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"A cinematic city skyline at sunset"}'
```

When `API_ACCESS_TOKEN` is set, include `-H 'Authorization: Bearer YOUR_TOKEN'` on generation requests. `/v1/video/generate` can legitimately return 503 when no verified keyless provider exists.

## Tests

Offline tests do not make AI requests, do not need provider access and do not spend credits:

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q main.py tests test_universal.py
```

For a running local app, run `python test_universal.py`. For Render, set `API_BASE=https://YOUR-APP.onrender.com` and optional `API_ACCESS_TOKEN` first. These tests check API health and routing, **not** live model quality/generation.

## Privacy and security

Prompts are sent to whichever public third-party provider responds. Do not send passwords, personal IDs, payment information, confidential source code, or private customer data through free public adapters. Set `API_ACCESS_TOKEN` before publishing your own gateway, and keep it out of GitHub and screenshots.

## Upstream code and terms

- GPT4Free: <https://github.com/xtekky/gpt4free> (upstream project is GPL-3.0; review the upstream license and provider terms when redistributing or using commercially).
- Keyless working provider list: <https://github.com/Free-AI-Things/g4f-working> (upstream reports are community maintained; check that repo's license before reusing the list in a commercial product).
- This wrapper is separate from those repositories and is not affiliated with Google, OpenAI, Anthropic, xAI, Meta, or any third-party provider.


## Single-model request behavior (v14.1 single-route patch)

Chat requests now attempt only the provider/model requested in `model` (for example,
`ProviderName|model-id`). If that exact route fails, the API returns HTTP 502 with
`error: requested_model_failed`, `requested_model`, `reason`, and
`fallback_used: false`. It does not silently switch to DeepSeek, Gemini, Cloudflare,
or another provider. `model: "auto"` makes one g4f Auto-route call; the gateway itself
does not loop over a provider list. Image/video behavior and the rest of the project
are unchanged.
