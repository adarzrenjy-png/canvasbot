"""HTTP client for Meta's Model API and the Muse Spark Open provider.

Both speak the OpenAI Chat Completions format, so one small httpx client covers
them. Every call goes through the session cost meter, and a role whose primary
provider is missing or down falls back to the provider named in models.toml.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from jig.ai.config import ModelConfig, Provider, Role
from jig.ai.cost import CostMeter, Usage


class AIError(RuntimeError):
    """A model call failed in a way the caller should show to the user."""


class MissingKeyError(AIError):
    pass


class ProviderUnavailable(AIError):
    """Transient failure (network, 429, 5xx) that survived every retry."""


@dataclass
class ChatResult:
    role: str
    provider: str
    model: str
    content: str
    data: Any | None
    usage: Usage
    cost_usd: float
    latency_ms: int
    fell_back: bool = False
    notes: list[str] = field(default_factory=list)


def _usage_from(body: dict[str, Any]) -> Usage:
    raw = body.get("usage") or {}
    details = raw.get("prompt_tokens_details") or {}
    return Usage(
        input_tokens=int(raw.get("prompt_tokens") or 0),
        cached_input_tokens=int(details.get("cached_tokens") or 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
    )


def _parse_json(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        # Schema-constrained output should never be fenced, but be forgiving.
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise AIError(f"Model returned invalid JSON: {error}") from error


class ModelClient:
    RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

    def __init__(
        self,
        config: ModelConfig,
        meter: CostMeter,
        *,
        key_lookup: Callable[[str], str | None],
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        timeout_s: float = 180.0,
        backoff_s: float = 0.5,
    ) -> None:
        self.config = config
        self.meter = meter
        self._key_lookup = key_lookup
        self._transport = transport
        self._max_attempts = max_attempts
        self._timeout_s = timeout_s
        self._backoff_s = backoff_s

    def has_key(self, provider: str) -> bool:
        return self._key_lookup(self.config.providers[provider].api_key_env) is not None

    def status(self) -> dict[str, Any]:
        return {
            "providers": {
                name: {"configured": self.has_key(name), "key_env": p.api_key_env}
                for name, p in self.config.providers.items()
            },
            "ready": self.has_key("meta"),
        }

    def _targets(self, role: Role) -> list[tuple[str, str, str | None]]:
        targets = [(role.provider, role.model, role.reasoning_effort)]
        if role.fallback_provider and role.fallback_model:
            targets.append((role.fallback_provider, role.fallback_model, None))
        return targets

    async def chat(
        self,
        role_name: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any] | None = None,
        schema_name: str = "result",
        max_output_tokens: int | None = None,
    ) -> ChatResult:
        role = self.config.role(role_name)
        notes: list[str] = []
        last_error: AIError | None = None
        for index, (provider_name, model, effort) in enumerate(self._targets(role)):
            provider = self.config.providers[provider_name]
            key = self._key_lookup(provider.api_key_env)
            if key is None:
                last_error = MissingKeyError(
                    f"{provider.api_key_env} is not set, so the {role_name} agent cannot "
                    f"reach {provider_name}. Add it to your .env file."
                )
                notes.append(f"{provider_name}: no key")
                continue
            body: dict[str, Any] = {"model": model, "messages": messages}
            if effort:
                body["reasoning_effort"] = effort
            if schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema},
                }
            if max_output_tokens:
                body["max_completion_tokens"] = max_output_tokens
            try:
                result = await self._post_chat(role_name, provider, key, body)
            except ProviderUnavailable as error:
                last_error = error
                notes.append(f"{provider_name}: {error}")
                continue
            result.fell_back = index > 0
            result.notes = notes
            if schema is not None:
                result.data = _parse_json(result.content)
            return result
        assert last_error is not None
        raise last_error

    async def _post_chat(
        self, role_name: str, provider: Provider, key: str, body: dict[str, Any]
    ) -> ChatResult:
        url = f"{provider.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as http:
            for attempt in range(self._max_attempts):
                self.meter.check()
                started = time.monotonic()
                try:
                    response = await http.post(url, headers=headers, json=body)
                except httpx.TransportError as error:
                    failure = f"network error: {error.__class__.__name__}"
                else:
                    if response.status_code == 200:
                        return self._finish(role_name, provider, body["model"], response, started)
                    if response.status_code not in self.RETRYABLE_STATUS:
                        raise AIError(_describe_error(provider, response))
                    failure = f"HTTP {response.status_code}"
                if attempt < self._max_attempts - 1:
                    await asyncio.sleep(self._backoff_s * 2**attempt + random.uniform(0, 0.25))
        raise ProviderUnavailable(f"{provider.name} unavailable after retries ({failure})")

    def _finish(
        self,
        role_name: str,
        provider: Provider,
        model: str,
        response: httpx.Response,
        started: float,
    ) -> ChatResult:
        payload = response.json()
        usage = _usage_from(payload)
        entry = self.meter.record(role_name, model, usage)
        try:
            content = payload["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as error:
            raise AIError(f"{provider.name} returned an unexpected response shape") from error
        return ChatResult(
            role=role_name,
            provider=provider.name,
            model=model,
            content=content,
            data=None,
            usage=usage,
            cost_usd=entry.cost_usd,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def _describe_error(provider: Provider, response: httpx.Response) -> str:
    try:
        envelope = response.json().get("error") or {}
        message = envelope.get("message") or response.text[:300]
    except ValueError:
        message = response.text[:300]
    hint = {
        401: f"check {provider.api_key_env}",
        403: f"check {provider.api_key_env} permissions",
        404: "check the model ID in models.toml",
    }.get(response.status_code, "")
    suffix = f" ({hint})" if hint else ""
    return f"{provider.name} rejected the request: HTTP {response.status_code}: {message}{suffix}"
