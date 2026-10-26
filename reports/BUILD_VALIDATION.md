# MAD X Hybrid Studio v17 — build/validation report

Date: 2026-10-26

## Checks performed in this environment

- `python -m pytest -q`: **77 tests passed** (offline tests; no paid model credits used).
- Python byte-compilation: `main.py`, `agents.py`, `provider_catalog.py`, `runtime_env.py`, `http_client.py`, `agent_router.py`, `scripts/audit_project.py`, `scripts/fetch_upstreams.py`, and `legacy/provider_gateway.py`: passed.
- `node --check`: `static/app.js`, `static/landing.js`, and `static/diagnostics.js`: passed.
- TestClient smoke checks: `/`, `/chat`, `/diagnostics`, `/robots.txt`, `/health`, and the authenticated connector-status route returned expected results; the connector route denied unauthenticated access with `REQUIRE_LOGIN=true` and accepted a bearer token without echoing the token.
- Confirmed both SVG logo paths exist; both icon PNG paths exist; the legacy MP4 is present; Android Gradle/Java/manifest/resources and HTML/Java/PHP/Python preview examples are present.
- Static ZIP audit against the original uploaded `madex-hybrid.zip`: 57 archive entries scanned. The scanner reports heuristic review candidates (including test-only fake key strings, subprocess invocations used for browser version/launch checks, and HTML string construction); findings are not proof of an exploitable vulnerability. The scanner does not execute archive contents.

## Not performed / blockers

- No live provider API calls, Google OAuth end-to-end test, Render deployment test, Docker build, or real image/video generation were performed.
- The build container has Node.js v22.16.0; current OmniRoute upstream documentation requires Node.js `>=22.22.2 <23` or `>=24 <27`. OmniRoute and its MCP server therefore were not installed or launched here.
- GitHub DNS/network resolution failed in the build container, so external repository source trees could not be fetched. Registry entries, setup notes, configurable gateway adapters, and an opt-in fetch script are included instead. The fetch script does not install or execute upstream code.
- The React/TSX source is included but was not built: its npm packages were not cached and outbound package installation was unavailable. Production `/` uses the included self-contained HTML/CSS/JS landing page.
- Android source is included, but the Android SDK, `adb`, and Gradle executable are unavailable; a signed APK was not compiled.
- A fully verified security audit would require dependency review, deployment configuration, live penetration testing within authorized scope, and review of actual secret-management settings. This report is a build check, not a security certification.
