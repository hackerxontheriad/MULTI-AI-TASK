# MADX Hybrid v18 — Render Free + API connector setup

This bundle keeps the application and all connector adapters in one repository. It does **not** include third-party API keys, paid account access, or hosted gateway instances. Each key must be issued by its provider/account owner.

## Important Render Free limitations

- Free web services sleep after 15 minutes of inactivity and may take about a minute to wake.
- Free web service files are ephemeral. SQLite files, generated ZIPs and uploads stored only on local disk can disappear on restart/redeploy/spin-down.
- Render Free PostgreSQL is limited and expires 30 days after creation. Do not use it as permanent production storage.
- For a no-cost demo, you may leave `DATABASE_URL` unset and accept that local database/files are temporary. For durable user/project history, use a persistent database/storage provider and configure its URL.
- A single Git repository can hold all application code/config. The gateway services themselves can be separately hosted and connected by HTTPS URLs.

## Deploy this repo

1. Push the extracted repository root (the directory containing `Dockerfile` and `render.yaml`) to your Git provider.
2. In Render choose **New → Blueprint**, connect the repository, and review `render.yaml`.
3. Set secret environment variables in Render. Do not commit `.env`, provider keys, Google client secrets, or admin tokens.
4. Generate independent random values for `API_ACCESS_TOKEN`, `ADMIN_ACCESS_TOKEN`, and `SESSION_ENCRYPTION_KEY`. For the Fernet key, run locally: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
5. Configure Google OAuth authorized JavaScript origin to your exact Render HTTPS origin; set `GOOGLE_CLIENT_ID` and `PUBLIC_SITE_URL`.
6. After deploy, check `/health`, login, `/v1/models`, and one low-cost test call.

## OpenAI-compatible gateways

For each gateway, configure the upstream provider inside that gateway first. Then copy the gateway's **reachable HTTPS base URL**, its own issued API token, and an exact model ID from that gateway's model list into Render environment variables. Use `/v1` at the end of the base URL when the gateway expects OpenAI-compatible routes. The configured adapter constructs `/chat/completions` and `/models` from that base URL.

### LiteLLM

- Docs: https://docs.litellm.ai/docs/
- Quickstart: https://docs.litellm.ai/docs/proxy/docker_quick_start
- Configure upstream providers and create a restricted virtual key. Set `LITELLM_BASE_URL`, `LITELLM_API_KEY`, and `LITELLM_MODELS` (comma-separated exact model IDs).

### Ollama

- Docs: https://github.com/ollama/ollama
- API docs: https://github.com/ollama/ollama/blob/main/docs/api.md
- Ollama is a model runtime, not a free hosted API. Install it on a computer/server that can run the model, pull a model, and keep the server reachable. Set `OLLAMA_BASE_URL` to that server's URL and `OLLAMA_MODEL`/catalogue model name as applicable. On Render, `127.0.0.1` points back to the Render container, not your phone/home PC. Do not expose Ollama unauthenticated to the public internet.

### OmniRoute

- Project/docs: https://omniroute.hagicode.com/en-US/getting-started/quick-start/
- Install and configure providers on a host that supports the project. Set `OMNIROUTE_BASE_URL`, `OMNIROUTE_API_KEY`, and `OMNIROUTE_MODELS`.

### PawanOsman-compatible endpoint

- No endpoint is prefilled because the exact service/repository must be confirmed. Use only a service you control or are authorized to use. Verify its documentation supports OpenAI-compatible `/v1/models` and `/v1/chat/completions`; then set `PAWANOSMAN_BASE_URL`, `PAWANOSMAN_API_KEY`, `PAWANOSMAN_MODELS`.

### 9Router

- Docs: https://docs.9router.com/
- Host/configure the service according to its current documentation, create an API token, then set `NINE_ROUTER_BASE_URL`, `NINE_ROUTER_API_KEY`, and `NINE_ROUTER_MODELS`.

### New API

- Repository: https://github.com/QuantumNous/new-api
- Configure an authorized upstream channel and create a restricted token in its UI. Set `NEW_API_BASE_URL`, `NEW_API_API_KEY`, and `NEW_API_MODELS`.

### One API

- Repository: https://github.com/songquanpeng/one-api
- Configure an authorized upstream channel and create a token. Set `ONE_API_BASE_URL`, `ONE_API_API_KEY`, and `ONE_API_MODELS`. Change any default admin credentials immediately.

## Where to obtain provider API keys

These are official developer/account portals. Availability, billing, free quotas and supported models depend on provider/account/region; a URL is not a promise of free access.

- Google Gemini: https://aistudio.google.com/apikey
- OpenAI: https://platform.openai.com/api-keys
- Anthropic Claude: https://console.anthropic.com/
- DeepSeek: https://platform.deepseek.com/
- xAI: https://console.x.ai/
- Perplexity: https://www.perplexity.ai/settings/api
- Mistral: https://console.mistral.ai/
- Groq: https://console.groq.com/keys
- Cerebras: https://cloud.cerebras.ai/
- Hugging Face: https://huggingface.co/settings/tokens
- Cloudflare Workers AI: https://dash.cloudflare.com/ (account ID and API token required)
- GitHub Models: https://github.com/marketplace/models (access/token availability varies)
- Pollinations: https://pollinations.ai/ (check current API/auth/terms)

## Security and model routing

- Keep every provider/gateway key server-side in Render environment settings. Never put keys in frontend JS, HTML, a public repo, or a ZIP shared with users.
- Use HTTPS endpoints with valid TLS certificates. Do not use a public unauthenticated gateway or expose gateway admin dashboards.
- Use one selected model per normal request. A gateway may itself have routing/fallback configured; disable that if you need strict model identity and verify returned model metadata.
- Keys and credentials are not included in this archive. Test each connector separately before enabling it for users.
