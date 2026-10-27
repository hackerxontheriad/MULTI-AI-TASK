# MADX v18 integration matrix

## Shipped in this archive

| Component | Status | Actual capability and limit |
|---|---|---|
| Direct provider API adapters | Implemented/configurable | Server-side documented API calls; valid keys, model access and quotas are required. |
| Local/hosted Ollama | Configurable | API adapter; the endpoint must be reachable from the server. `localhost` on Render is the Render container. |
| OpenAI-compatible endpoints | Configurable | Operator supplies a controlled base URL, server key and model list. Upstream service is not bundled. |
| Project Foundry | Implemented | Planner → explicitly routed tasks → validation → final ZIP. No incomplete ZIP is marked successful. |
| Database | Implemented | SQLAlchemy models for users, projects, task records and audit events; SQLite local fallback, PostgreSQL from `DATABASE_URL`. |
| Owner console | Implemented | Token exchange to short-lived HttpOnly cookie; protected diagnostics, summary and safe terminal allowlist. |
| Reverse Audit | Implemented | Static archive inventory and heuristics; no extraction, binary execution or proof of exploitability. |
| Kali security lab | Included as Docker recipe | Local isolated container for authorized lab work; not exposed as a hosted shell. |
| HTML/Java/PHP/Python preview examples | Templates | Examples only; they are not automatically launched as per-user isolated code-execution services. |
| Android wrapper | Source retained | APK has not been compiled or signed by this packaging workflow. |
| Google Flow / video | Not generally integrated | No private browser-session scraping; requires a supported video API adapter and account access. |

## Intentionally excluded

No G4F/GPT4Free, scraped browser sessions, copied provider cookies, arbitrary public shell or remotely fetched repository code is bundled. External repositories may be useful as design references, but are not dependencies and were not merged into the runtime.
