# MADEX Single-Model AI Hub v15.0

A mobile-friendly FastAPI app that lets you choose one exact provider/model for each request. It supports official server-side API adapters plus experimental community `g4f` adapters and an optional local Ollama endpoint.

## Single-route guarantee

- Selecting `OpenAI API|gpt-6-astra` calls the OpenAI API with that exact model ID.
- Selecting `Gemini API|...`, `Claude API|...`, `xAI Grok API|...`, `Meta Model API|...`, `DeepSeek API|...` or `Perplexity API|...` calls only that provider.
- Selecting a `g4f:Provider|model` row attempts only that explicit community adapter/model.
- If the selected provider/model fails, MADEX returns an error and `fallback_used: false`. It does not silently switch to another model.
- `auto` is one upstream g4f Auto call, not a gateway loop over model candidates. Because g4f Auto itself is managed by the upstream library, its internal routing behavior is outside MADEX's control. Select an exact provider row for the strictest control.
- Image generation now attempts only the selected image model. Video generation attempts one selected/listed route and returns an error when no actual video API is available. The app does not fabricate image/video outputs.

## Providers and catalog

### Official API routes (keys go on the server)

The selector includes common model IDs for:

- **OpenAI API** — GPT and GPT-OSS chat-capable options. OpenAI API access is separate from a ChatGPT web subscription.
- **Gemini API** — common Gemini text-generation models.
- **Claude API** — Claude Opus, Sonnet and Haiku model families.
- **xAI Grok API** — Grok chat/reasoning models.
- **Meta Model API** — Muse Spark/Wonder presets. Check Meta's model dashboard if these preset IDs differ for your account.
- **DeepSeek API** and **Perplexity API**.
- **Ollama Local** — locally installed models such as Llama, Qwen or Mistral, when an Ollama service is running.

When a valid API key is configured, MADEX also tries that provider's own model-list endpoint and appends the live IDs returned by the provider. Model-list visibility does not guarantee API access, quota or generation support; a request error is shown rather than a fallback.

Official references: [OpenAI models](https://developers.openai.com/api/docs/models), [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Claude Messages API](https://platform.claude.com/docs/en/api/messages), [xAI models](https://docs.x.ai/developers/models), [Meta Model API](https://dev.meta.ai/docs/models), [DeepSeek API](https://api-docs.deepseek.com/), [Perplexity API](https://docs.perplexity.ai/), [Ollama model library](https://ollama.com/library).

### Community routes

- The public `g4f-working` report is fetched dynamically and cached for 15 minutes.
- Additional Gemini, ChatGPT-web, Claude, Grok, MetaAI, DeepSeek, Perplexity and other community rows are displayed as **experimental presets** so you can inspect and try those routes.
- Community rows may require cookies/session state, supported browsers, or provider-specific parameters; they may fail or disappear as websites change. A row is not represented as verified just because it is visible.
- Community adapters must not be used to bypass provider login, access controls or terms. Use official API keys or local open-weight models for reliable supported access.

## Server-side API keys

Copy `.env.example` to `.env` for local development or set the corresponding variables in the host's environment settings. Do not place provider keys in browser JavaScript or commit `.env`.

| Provider | Environment variable |
|---|---|
| OpenAI | `OPENAI_API_KEY` |
| Gemini | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |
| Claude | `ANTHROPIC_API_KEY` |
| Grok / xAI | `XAI_API_KEY` |
| Meta Model API | `META_MODEL_API_KEY` (or `MODEL_API_KEY`) |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Perplexity | `PERPLEXITY_API_KEY` |
| Local Ollama | `OLLAMA_BASE_URL`, default `http://127.0.0.1:11434` |

Keys are optional if you only try keyless/community options. If a selected official provider's key is missing, the selected route responds with `provider_credentials_missing`; no other model is tried. Some official APIs bill usage or enforce quotas, so check the vendor's current pricing before setting a key.

`API_ACCESS_TOKEN` is a separate optional password for your own MADEX gateway. If deploying publicly, set a strong value before exposing generation endpoints. Never use the provider key as the MADEX access token.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Responsive phone/desktop UI |
| `GET /health` | Gateway, g4f and provider-key configuration diagnostics (never returns key values) |
| `GET /v1/status` | Service and capability status |
| `GET /v1/catalog` | Live community rows + official presets + detected community adapters |
| `GET /v1/catalog?refresh=true` | Refresh the cached catalog/model list |
| `GET /v1/models` | OpenAI-style model list, including route/auth metadata |
| `POST /v1/chat/completions` | Text chat, OpenAI-compatible request/response shape |
| `POST /v1/images/generations` | One selected g4f image-model attempt |
| `POST /v1/video/generate` | One supported video route if the library exposes a real video generation API |
| `/docs` | Interactive API docs |

Example, official Gemini route:

```bash
curl -X POST http://127.0.0.1:10000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Gemini API|gemini-3.8-flash","messages":[{"role":"user","content":"Explain gravity simply."}]}'
```

Example, exact provider/model from a live community list:

```bash
curl http://127.0.0.1:10000/v1/models
curl -X POST http://127.0.0.1:10000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"g4f:Gemini|gemini-2.5-flash","messages":[{"role":"user","content":"Hello"}]}'
```

If `API_ACCESS_TOKEN` is enabled, include `-H 'Authorization: Bearer YOUR_MADEX_TOKEN'` on generation requests.

## Run locally

Python 3.11 is recommended.

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
# Optional: copy .env.example to .env and set provider keys in that environment.
uvicorn main:app --host 0.0.0.0 --port 10000
```

Open `http://127.0.0.1:10000/` or `http://127.0.0.1:10000/docs`.

### Android / Termux / Pydroid

Termux is generally more suitable for browser-heavy g4f dependencies. Pydroid may run the FastAPI app but not every browser-based community provider. The UI and official API adapters need internet access. To run local Llama models through Ollama, Ollama must be installed and reachable from the Python process; the models can be too large for a typical phone.

### Docker / Render

Build/run with the included `Dockerfile`, or deploy through `render.yaml`. Set `API_ACCESS_TOKEN` before public deployment and add only the API keys you intend to use in the host's **Environment** settings. Free hosting can sleep, run out of memory, or lack the browser support required by some community adapters.

## Tests

Tests use mocks and do not spend API credits or require live provider access:

```bash
pip install -r requirements-dev.txt
pytest -q
python -m compileall -q main.py provider_catalog.py tests test_universal.py
```

A passing test suite validates the wrapper/routing logic, not whether a real provider is online or an account has quota.

## Security and privacy

- Prompts are sent to the specific selected provider. Review that provider's privacy and data policies.
- Do not send passwords, government IDs, payment information, confidential code or private customer data through public community adapters.
- API keys belong in server environment variables, never in the frontend, GitHub, browser local storage, screenshots or chat messages.
- Community adapters are unofficial. Respect provider access controls and terms.

## Project notes

This wrapper is not affiliated with OpenAI, Google, Anthropic, xAI, Meta, DeepSeek, Perplexity or the g4f project. Upstream g4f: https://github.com/xtekky/gpt4free. Community provider list: https://github.com/Free-AI-Things/g4f-working.
