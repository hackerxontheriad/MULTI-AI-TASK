# Hybrid integration inventory (MadEx Workspace + Multi-Provider AI Hub)

## What is merged
- Original MadEx Workspace UI, Google sign-in/session, chat history, Google Drive upload route, legal pages, logo/icon, and existing workspace API.
- Multi-Provider Hub catalog/adapters, TLS/CA helpers, runtime/Chromium discovery, provider diagnostics, and agent orchestration modules.
- Workspace chat now calls the provider gateway internally; it no longer relies only on the old single g4f streaming path.
- `/api/providers` returns the available catalog, `/api/diagnostics` returns installed-library/runtime diagnostics after sign-in, `/api/chat-link` returns `CHAT_PUBLIC_URL`, and `/api/tasks/run` runs the planner/worker/synthesizer agent workflow.
- The UI loads explicit text routes from `/api/providers`. The selected route is attempted first; configured official/free-tier provider routes may be tried as fallback. Provider keys are never returned by diagnostics.

## Repository inventory
These are integrations/pattern references, not all vendored source trees. Pulling 20+ unrelated full applications into one process would create dependency, security, license, and deployment conflicts. Their ideas are used selectively; each repo's own license must be reviewed before redistributing its code.

| Repository | Link | Status in this ZIP |
|---|---|---|
| ai-agent-comparison | https://github.com/Vigneshmaradiya/ai-agent-comparison | Comparison concept/reference; not vendored |
| CrewAI-Langgraph-Projects | https://github.com/charithmadhuranga/CrewAI-Langgraph-Projects | Graph/workflow reference; native workflow used |
| crewAI-examples | https://github.com/crewAIInc/crewAI-examples | Role/task pattern reference; not vendored |
| mcp-memory-service | https://github.com/doobidoo/mcp-memory-service | Not installed; persistent MCP memory service remains optional future integration |
| full-stack-ai-agent-template | https://github.com/vstorm-co/full-stack-ai-agent-template | FastAPI/Docker pattern reference |
| agentops | https://github.com/AgentOps-AI/agentops | Not installed; observability library optional |
| CrewAI-Studio | https://github.com/strnad/CrewAI-Studio | Not installed; separate Streamlit UI |
| AgentsCrashCourse | https://github.com/ddavid37/AgentsCrashCourse | Learning/reference repository, not runtime dependency |
| innovation-lab-examples | https://github.com/fetchai/innovation-lab-examples | A2A pattern reference; not vendored |
| academic-commercialization-agent | https://github.com/shuxiachai/academic-commercialization-agent | Domain-specific example; not vendored |
| caspian-sdk | https://github.com/TryCaspian/caspian-sdk | Not installed; messaging SDK unrelated to core chat runtime |
| LibreChat | https://github.com/LibreChat-AI/LibreChat | Separate full-stack app; not merged into FastAPI process |
| big-AGI | https://github.com/enricoros/big-AGI | UI/model-router reference; not vendored |
| MetaGPT | https://github.com/geekan/MetaGPT | Software-agent reference; not installed due heavyweight dependency/runtime footprint |
| rea | https://github.com/morluto/rea | Binary-analysis tool; not installed |
| awesome-multi-agent-papers | https://github.com/kyegomez/awesome-multi-agent-papers | Research list only |
| g4f / GPT4Free | https://github.com/xtekky/gpt4free | Optional dependency; community routes experimental |
| Open Interpreter | https://github.com/KillianLucas/open-interpreter | Not installed; arbitrary local code execution requires separate sandbox and explicit opt-in |
| ComfyUI | https://github.com/comfyanonymous/ComfyUI | Not bundled; connect a separately hosted ComfyUI endpoint for image/video workflows |
| Fooocus | https://github.com/lllyasviel/Fooocus | Not bundled; separate GPU application |
| AUTOMATIC1111 WebUI | https://github.com/AUTOMATIC1111/stable-diffusion-webui | Not bundled; separate GPU application |

## Provider support
Optional provider adapters in the merged gateway include Groq, Cerebras, Mistral, Gemini, GitHub Models, Hugging Face Inference Providers, Cloudflare Workers AI, Pollinations, NVIDIA NIM, OpenRouter Free, PawanOsman-compatible endpoints, LiteLLM proxies, and Ollama. A provider is usable only when its service is reachable and any required key/account/model is configured. “Free” means a provider may offer a free tier, not unlimited free compute.

## Diagnostics
- `GET /health`: lightweight service health.
- `GET /api/diagnostics` after sign-in: Python library presence/version, TLS CA source, configured provider names, browser probe skipped by default, and executable discovery.
- `GET /api/diagnostics?probe=true` after sign-in: additionally attempts a Chromium launch. This can consume memory and may fail on a 512 MB free host.
- `GET /api/providers` after sign-in: current catalog and provider configuration summary.
- `GET /api/chat-link`: current `CHAT_PUBLIC_URL`.

## Custom domain
Set `CHAT_PUBLIC_URL=https://chat.mysitelink.com`, then add `chat.mysitelink.com` as a custom domain in your hosting dashboard and create the DNS record it specifies. The URL variable does not register the domain or create DNS automatically. For Render, use the exact target Render displays in its custom-domain instructions. Update Google OAuth Authorized JavaScript origins and redirect/allowed origins to the actual deployed domain.
