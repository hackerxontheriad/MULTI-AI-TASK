"""Transparent task-routing policy; aliases do not imply official model access."""
from typing import Any

AGENTS = {
    "general": {"label": "X1 Pro Light", "role": "Orchestrator", "power": "medium", "description": "Plans the task and selects a specialist. This is an app-level alias, not a real model."},
    "coding": {"label": "Coding Agent", "role": "Code, debugging, tests, APK/build guidance", "power": "high"},
    "research": {"label": "Research Agent", "role": "Search GitHub/docs/reports first, then summarize evidence", "power": "medium"},
    "reasoning": {"label": "Reasoning Agent", "role": "Break complex tasks into steps and check assumptions", "power": "high"},
    "creative": {"label": "Creative Agent", "role": "Writing, brainstorming, UI copy", "power": "low"},
    "media": {"label": "Media Agent", "role": "Video prompt planning and media workflow", "power": "medium"},
}
MODEL_ROLES = {
    "chatgpt": "general", "gemini": "research", "deepseek": "reasoning",
    "meta": "creative", "claude": "coding", "grok": "fallback", "perplexity": "research",
}
def plan_task(task: str, requested_agent: str = "general") -> dict[str, Any]:
    t = task.lower()
    if any(k in t for k in ("github", "repo", "repository", "report", "latest", "research", "search")):
        chosen = "research"
        steps = ["Check repository README, issues, releases, and security advisories when available", "Verify compatibility and license", "Summarize evidence, limitations, and next steps"]
    elif any(k in t for k in ("apk", "typescript", "tsx", "code", "debug", "build", "docker", "render")):
        chosen = "coding"
        steps = ["Inspect project files and environment", "Propose a minimal implementation", "Run available checks and report anything not verified"]
    elif any(k in t for k in ("video", "flow", "veo", "image-to-video", "text-to-video")):
        chosen = "media"
        steps = ["Validate the selected video provider and authentication", "Generate only if the provider reports a real result", "Upload to Drive only after successful generation"]
    else:
        chosen = requested_agent if requested_agent in AGENTS else "general"
        steps = ["Clarify the goal and constraints", "Delegate to a specialist if useful", "Check the result and explain limitations"]
    return {"agent": chosen, "agent_info": AGENTS[chosen], "model_role_hint": MODEL_ROLES.get(chosen, "orchestrator"), "steps": steps, "fallback": {"primary": "selected provider", "secondary": "grok", "trigger": "provider reports quota/rate-limit/unavailable before any answer is emitted", "notice_user": True}, "power_modes": ["low", "medium", "high"], "github_preflight": "For tasks about external repositories, check README, issues, releases, license and security reports before recommending implementation."}
