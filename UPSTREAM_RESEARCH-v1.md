# Upstream provider and agent research (v15.3)

This file records the public integration references reviewed for this release. It is not a claim that every upstream service was live-tested from this build environment.

## Provider adapters

- **GPT4Free / g4f** — https://github.com/xtekky/gpt4free and https://g4f.dev/docs/ . Optional community adapter; upstream providers can be unstable, require sessions/browser support, and may change frequently. Catalog entries are explicitly marked experimental.
- **PawanOsman ChatGPT API** — https://github.com/PawanOsman/ChatGPT . Supports an OpenAI-compatible API; the upstream README documents `https://api.pawan.krd/v1` for its hosted service and describes obtaining access. We expose it as an opt-in credentialed route and also preserve custom self-hosted endpoint configuration.
- **LiteLLM** — https://docs.litellm.ai/docs/ . Exposed as a user-configured LiteLLM Proxy route. LiteLLM normalizes providers; it does not guarantee that a configured upstream is free.
- **Hugging Face Inference Providers** — https://huggingface.co/docs/inference-providers/index . Uses the documented OpenAI-compatible `https://router.huggingface.co/v1` chat endpoint with a server-side token. The free tier currently advertises small monthly credits; this is not unlimited inference.
- **Ollama** — https://github.com/ollama/ollama/blob/main/docs/api/introduction.mdx . Uses the documented local `/api/chat` API, with live discovery of installed models.
- **NVIDIA NIM** — https://docs.api.nvidia.com/nim/reference/llm-apis and https://docs.api.nvidia.com/nim/reference/openai-gpt-oss-20b-infer . Uses NVIDIA's OpenAI-compatible `/v1/chat/completions` endpoint; developer-program access is for prototyping and model/quotas can vary.
- **OpenRouter Free** — https://openrouter.ai/collections/free-models . Exposed only through the named adapter. Live model discovery filters for zero-priced prompt and completion metadata (or an explicit `:free` suffix); provider availability and quotas can change.
- **DuckDuckGo AI Chat** — no stable, documented public chat-completion endpoint is included here. We do not scrape private browser endpoints, bypass bot checks, or pretend that web search is an AI generation provider.

The existing direct adapters for Groq, Cerebras, Mistral, Gemini, GitHub Models, Cloudflare Workers AI, Pollinations, OpenAI, Anthropic, xAI, Meta, DeepSeek and Perplexity remain in `provider_catalog.py`.

## Agent orchestration patterns reviewed

- **LangGraph** — https://github.com/langchain-ai/langgraph (resilient graph-style agent orchestration).
- **AgentScope** — https://github.com/agentscope-ai/agentscope (observable agent workflows).
- **AG2 / AutoGen** — https://github.com/ag2ai/ag2 (multi-agent coordination).
- **Google ADK Python** — https://github.com/google/adk-python (code-first agent framework).

The shipped implementation in `agents.py` remains a small native orchestration layer (compare, council/review, and planner/workers/synthesiser) so this lightweight API can run without pulling in several large, overlapping frameworks. The patterns are adapted, not wholesale-vendored code; consult upstream repositories and their licenses before integrating any code from them. The orchestration enforces route selection, call budgets, parallelism caps and untrusted-peer-text handling.

## Honest verification status

- Offline unit tests mock provider HTTP responses and browser executables; they verify request formatting, error mapping, TLS retry behavior, catalog filtering, fallback metadata and agent orchestration.
- Unit tests do **not** prove a real account key, real quota, upstream availability, Chromium dependencies on a host, or Render deployment. Use `/v1/diagnostics` and a small live smoke test after configuring credentials.
