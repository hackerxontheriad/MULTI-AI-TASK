# MAD X v17 integration matrix (2026-10-26)

## Native/implemented in this archive

| Connector | Status | What is actually implemented |
|---|---|---|
| Official/free-tier HTTP provider adapters in `provider_catalog.py` | Configurable | Server-side API calls; key must be configured and quota/provider availability varies. |
| Local/hosted Ollama | Configurable | Native API adapter; remote host and optional key required when not local. |
| LiteLLM Proxy / PawanOsman-compatible endpoint | Configurable | OpenAI-compatible API base URL and key are used server-side. |
| OmniRoute | Configurable HTTP adapter + MCP setup guide | Add OMNIROUTE_BASE_URL / OMNIROUTE_API_KEY / OMNIROUTE_MODELS; run OmniRoute separately and create an endpoint key there. |
| New-API / One-API | Configurable HTTP adapters | Each needs a separately deployed instance, model IDs and key. The upstream services are not embedded into the Python runtime. |
| 9Router | Adapter scaffold only | Exact repository owner/url and API contract were not specified, so this is not verified as working. |
| G4F community provider wrapper | Optional/experimental | Listed by runtime diagnostics if installed; no promise of access, uptime or unlimited use. It is not the default production recommendation. |
| Six-agent task lane | Native | Planner, researcher, builder, reviewer, optimizer, tester; actual provider route configuration and quotas still apply. |
| HTML/SVG preview | Native | Copy, download, Run and Preview in a sandboxed iframe. It is not a general remote code execution environment. |
| HTML/Java/PHP/Python runner examples | Included | Docker examples and snippets are templates only; not automatically launched or isolated as per-user runtime services. |
| Android wrapper | Source included | Gradle/Java/manifest/resources are present. APK has not been compiled or signed in this environment. |
| Browser/ZIP/APK static audit | Included | `scripts/audit_project.py` scans without executing archive contents. Heuristic findings require review. |

## External projects listed, not vendored

The registry includes BetterChatGPT, freegpt-webui, Buddo, youcoded, freemicro, OmniSearches, Free-GPT4-WEB-API, OmniRoute, New-API, One-API and previous agent/media/reference projects. Their full source trees are **not** in this ZIP. Automatic downloading failed in the build environment because outbound GitHub DNS/network access was unavailable, and cloning all sources into the app would create license, dependency, size and runtime-isolation risks. `scripts/fetch_upstreams.py` is an explicit opt-in shallow clone helper; it clones source but does not install or run it.

The `9Router` name lacks an exact upstream repository URL. The ten other newly named repository paths are pinned in that helper and `integrations/repositories.txt`.

## Separate report files

The two uploaded ZIPs were inspected. No additional 10–14 standalone reports were attached as separate files in this turn, so they are not claimed as reviewed. Existing upstream research documents were preserved in the package.
