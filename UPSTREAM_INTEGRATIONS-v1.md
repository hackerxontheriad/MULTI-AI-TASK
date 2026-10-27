# MADX v18 integration inventory

This release uses native provider adapters in `provider_catalog.py`; the inventory below describes configuration boundaries, not code copied from other projects. Third-party source repositories are not downloaded or executed as part of deployment.

## Native functionality

- **Direct provider API adapters:** OpenAI, Gemini, Anthropic, xAI, Meta, DeepSeek, Perplexity, Groq, Cerebras, Mistral, GitHub Models, Hugging Face, Cloudflare Workers AI, Pollinations and configured local Ollama (actual availability depends on current provider API/model access).
- **User-operated compatible endpoints:** optional LiteLLM, OmniRoute, New-API, One-API and other compatible endpoints are enabled only when the operator supplies the base URL, key, and exact model IDs. These endpoint names are configuration hooks, not bundled services or a promise of free upstream inference.
- **Project Foundry:** planner output becomes concrete tasks with full work prompts, allowlisted file paths, explicit model routes and status/error records. ZIP packaging occurs only after every worker succeeds and path/size validation passes.
- **Static Reverse Audit:** ZIP/APK/AAB/JAR inventory, path traversal detection, endpoint and dependency extraction, selected Android manifest strings, and secret/shell/TLS heuristics. Archive contents are neither extracted nor executed.
- **Admin console:** short-lived signed HttpOnly admin cookie, diagnostics, audit-event summaries, database counts and allowlisted terminal commands. The user UI does not show admin diagnostics.
- **Kali lab:** disposable local Docker image in `security-lab/`; never attached to a public arbitrary-command endpoint.

## Deliberately not bundled

No GPT4Free/G4F, browser-login scraping, GitHub-sourced adapters, credential harvesting, or cross-provider cookie copying is shipped. Google sign-in uses the official web identity flow, and each AI provider requires an API route or provider-approved integration. The Google Flow site is not treated as a generic video API; video generation returns an honest unavailable result until a supported video adapter is configured.

## Verification

Offline tests mock API responses. They verify request formatting, token redaction, access control, task packaging, route validation, and static archive review. Provider quotas, Google OAuth settings, external gateway availability, and Render deployment require operator-provided secrets and a live smoke test.
