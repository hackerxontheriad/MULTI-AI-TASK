# MADX Hybrid Studio v18 — build/validation report

The package contains a FastAPI runtime, static responsive frontend, SQLAlchemy persistence, selected provider API adapters, Project Foundry, static Reverse Audit, a protected admin console, Render configuration and a separate local Kali Docker lab.

Validation is performed with the included offline test suite, Python compilation, JavaScript syntax checks, JSON parsing, archive integrity and route smoke tests. Tests mock provider APIs; no provider keys, OAuth credentials or live account sessions are provisioned by this package. Render hosting/deployment and actual provider quotas must be checked after configuration by the owner.
