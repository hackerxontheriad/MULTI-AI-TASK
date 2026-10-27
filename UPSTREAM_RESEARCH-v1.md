# MADX v18 provider and workflow notes

This file is a status note, not a claim that every external provider has been live-tested. No source code is fetched from the projects mentioned by name, and no browser-session wrapper is part of the supported runtime.

## Provider adapter policy

Use documented provider APIs or an endpoint the operator owns/is authorized to use. Provider keys stay in server environment variables. A configured key or free-tier label does not guarantee model access, credits, regional availability, or uptime. Every explicit generation request targets one provider/model; the system records the failed route instead of silently substituting another provider. `auto` resolves once to a single configured route and does not retry a different model after an error.

## Hosted and local connectors

- Direct adapters in `provider_catalog.py` cover a curated catalog of APIs including OpenAI, Gemini, Anthropic, xAI, Meta, DeepSeek, Perplexity, Groq, Cerebras, Mistral, GitHub Models, Hugging Face, Cloudflare Workers AI, Pollinations and Ollama. Verify the provider's current model catalogue before relying on a preset identifier.
- OpenAI-compatible connectors (such as a privately-operated LiteLLM or gateway deployment) require a controlled base URL, server-side key and an explicit model list. The connector does not make that service free.
- Video generation remains unconfigured until a supported provider API adapter is installed and its credentials/entitlements are supplied. Google Flow web UI sessions are not scraped or impersonated.

## Engineering choices

The project uses a small native task orchestrator rather than bundling several overlapping multi-agent frameworks. `Project Foundry` has a planner, task distribution, selected-model workers, output validation and deterministic ZIP packaging. Reverse Audit is static-only. Kali runs locally in a container with restricted capabilities; it is not an online shell.

## Verification status

The test suite is offline and uses mocks; a passing test run does not establish live API access, provider quotas, OAuth app correctness, or a successful Render deployment.
