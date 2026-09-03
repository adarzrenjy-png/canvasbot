"""Live Brain providers.

Every provider returns the same pydantic models the deterministic demo Brain
returns, so the pipeline does not care which one is configured.

Two wire formats cover everything currently offered in the UI:

* OpenAI-compatible ``/chat/completions`` — OpenAI, Z.AI (GLM), and any custom
  endpoint that speaks the same shape (OpenRouter, Ollama, vLLM, LM Studio).
* Anthropic ``/v1/messages``.

Models are asked for JSON and the reply is validated against the schema. A
malformed reply is retried once with the parse error appended; if it still does
not validate the caller falls back to the demo Brain rather than failing the
request outright.
"""

from __future__ import annotations

import json
import re
from typing import Any, Type

import httpx
from pydantic import BaseModel, ValidationError

from .base import LLMProvider
from .schemas import AssignmentAnalysisOutput, CalibrationOutput

TIMEOUT_SECONDS = 60.0

# Base URLs for the providers offered in the desktop UI. "custom" has no default:
# the user supplies one.
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "zai": "https://api.z.ai/api/paas/v4",
}

OPENAI_COMPATIBLE = {"openai", "zai", "custom"}
SUPPORTED_PROVIDERS = OPENAI_COMPATIBLE | {"anthropic"}


class BrainError(RuntimeError):
    """A provider call failed in a way the caller should report or fall back from."""


def _extract_json(text: str) -> str:
    """Pull a JSON object out of a reply that may be wrapped in prose or fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


ANALYSIS_INSTRUCTIONS = """You analyse a university assignment and reply with JSON only.

Required shape:
{
  "summary": "one or two sentences on what the work involves",
  "topics": ["specific academic topic", "..."],
  "estimated_difficulty": 0.0 to 1.0,
  "base_time_minutes": integer 15 to 1440, focused working minutes for a typical student,
  "prerequisites": ["topic a student should already know", "..."],
  "assignment_type": "Homework | Quiz | Problem set | Writing | Project | Exam",
  "reasoning_summary": "one sentence on how you reached the estimate"
}

Topics must be concrete concepts, not restatements of the title. Reply with the
JSON object and nothing else."""

CALIBRATION_INSTRUCTIONS = """You write a three-question diagnostic that reveals how well a student
understands an assignment's topics. Reply with JSON only.

Required shape:
{
  "questions": [
    {"dimension": "CONCEPTUAL_UNDERSTANDING", "prompt": "...", "topics": ["..."]},
    {"dimension": "EXECUTION_CALCULATION", "prompt": "...", "topics": ["..."]},
    {"dimension": "TRANSFER_APPLICATION", "prompt": "...", "topics": ["..."]}
  ]
}

Exactly three questions, in that order of dimensions. Each prompt is answerable
in a short paragraph without a calculator. Reply with the JSON object and nothing else."""

GRADING_INSTRUCTIONS = """You grade a student's diagnostic answers. Reply with JSON only.

Required shape:
{"scores": [0.0 to 1.0, 0.0 to 1.0, 0.0 to 1.0]}

