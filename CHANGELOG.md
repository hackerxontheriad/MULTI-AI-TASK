# Changelog

## v17.0.0 — MAD X hybrid merge (2026-10-26)

- Merged both supplied ZIPs using v16.1 single-route FastAPI as the active runtime and preserved old gateway code separately under `legacy/` to avoid overriding the active routes.
- Restored `static/assets/logo-mark.svg`, `static/assets/madex-icon.png`, the original `logo-demo.mp4`, `robots.txt`, the original landing page as `legacy/static/landing-v1.html`, and the old hub page.
- Rebuilt `static/landing.html` with emerald glass styling, animated reveal effects, MP4 film section, old/new logo marks, feature cards and secure workspace/diagnostics CTAs. Added companion React/TSX source under `frontend/`.
- Added `Run` next to Copy/Download/Preview for HTML/SVG code blocks; execution occurs in an opaque sandboxed iframe, not in the parent app origin.
- Added configurable OpenAI-compatible routes for OmniRoute, 9Router scaffold, New-API and One-API, including environment placeholders and Render settings.
- Added connector status endpoint and a diagnostics dashboard; it never returns provider key values. Configured vs reachable status is distinguished.
- Added OmniRoute MCP setup guide and example client configuration; OmniRoute remains a separate runtime and token creation/rotation remains upstream.
- Added a non-executing ZIP/APK static audit helper and an opt-in upstream fetch script that never installs or executes fetched repository code.
- Preserved Android wrapper, HTML/Java/PHP/Python preview examples and existing file/chat/agent/media code.
- Added security/limitations and integration matrix reports. External repository source trees were not copied wholesale; the build environment could not reach GitHub, and some repositories require separate services, license review, GPUs or incompatible stacks.

## v16.1.0 — MAD X Hybrid Studio (2026-10-26)

- Added multi-page chat, six-agent task workflow, uploads/file library, Google verified sign-in, diagnostics protection, provider catalog and single-model gateway foundation.
- Added emerald/metallic visual style, code blocks with copy/download, sandboxed HTML preview, integration registry and mobile-friendly Android WebView wrapper source.
- Baseline validation: 76 offline tests, Python compile and JavaScript syntax checks passed before the v17 merge. Live OAuth, provider quotas and hosted integrations require independent configuration/verification.

## v16.0 and earlier

See the preserved v16.1 history in repository archives or upstream research notes for prior provider, environment and diagnostics changes.
