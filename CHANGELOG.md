# Changelog — v14.1

This package replaces the two supplied MULTI-AI-TASK ZIP versions with one consistent project layout.

- Replaced fixed provider-name claims with a live `g4f-working` provider/model catalog and a small fallback list.
- Removed direct OpenRouter/KiloCode aliases; no commercial provider API keys are configured.
- Added `/health`, `/v1/status`, `/v1/catalog`, `/v1/catalog/refresh`, `/v1/models`, chat, image, and video endpoints.
- Added a phone-friendly web UI with Chat, Image, and Video tabs, live catalog counts, diagnostics, and optional app token input.
- Replaced the old fake-video success behavior (a downloaded sample MP4 or fabricated MP4 header) with capability detection and an honest HTTP 503 when no real keyless video API is available.
- Added a Dockerfile with Chromium and browser system dependencies for providers that use browser automation.
- Added optional app-token protection for generation endpoints and bounded provider-worker capacity.
- Added offline unit tests and a network smoke test.

The wrapper does not guarantee that any public provider will work on a given day. Live generation has to be tested in the target environment with internet access and a working g4f install.
