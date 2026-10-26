"""The Meta Model API client, against a mock transport (no network, no credits)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from jig.ai.client import AIError, MissingKeyError, ModelClient
from jig.ai.config import load_model_config
from jig.ai.cost import BudgetExceeded, CostMeter, Usage


def completion(content: str, prompt: int = 1000, output: int = 200) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }


def make_client(
    handler, keys: dict[str, str], budget: float = 20.0
) -> tuple[ModelClient, CostMeter]:
    config = load_model_config()
    meter = CostMeter(config=config, budget_usd=budget)
    client = ModelClient(
        config,
        meter,
        key_lookup=keys.get,
        transport=httpx.MockTransport(handler),
        backoff_s=0,
    )
    return client, meter


def test_every_role_resolves_to_a_configured_provider() -> None:
    config = load_model_config()
    for name in ("planner", "modeler", "verifier", "fixer", "segmentation", "transcribe"):
        role = config.role(name)
        assert role.provider in config.providers
    assert config.role("verifier").model == "meta-models/muse-spark-open-1026"
    assert config.role("planner").model.startswith("muse-spark")


def test_chat_sends_the_documented_request_and_meters_cost() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion('{"ok": true}'))

    client, meter = make_client(handler, {"MODEL_API_KEY": "LLM|1|secret"})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    result = asyncio.run(client.chat("planner", [{"role": "user", "content": "hi"}], schema=schema))

    (request,) = seen
    assert str(request.url) == "https://api.meta.ai/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer LLM|1|secret"
    body = json.loads(request.content)
    assert body["model"] == "muse-spark-1.3"
    assert body["response_format"]["type"] == "json_schema"
    assert body["reasoning_effort"] == "medium"
    assert result.data == {"ok": True}
    expected = 1000 * 1.25 / 1e6 + 200 * 4.25 / 1e6
    assert result.cost_usd == pytest.approx(expected)
    assert meter.summary()["calls"] == 1


def test_missing_key_gives_a_clear_error() -> None:
    client, _ = make_client(lambda r: httpx.Response(500), {})
    with pytest.raises(MissingKeyError, match="MODEL_API_KEY"):
        asyncio.run(client.chat("planner", [{"role": "user", "content": "hi"}]))


def test_verifier_falls_back_to_meta_when_baseten_is_down() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "inference.baseten.co":
            return httpx.Response(503)
        return httpx.Response(200, json=completion("PASS"))

    client, _ = make_client(handler, {"MODEL_API_KEY": "k", "BASETEN_API_KEY": "b"})
    result = asyncio.run(client.chat("verifier", [{"role": "user", "content": "check"}]))
    assert result.fell_back and result.provider == "meta"
    assert hosts.count("inference.baseten.co") == 3  # retried before falling back
    assert hosts[-1] == "api.meta.ai"


def test_verifier_uses_baseten_with_the_hackathon_model_id() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion("PASS"))

    client, _ = make_client(handler, {"MODEL_API_KEY": "k", "BASETEN_API_KEY": "b"})
    result = asyncio.run(client.chat("verifier", [{"role": "user", "content": "check"}]))
    assert result.provider == "baseten" and not result.fell_back
    assert bodies[0]["model"] == "meta-models/muse-spark-open-1026"


def test_client_errors_are_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "n must be 1"}})

    client, _ = make_client(handler, {"MODEL_API_KEY": "k"})
    with pytest.raises(AIError, match="n must be 1"):
        asyncio.run(client.chat("planner", [{"role": "user", "content": "hi"}]))
    assert len(calls) == 1


def test_budget_stops_calls_once_spent() -> None:
    client, meter = make_client(
        lambda r: httpx.Response(200, json=completion("x")), {"MODEL_API_KEY": "k"}, budget=0.01
    )
    meter.record("planner", "muse-spark-1.3", Usage(output_tokens=10_000))  # $0.0425
    with pytest.raises(BudgetExceeded):
        asyncio.run(client.chat("planner", [{"role": "user", "content": "hi"}]))
    assert meter.summary()["exhausted"]


def test_unknown_models_are_priced_conservatively() -> None:
    meter = CostMeter(config=load_model_config(), budget_usd=20)
    known = meter.estimate("muse-spark-1.3", Usage(output_tokens=1_000_000))
    unknown = meter.estimate("mystery-model", Usage(output_tokens=1_000_000))
    assert unknown >= known
