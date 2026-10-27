# Changelog

## v18.0.0 — MADX Hybrid Studio (2026-10-27)

- Added SQLAlchemy persistence for users, projects, project task records and audit events; SQLite is the local fallback and PostgreSQL is selected via `DATABASE_URL`.
- Added Project Foundry: planner-produced full task prompts, explicit model-worker routing, file allowlists, output validation, task status/error records and ZIP packaging after a fully successful run.
- Added a liquid emerald/metallic-green/gold Builder page, dedicated Google auth page, and static ZIP/APK/AAB/JAR Reverse Audit page.
- Added a separately protected admin console with URL-token-to-cookie exchange, diagnostics, database/project summary, audit events and an allowlisted terminal.
- Added a local-only Docker Kali lab; no arbitrary shell/Kali command endpoint is exposed publicly.
- Removed legacy browser-session/G4F wrapper paths and old public diagnostics assets; retained strict rejection of legacy route identifiers.
- Updated Render/Docker configuration and deployment guidance, and refreshed regression tests.
- Validation: offline tests, syntax checks and smoke tests pass in the build environment; live provider/auth/deployment status still depends on operator configuration.

## v17.0.0 and earlier

The prior hybrid UI, provider catalog, agent workflow, preview examples, Android wrapper assets and logos are retained where compatible. Old runtime wrapper/deep-diagnostics behavior has been replaced by the v18 security boundaries.
