# MAD X Hybrid Studio — integration registry

`registry.json` records the requested GitHub projects and other ecosystem candidates. Each entry is deliberately marked as native, configurable, external, reference-only, or requiring separate deployment. A repository link is not equivalent to installing its source code into this application.

## Safe integration pattern

1. Read the upstream README, license, release status and security advisories.
2. Deploy a separate external service where it has a different stack or large dependencies.
3. Connect it only through a documented API URL that you own or are authorised to use.
4. Keep all API keys/cookies on the server, authenticate the service connection, use HTTPS and apply resource limits.
5. Test provider availability and quotas; a free software license does not promise free hosting or model inference.

## Requested repositories

The new user-provided list appears in `registry.json`: BetterChatGPT, freegpt-webui, Buddo, youcoded, freemicro, OmniSearches and Free-GPT4-WEB-API. Some are separate frontends or framework projects, one is a hardware utility, and community provider wrappers can be unreliable. The hybrid app does not install or execute them automatically.

## Core routes

- `/v1/chat/completions`: one explicitly selected model only.
- `/v1/tasks/run`: six specialist roles; a failed role may retry once on a configured free-tier route. Fallbacks are reported.
- `/v1/files/upload`: generic byte upload; a model only receives content it can parse.
- `/v1/images/generations`: supported configured image adapters.
- `/v1/video/generate`: only works when a real video provider is available.

See the root `README.md` for environment variables, Google OAuth, production security and limitations.
