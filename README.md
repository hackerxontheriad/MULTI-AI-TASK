# MadEx Multi-AI Gateway (v13)

A safer replacement for the two supplied ZIPs. It keeps an OpenAI-compatible chat route, supports provider-based fallback, removes browser scraping from the core chat path, and connects the video route to Google's actual Gemini Omni video API. It does **not** pretend a sample MP4 is a generated video.

## What's fixed

- **Chrome/Chromium error:** removed the `g4f`/Playwright browser dependency from the chat pipeline. API calls now go through LiteLLM and configured provider APIs, so the main chat path does not need Chrome or Chromium.
- **API limit exhaustion:** retries/falls back to another provider only when that provider has its own configured credentials. It cannot bypass a provider's usage quota. Add a second provider key, check billing/quota, or run an Ollama model locally.
- **Fake video output removed:** `/v1/video/generate` submits to Google's Gemini Omni Interactions API. If the Google key is absent or the provider rejects/fails the request, the job reports an error; no sample MP4 or fabricated file is created.
- **Video jobs are asynchronous:** submit a job, then poll `/v1/video/jobs/{job_id}` so a long generation does not hold the HTTP request open.
- **Security:** environment-only credentials, optional bearer-token protection with `API_ACCESS_TOKEN`, model/input validation, bounded request fields, random file names, and HTTPS/public-host checks for `image_url`.
- **Deployment:** a current Python Dockerfile that uses Render's `PORT` when present and does not attempt to install an unneeded browser.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS/Termux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add at least one genuine provider key (for example `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, or `OPENAI_API_KEY`). If deploying publicly, replace `API_ACCESS_TOKEN` with a long random secret and send it as `Authorization: Bearer YOUR_TOKEN`. Do not put keys in frontend JavaScript or upload `.env` to GitHub.

```bash
uvicorn main:app --host 0.0.0.0 --port 10000 --reload
```

Open `http://127.0.0.1:10000/docs` and `http://127.0.0.1:10000/health`.

## Chat API

The previous aliases remain: `chatgpt`, `gemini`, `deepseek`, `meta`, `claude`, `grok`, `perplexity`, `mistral`, `openrouter`, and `ollama`. You can also pass a LiteLLM model ID such as `provider/model-name`, or `auto` to use configured fallback providers.

```bash
curl http://127.0.0.1:10000/v1/chat/completions \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: Bearer replace-with-a-long-random-token' \\
  -d '{
    "user_id": "demo",
    "model": "auto",
    "messages": [{"role": "user", "content": "Write a Python prime checker."}],
    "stream": false
  }'
```

Set `stream` to `true` for Server-Sent Events. For an OpenAI-only, Anthropic-only, or Gemini-only request, use that alias or a provider/model ID. If that provider fails and another provider key is configured, this server can return a fallback answer and reports the actual serving model under `madex.served_by`.

Model IDs can change or vary by account. Override `MODEL_CHATGPT`, `MODEL_CLAUDE`, `MODEL_GEMINI`, etc. in `.env` with model IDs currently available to your provider account. LiteLLM supports 100+ providers, but the models are not all free and this app cannot create credentials or quota for you.

## Video API

Real generation requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and access to `gemini-omni-1.1-flash` in Google AI Studio. Google video generation is billed/limited separately from chat. The older Veo 3.1 preview IDs are deprecated as of October 22, 2026, so this project defaults to Gemini Omni Flash; see Google's current official docs before changing the model.

Submit a video job:

```bash
curl -X POST http://127.0.0.1:10000/v1/video/generate \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: Bearer replace-with-a-long-random-token' \\
  -d '{"user_id":"demo","prompt":"A cinematic drone shot above a neon city at night","aspect_ratio":"16:9","resolution":"720p"}'
```

The API returns `202` and a `job_id`. Poll the returned `status_url` until `status` is `completed` or `failed`. When complete, `player_ready_url` points to the generated MP4. Image-to-video accepts either `image_url` (public HTTPS image only) or `image_base64` plus `image_mime_type`.

**Persistence note:** the starter stores jobs in process memory and videos on the local filesystem. A process restart or redeploy can clear job records; use a persistent disk/object store and a Redis/database-backed queue for production scale.

## Test

Offline logic/unit tests (do not spend API quota):

```bash
pip install -r requirements-dev.txt
pytest -q
```

Live smoke test against a running server:

```bash
python test_universal.py
```

Set `API_BASE`, `API_ACCESS_TOKEN`, and optionally `TEST_MODEL` as environment variables. Set `TEST_VIDEO=1` only when you intentionally want to submit a real billable video generation request.

## Deployment notes

- Docker: `docker build -t madex-gateway . && docker run --env-file .env -p 10000:10000 madex-gateway`
- Render: deploy from this folder using the included Dockerfile; define provider keys and `API_ACCESS_TOKEN` in Render's environment settings.
- No Chrome/Chromium install is required for the chat route. Do not re-add browser automation unless a separate feature genuinely needs a browser.
- Never commit API keys. `API_ACCESS_TOKEN` protects your gateway endpoint; provider API keys must remain server-side.
