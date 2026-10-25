"""Offline tests for multi-agent orchestration (stub models; no network, no quota)."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agents
import main


def run(coro):
    return asyncio.run(coro)


def make_chat(script, calls):
    """script: route -> str | Exception | callable(messages)->str. Records every call."""
    async def chat(route, messages, temperature, max_tokens):
        calls.append((route, messages))
        value = script[route]
        if callable(value):
            value = value(messages)
        if isinstance(value, BaseException):
            raise value
        return value, route.split("|")[-1], route.split("|")[0], []
    return chat


def describe(exc):
    return {"status": 502, "error": "failed", "message": str(exc), "hint": None}


def go(mode, calls, script, **kw):
    args = dict(mode=mode, prompt="Q?", routes=[], judge=None, planner=None, rounds=1, max_subtasks=4,
                temperature=0.5, max_tokens=300, chat=make_chat(script, calls), describe_error=describe)
    args.update(kw)
    return run(agents.run_agents(**args))


def test_compare_runs_each_route_once_and_reports_failures_without_fallback():
    calls = []
    out = go("compare", calls, {"A|a": "answer A", "B|b": RuntimeError("down"), "C|c": "answer C"},
             routes=["A|a", "B|b", "C|c"])
    assert [c[0] for c in calls] == ["A|a", "B|b", "C|c"]          # exactly the chosen routes, once each
    assert out["succeeded"] == 2 and out["failed"] == 1 and out["fallback_used"] is False
    failed = [a for a in out["agents"] if not a["ok"]][0]
    assert failed["route"] == "B|b" and "down" in failed["error"]["message"]


def test_council_two_rounds_and_judge_sees_revised_answers():
    calls = []
    script = {"A|a": lambda m: "revised A" if "Peer answers" in m[-1]["content"] else "first A",
              "B|b": lambda m: "revised B" if "Peer answers" in m[-1]["content"] else "first B",
              "J|j": "FINAL"}
    out = go("council", calls, script, routes=["A|a", "B|b"], judge="J|j", rounds=2)
    assert out["final"]["text"] == "FINAL" and out["calls_made"] == 5
    judge_prompt = [c for c in calls if c[0] == "J|j"][0][1][-1]["content"]
    assert "revised A" in judge_prompt and "revised B" in judge_prompt and "first A" not in judge_prompt
    assert "UNTRUSTED" in [c for c in calls if c[0] == "J|j"][0][1][0]["content"]


def test_council_failed_member_is_not_replaced_and_judge_still_runs_with_survivors():
    calls = []
    out = go("council", calls, {"A|a": "good", "B|b": RuntimeError("quota"), "J|j": "merged"},
             routes=["A|a", "B|b"], judge="J|j")
    assert out["members_succeeded"] == 1 and out["members_failed"] == 1 and out["final"]["text"] == "merged"
    assert sorted(c[0] for c in calls) == ["A|a", "B|b", "J|j"]


def test_council_all_members_failed_skips_judge():
    calls = []
    out = go("council", calls, {"A|a": RuntimeError("x"), "B|b": RuntimeError("y"), "J|j": "never"},
             routes=["A|a", "B|b"], judge="J|j")
    assert out["final"]["ok"] is False and out["final"]["error"]["error"] == "no_member_answers"
    assert "J|j" not in [c[0] for c in calls]


def test_failed_revision_keeps_first_answer_and_reports_error():
    calls = []
    state = {"n": 0}

    def flaky(m):
        if "Peer answers" in m[-1]["content"]:
            raise RuntimeError("revision failed")
        return "first A"

    out = go("council", calls, {"A|a": flaky, "B|b": "first B", "J|j": "done"}, routes=["A|a", "B|b"], judge="J|j", rounds=2)
    rev = out["stages"][1]["agents"]
    assert rev[0]["text"] == "first A"          # not silently dropped, not replaced by another model
    assert out["final"]["text"] == "done"


def test_plan_assigns_workers_deterministically_and_synthesises():
    calls = []
    plan = json.dumps({"subtasks": [{"role": "Researcher", "task": "t1"}, {"role": "Writer", "task": "t2"}, {"role": "Critic", "task": "t3"}]})
    out = go("plan", calls, {"P|p": plan, "W1|w": "r1", "W2|w": "r2", "S|s": "synth"},
             routes=["W1|w", "W2|w"], planner="P|p", judge="S|s")
    workers = [c[0] for c in calls if c[0].startswith("W")]
    assert workers == ["W1|w", "W2|w", "W1|w"]
    assert out["final"]["text"] == "synth" and out["workers_succeeded"] == 3 and out["calls_made"] == 5


def test_plan_defaults_synthesiser_to_planner_and_says_so():
    calls = []
    plan = '```json\n{"subtasks":[{"role":"R","task":"do it"}]}\n```'
    out = go("plan", calls, {"P|p": lambda m: plan if "planning agent" in m[0]["content"] else "synth by planner", "W|w": "r"},
             routes=["W|w"], planner="P|p")
    assert out["synthesiser_defaulted_to_planner"] is True and out["final"]["text"] == "synth by planner"


def test_plan_with_invalid_json_returns_error_not_a_made_up_plan():
    calls = []
    out = go("plan", calls, {"P|p": "sure! here is my plan: step one...", "W|w": "x"}, routes=["W|w"], planner="P|p")
    assert out["error"]["error"] == "planner_invalid_plan" and out["workers"] == []
    assert "W|w" not in [c[0] for c in calls]


def test_parse_plan_variants_and_limits():
    assert agents.parse_plan('{"subtasks":[{"role":"a","task":"b"}]}', 3)[0]["task"] == "b"
    assert agents.parse_plan('[{"task":"only"}]', 3)[0]["role"] == "specialist"
    assert len(agents.parse_plan(json.dumps({"subtasks": [{"task": str(i)} for i in range(9)]}), 3)) == 3
    for bad in ("", "no json", '{"subtasks": []}', '{"subtasks":[{"role":"x"}]}'):
        with pytest.raises(ValueError):
            agents.parse_plan(bad, 3)


def test_request_validation_blocks_wasteful_or_ambiguous_requests():
    for kw in (dict(mode="compare", routes=["A|a"]),
               dict(mode="compare", routes=["A|a", "a|A"]),
               dict(mode="council", routes=["A|a", "B|b"]),
               dict(mode="compare", routes=["A|a", "B|b", "C|c", "D|d", "E|e", "F|f", "G|g"]),
               dict(mode="plan", routes=["W|w"])):
        with pytest.raises(agents.AgentPlanError):
            agents.validate_request(kw["mode"], kw["routes"], kw.get("judge"), kw.get("planner"), kw.get("rounds", 1))


def test_call_budget_is_enforced():
    calls = []
    runner = agents.Runner(chat=make_chat({"A|a": "x"}, calls), describe_error=describe, temperature=0.5, max_tokens=100,
                           budget=agents.Budget(limit=1))
    first = run(runner.call("m", "A|a", "", "q"))
    second = run(runner.call("m", "A|a", "", "q"))
    assert first["ok"] and not second["ok"] and second["error"]["error"] == "agent_call_budget" and len(calls) == 1


# ------------------------------ HTTP-level wiring ------------------------------ #
def test_endpoint_runs_compare_through_the_real_single_route_gateway(monkeypatch):
    seen = []

    async def fake_official(fn, *args, timeout):
        seen.append((args[0], args[1]))
        return f"reply from {args[1]}"

    monkeypatch.setattr(main, "_run_official_thread", fake_official)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_testtesttesttest1234")
    monkeypatch.setenv("MISTRAL_API_KEY", "m" * 16)
    req = main.AgentRequest(mode="compare", prompt="hi", routes=["Groq API|llama-3.3-70b-versatile", "Mistral API|mistral-small-latest"])
    out = run(main.agents_run(req, None))
    assert out["succeeded"] == 2 and out["fallback_used"] is False
    assert seen == [("Groq API", "llama-3.3-70b-versatile"), ("Mistral API", "mistral-small-latest")]


def test_endpoint_reports_missing_key_per_agent_without_rerouting(monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_testtesttesttest1234")

    async def fake_official(fn, *args, timeout):
        if args[0] == "Cerebras API":
            return fn(*args)  # real adapter -> ProviderCredentialsMissing
        return "ok from groq"

    monkeypatch.setattr(main, "_run_official_thread", fake_official)
    req = main.AgentRequest(mode="compare", prompt="hi", routes=["Groq API|llama-3.3-70b-versatile", "Cerebras API|gpt-oss-120b"])
    out = run(main.agents_run(req, None))
    bad = [a for a in out["agents"] if not a["ok"]][0]
    assert bad["route"] == "Cerebras API|gpt-oss-120b" and bad["error"]["error"] == "provider_credentials_missing"
    assert out["succeeded"] == 1


def test_endpoint_rejects_router_aliases_and_bad_plans():
    with pytest.raises(HTTPException) as info:
        run(main.agents_run(main.AgentRequest(mode="compare", prompt="x", routes=["openrouter/free", "A|a"]), None))
    assert info.value.status_code == 400
    with pytest.raises(HTTPException) as info:
        run(main.agents_run(main.AgentRequest(mode="council", prompt="x", routes=["A|a", "B|b"]), None))
    assert info.value.status_code == 400 and info.value.detail["error"] == "invalid_agent_request"
