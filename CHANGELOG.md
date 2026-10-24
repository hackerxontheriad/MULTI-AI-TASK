# Changelog

## v15.0.0 — 2026-10-24

- Added curated official API routes for OpenAI, Gemini, Claude, xAI Grok, Meta Model API, DeepSeek and Perplexity.
- Added provider-native model-list discovery when that provider's server-side key is configured.
- Added local Ollama routes for Llama/Qwen/Mistral and other installed local chat models.
- Added clearly marked community presets for ChatGPT web, Gemini, Claude, Grok, MetaAI and other g4f adapters.
- Enforced single-route behavior for text, image and video: no gateway-level model/provider fallback.
- Explicit g4f provider selection now returns an error if that adapter is missing instead of allowing g4f to choose another provider.
- Updated UI labels, server-side credential guidance, tests, docs and validation artifacts.

## v14.1.0

- Single-model text route behavior; requested provider/model failures returned without gateway-level fallback.
- Mobile UI, keyless-community catalog, image experiments and conservative video capability checks.
