# Agent roles, coding environment, and Android wrapper

## Agent routing
`POST /api/agents/plan` returns a transparent task plan with role and power mode:
- X1 Pro Light: app-level orchestrator alias; not a real model or guaranteed provider.
- Coding Agent: code, Docker, Render, APK/build help.
- Research Agent: repository README/issues/releases/license/security-report preflight.
- Reasoning Agent: decomposition and consistency checks.
- Creative Agent: writing/UI.
- Media Agent: video workflow.
- Grok is the configured fallback hint when a provider quota/rate-limit error is detected. This routing policy is currently planning metadata; it does not magically create model access or guarantee quota detection across unofficial providers.

## Android
This repository is a responsive browser app and can be installed as a PWA from a compatible browser. It does **not** include a compiled APK. A signed APK needs an Android SDK/Gradle build environment and package signing. The source code for an optional Android WebView wrapper can be added as a separate Android Studio project, but it must point to your deployed HTTPS URL and be built/signed with your own keystore. Never put OAuth client secrets or provider tokens inside an APK.

## Render environment variables
Required:
- `GOOGLE_CLIENT_ID` — Google OAuth web client ID.
- `SESSION_ENCRYPTION_KEY` — generated Fernet key; keep private.
- `PUBLIC_SITE_URL` — deployed HTTPS origin.
- `COOKIE_SECURE=true`
Optional:
- `SESSION_DAYS=30`

Do not commit `.env`, browser storage-state JSON, access tokens, signing keystores, or session encryption keys.
