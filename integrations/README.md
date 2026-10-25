# MADEX ecosystem integration guide (v16)

This pack records all 26 requested/reference projects and clarifies their integration state. It does **not** copy 26 complete repositories into one application: they have different licenses, runtimes (Python/Node/Streamlit), storage requirements and GPU needs. The manifest is `integrations/registry.json`.

## What is connected in the current gateway

- **g4f**: optional experimental community adapter/catalog. Browser providers are best-effort, may require Chromium/session state, and are unreliable on Render free (512 MB). They are not official APIs and do not guarantee unlimited free usage.
- **Native multi-agent orchestration**: `agents.py` provides compare, council, and planner modes. These call only routes explicitly selected by the user; no hidden provider fallback.
- **Free-tier API adapters**: Groq, Cerebras, Mistral, Gemini, GitHub Models, Hugging Face, Cloudflare Workers AI and Pollinations, each with provider-specific keys and limits.
- **LiteLLM / PawanOsman-compatible endpoints**: configurable OpenAI-compatible adapters. Set the exact endpoint and credentials you are authorized to use. No guessed public base URL is hard-coded.
- **Ollama**: local or reachable server endpoint. `OLLAMA_API_KEY` is optional and sent as a Bearer header for hosted endpoints. The diagnostics endpoint now probes `/api/tags` and reports reachability without revealing the key.
- **Image generation**: current native routes include Pollinations and Cloudflare; g4f image routes are experimental.

## Render environment setup

1. Set a long random `API_ACCESS_TOKEN` to protect the MADEX gateway.
2. Add only provider keys you own, in Render → service → Environment. Never commit `.env` or keys.
3. For Cerebras, set `CEREBRAS_API_KEY`. A missing key is a configuration error, not a model outage.
4. For Ollama, set `OLLAMA_BASE_URL` to an HTTPS endpoint reachable from Render. Add `OLLAMA_API_KEY` only if that endpoint requires it. The default `http://127.0.0.1:11434` is the Render container itself and will not reach your Android phone or PC.
5. After deployment, call `/v1/diagnostics` (with your app token if configured). Inspect the `ollama` object and configured provider names.
6. Keep `REQUIREMENTS_FILE=requirements-lite.txt` and `INSTALL_BROWSER=0` on Render free. Installing g4f + Chromium may exceed the instance's RAM; do not treat a build that succeeds as proof a provider will work.

## Separate services, not bundled into the free Render container

- **LibreChat / big-AGI**: separate frontend applications; configure their provider/base URL to the MADEX OpenAI-compatible endpoint where supported.
- **ComfyUI / Fooocus / AUTOMATIC1111**: separate image/video inference servers; normally need GPU hardware and substantial model storage. A secure authenticated adapter is needed before MADEX can call them.
- **MCP memory service / AgentOps / Caspian / A2A examples**: require separate credentials, services or explicit code adapters. Their presence in the registry does not mean they are live-connected.
- **CrewAI / LangGraph / MetaGPT / Open Interpreter**: optional framework integrations, not default dependencies. See `requirements-integrations.txt`; install only selected packages after checking compatibility. Never run Open Interpreter or arbitrary model-generated code inside the public web worker without sandboxing and explicit user approval.
- **DuckDuckGo AI Chat**: no supported stable public chat endpoint is configured here; the app does not scrape private endpoints or bypass login/access controls.

## Free-use reality

The app code and many frameworks are open-source, but API keys have quotas, free tiers change, and GPU hosting/storage may cost money. Local Ollama can be zero API-cost if you supply compatible hardware and power. If a provider key is absent or a quota is exhausted, the selected route returns its own error; MADEX will not silently switch to a different model.

## Verify

```bash
pip install -r requirements-dev.txt
pytest -q
```

Real provider tests require working credentials and network access; offline tests do not prove an upstream service is currently available.
