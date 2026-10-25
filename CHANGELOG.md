# Changelog

## v15.2.0 — 2026-10-25

- Fixed stale Chromium environment overrides masking an available executable.
- Improved hints for shared Chrome startup and DBus/container warnings; does not claim DBus alone is always fatal.
- Normalised g4f provider IDs with copied whitespace such as `g4f: GoogleAiMode|...`.
- Added configurable LiteLLM Proxy and PawanOsman-compatible OpenAI API routes that require an explicit authorized base URL and key.
- Documented that DuckDuckGo AI Chat is not called through an unsupported scraping route; documented remaining community-provider limitations.
- Expanded offline regression tests to cover these fixes.


## v15.1.0 — 2026-10-25

- **Agents**: new `/v1/agents/run` with Compare, Council (debate + judge) and Planner (planner → workers → synthesiser) modes;
  every agent bound to a caller-chosen route, no fallback, 16-call budget, untrusted-peer-text guard.
- **Free routes**: Groq, Cerebras, Mistral, GitHub Models, Hugging Face, Cloudflare Workers AI, Pollinations (text + image),
  Ollama live model discovery; Gemini marked free-tier. Real image routes (Pollinations, Cloudflare) without a browser.
- **Chromium**: real binary detection, stale env cleanup, container-safe wrapper (`scripts/chromium-safe`), launch probe in `/v1/diagnostics`.
- **SSL/network**: CA bundle setup, same-URL bounded retries, actionable error hints, certificate failures never retried or bypassed.
- **Security**: Gemini key moved from URL to header; all client-visible errors redacted; constant-time token check; rate limiter; non-root Docker user.
- **Fixes**: `.env` now actually loaded; separate official/g4f worker pools with busy detection; role/temperature/token-param normalisation per provider;
  fast `/health`; shorter retry after failed catalog fetch; Docker pinned to bookworm without hand-listed libs; lite install path for 512 MB hosts.
- **Frontend**: Agents tab (mode cards, route picker with Free & ready first, result cards, copy buttons), grouped model selector,
  image models from catalog, real diagnostics panel, toasts, hints in error messages, text rendered via `textContent` only.
- Tests: 62 offline tests (was 20).

## v15.0.0 — 2026-10-24

- Added curated official API routes for OpenAI, Gemini, Claude, xAI Grok, Meta Model API, DeepSeek and Perplexity.
- Added provider-native model-list discovery, local Ollama routes and clearly marked community presets.
- Enforced single-route behavior for text, image and video.

## v14.1.0

- Single-model text route behavior; mobile UI, keyless-community catalog, image experiments and conservative video capability checks.
