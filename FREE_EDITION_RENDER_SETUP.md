# MADX Hybrid Studio Free Edition — Render Setup

This profile implements the selected configuration:

- AI execution: hybrid (eligible hosted free-tier APIs plus optional user-owned Ollama)
- Login: Google OAuth sign-in for the MADX app
- Storage: temporary/ephemeral; project ZIPs should be downloaded promptly
- Requests: one explicitly selected model per task request
- Fallbacks: disabled; quota/provider errors are returned instead of silently switching models
- Admin and user surfaces: separate interfaces and protected admin endpoints
- Paid API keys: not required; do not add them unless you intentionally choose to use a paid service

## Deploy

1. Push the entire repository to one GitHub repository.
2. In Render, choose **New + → Blueprint**, select the repository, and apply `render.yaml`.
3. Set the secret values listed below in the Render service environment. Do not commit them.
4. Set `MADX_DEFAULT_MODEL` to an exact model ID that appears in `/v1/models` after you configure at least one supported provider. Leave it empty until then; task execution will require an explicit model.
5. Deploy and check `/health`, then sign in and test one model at a time.

## Required Google OAuth configuration

1. Open Google Cloud Console and create/select a project.
2. Configure the OAuth consent screen and create an OAuth client of type **Web application**.
3. Add your Render URL to **Authorized JavaScript origins**, e.g. `https://YOUR-SERVICE.onrender.com`.
4. Copy the OAuth client ID to Render's `GOOGLE_CLIENT_ID` variable.
5. Set `PUBLIC_SITE_URL` to the exact HTTPS Render URL.
6. Optionally set `ALLOWED_LOGIN_EMAILS` to a comma-separated allowlist. This is recommended for an admin-only early deployment.
7. Generate unique secrets for `API_ACCESS_TOKEN`, `ADMIN_ACCESS_TOKEN`, and `SESSION_ENCRYPTION_KEY`. Never reuse the Google client secret as any of these values. If the app's sign-in flow uses Google's ID credential, configure the client ID and authorized origin; do not collect a Google password in MADX.

Google sign-in authenticates the user to MADX only. It does **not** sign the user into Gemini, ChatGPT, Claude, Grok, Meta AI, Perplexity, or Google Flow.

## Secrets and key generation

Generate random access tokens with Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate a Fernet session-encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the outputs in Render Environment. Do not paste them into chat, frontend JavaScript, or the repository.

## Free-tier provider setup

Free access is provider/account/region dependent and may require a provider-issued key. Add only keys you have permission to use, such as eligible Gemini, Groq, Cerebras, Mistral, GitHub Models, Hugging Face, or Cloudflare access. A free-tier key is still an API key, but it does not automatically mean unlimited usage or zero-cost overages; check each provider's current terms and billing settings.

For Ollama, set `OLLAMA_BASE_URL` to an HTTPS endpoint for a machine/server you control and that is reachable from Render. `127.0.0.1` on Render points to the Render container, not your phone or home computer. Do not expose Ollama unauthenticated to the public internet. If no remote Ollama is available, leave it blank and use the configured hosted free-tier provider.

For LiteLLM, OmniRoute, PawanOsman-compatible APIs, 9Router, New-API, or One-API, set their base URL and API key only after you host/configure that gateway separately. The connector adapter does not host those services for you.

## No-fallback behavior

`MADX_FREE_EDITION=true` and `MADX_DISABLE_FALLBACK=true` are enabled by `render.yaml`. If a provider reaches quota, is unavailable, or returns an error, MADX returns the error and does not silently route to another model. `/v1/tasks/run` accepts only one selected route in this profile. The six task roles, if used, run against that same selected model; they are not six independent provider logins.

## Temporary storage warning

`MADX_DATA_DIR=/tmp/madx-data` is intentionally temporary. Files and SQLite data may disappear when Render restarts/redeploys or its instance is replaced. Download generated ZIPs promptly. Do not store critical user data in this profile. Render free web services may sleep when idle; free database offerings, if added, have their own limits/expiry. This profile does not create a persistent database automatically.

## Smoke tests

```bash
curl -i https://YOUR-SERVICE.onrender.com/health
curl -i https://YOUR-SERVICE.onrender.com/v1/models \
  -H "Authorization: Bearer YOUR_API_ACCESS_TOKEN"
```

A healthy web service does not prove that a provider key, model, OAuth origin, or quota is valid. Test each configured integration individually. Never expose provider keys in browser code or logs.