One score per answer, in order. Judge demonstrated understanding, not length or
writing style. An empty or off-topic answer scores near 0. Reply with the JSON
object and nothing else."""


class _ScoreList(BaseModel):
    scores: list[float]


class RemoteBrainProvider(LLMProvider):
    """Shared prompting and validation for every live provider."""

    def __init__(self, provider: str, model: str, api_key: str, base_url: str | None = None) -> None:
        self.name = provider
        self.model = model
        self._api_key = api_key
        resolved = base_url or DEFAULT_BASE_URLS.get(provider)
        if not resolved:
            raise BrainError(f"No base URL is configured for provider '{provider}'.")
        self._base_url = resolved.rstrip("/")

    # -- transport, implemented per wire format -------------------------------

    def _complete(self, system: str, user: str) -> str:
        raise NotImplementedError

    # -- LLMProvider ----------------------------------------------------------

    async def generate(self, prompt: str) -> str:
        return self._complete("You are a helpful academic assistant.", prompt)

    async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> Any:
        return self._structured("Reply with JSON only.", prompt, schema)

    # -- structured helper ----------------------------------------------------

    def _structured(self, system: str, user: str, schema: Type[BaseModel]):
        reply = self._complete(system, user)
        try:
            return schema.model_validate_json(_extract_json(reply))
        except (ValidationError, ValueError) as first_error:
            # One corrective retry. Models frequently fix their own shape when
            # told exactly what failed.
            retry = self._complete(
                system,
                f"{user}\n\nYour previous reply was rejected: {first_error}\nReply with valid JSON matching the schema exactly.",
            )
            try:
                return schema.model_validate_json(_extract_json(retry))
            except (ValidationError, ValueError) as second_error:
                raise BrainError(f"{self.name} returned malformed JSON: {second_error}") from second_error

    # -- Brain surface used by the pipeline -----------------------------------

    def analyze_assignment(self, title: str, description: str, assignment_type: str) -> AssignmentAnalysisOutput:
        user = f"Title: {title}\nType: {assignment_type}\nDescription: {description or '(none provided)'}"
        return self._structured(ANALYSIS_INSTRUCTIONS, user, AssignmentAnalysisOutput)

    def generate_calibration(self, title: str, topics: list[str]) -> CalibrationOutput:
        user = f"Assignment: {title}\nTopics: {', '.join(topics) or '(none identified)'}"
        return self._structured(CALIBRATION_INSTRUCTIONS, user, CalibrationOutput)

    def grade_calibration(self, answers: list[str]) -> list[float]:
        numbered = "\n\n".join(f"Answer {index}: {answer or '(blank)'}" for index, answer in enumerate(answers, start=1))
        result = self._structured(GRADING_INSTRUCTIONS, numbered, _ScoreList)
        scores = [min(max(float(score), 0.0), 1.0) for score in result.scores]
        if len(scores) != len(answers):
            raise BrainError(f"{self.name} returned {len(scores)} scores for {len(answers)} answers.")
        return scores


class OpenAICompatibleProvider(RemoteBrainProvider):
    """Anything speaking OpenAI's /chat/completions: OpenAI, Z.AI/GLM, OpenRouter, Ollama."""

    def _complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise BrainError(f"Could not reach {self.name}: {error}") from error
        if response.status_code >= 400:
            raise BrainError(_http_message(self.name, response))
        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, json.JSONDecodeError) as error:
            raise BrainError(f"{self.name} returned an unexpected response shape: {error}") from error


class AnthropicProvider(RemoteBrainProvider):
    """Anthropic's /v1/messages format."""

    def _complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = httpx.post(
                f"{self._base_url}/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise BrainError(f"Could not reach {self.name}: {error}") from error
        if response.status_code >= 400:
            raise BrainError(_http_message(self.name, response))
        try:
            blocks = response.json()["content"]
            return "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise BrainError(f"{self.name} returned an unexpected response shape: {error}") from error


def _http_message(provider: str, response: httpx.Response) -> str:
    label = {"openai": "OpenAI", "anthropic": "Anthropic", "zai": "Z.AI"}.get(provider, provider)
    if response.status_code in (401, 403):
        return f"{label} rejected the API key or it lacks access to this model."
    if response.status_code == 404:
        return f"{label} does not recognise the selected model."
    if response.status_code == 429:
        return f"{label} rate-limited the request. Try again shortly."
    detail = ""
    try:
        body = response.json()
        detail = body.get("error", {}).get("message") or body.get("message") or ""
    except (json.JSONDecodeError, AttributeError):
        detail = response.text[:200]
    return f"{label} returned HTTP {response.status_code}{f': {detail}' if detail else ''}"


def build_provider(provider: str, model: str, api_key: str, base_url: str | None = None) -> RemoteBrainProvider:
    if provider == "anthropic":
        return AnthropicProvider(provider, model, api_key, base_url)
    if provider in OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(provider, model, api_key, base_url)
    raise BrainError(f"Unsupported Brain provider '{provider}'.")
