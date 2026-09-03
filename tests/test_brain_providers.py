"""Live Brain provider adapters, credential handling, and Brain selection."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.app import credentials
from backend.app.llm.providers import (
    AnthropicProvider,
    BrainError,
    OpenAICompatibleProvider,
    build_provider,
)


class _StubHandler(BaseHTTPRequestHandler):
    """Minimal stand-in for OpenAI-compatible and Anthropic chat endpoints."""

    calls: list[tuple[str, dict, dict]] = []

    def log_message(self, *args):  # noqa: D102 - silence test output
        pass

    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).calls.append((self.path, dict(self.headers), body))

        if "unauthorized" in self.path:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"bad key"}}')
            return

        if "/messages" in self.path:
            prompt = body["messages"][-1]["content"]
        else:
            prompt = body["messages"][-1]["content"]

        if "Answer 1" in prompt:
            payload = {"scores": [0.9, 0.4, 0.7]}
        elif "Topics:" in prompt:
            payload = {
                "questions": [
                    {"dimension": dimension, "prompt": f"Prompt {index}", "topics": ["kinematics"]}
                    for index, dimension in enumerate(
                        ["CONCEPTUAL_UNDERSTANDING", "EXECUTION_CALCULATION", "TRANSFER_APPLICATION"]
                    )
                ]
            }
        else:
            payload = {
                "summary": "Work the problems.",
                "topics": ["kinematics", "vectors"],
                "estimated_difficulty": 0.6,
                "base_time_minutes": 120,
                "prerequisites": ["algebra"],
                "assignment_type": "Homework",
                "reasoning_summary": "Standard problem set.",
            }

        # Wrapped in a fence so the JSON extractor is exercised, not bypassed.
        text = "Sure:\n```json\n" + json.dumps(payload) + "\n```"
        envelope = (
            {"content": [{"type": "text", "text": text}]}
            if "/messages" in self.path
            else {"choices": [{"message": {"content": text}}]}
        )
        raw = json.dumps(envelope).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture()
def stub_server():
    _StubHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def test_openai_compatible_analysis(stub_server):
    provider = OpenAICompatibleProvider("openai", "gpt-test", "sk-test", stub_server)
    result = provider.analyze_assignment("Projectile motion", "Chapter 3", "Homework")
    assert result.base_time_minutes == 120
    assert "kinematics" in result.topics
    assert any(path == "/v1/chat/completions" for path, _, _ in _StubHandler.calls)


def test_openai_compatible_calibration_and_grading(stub_server):
    provider = OpenAICompatibleProvider("openai", "gpt-test", "sk-test", stub_server)
    calibration = provider.generate_calibration("Projectile motion", ["kinematics"])
    assert len(calibration.questions) == 3
    assert provider.grade_calibration(["a", "b", "c"]) == [0.9, 0.4, 0.7]


def test_anthropic_uses_its_own_wire_format(stub_server):
    provider = AnthropicProvider("anthropic", "claude-test", "sk-ant", stub_server)
    assert provider.analyze_assignment("Projectile motion", "Chapter 3", "Homework").summary
    paths = [path for path, _, _ in _StubHandler.calls]
    headers = [headers for _, headers, _ in _StubHandler.calls]
    assert "/v1/messages" in paths
    assert any(item.get("x-api-key") == "sk-ant" and item.get("anthropic-version") for item in headers)


def test_grading_scores_are_clamped_to_unit_range(stub_server):
    provider = OpenAICompatibleProvider("openai", "gpt-test", "sk-test", stub_server)
    scores = provider.grade_calibration(["a", "b", "c"])
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_rejected_key_raises_a_readable_error(stub_server):
    provider = OpenAICompatibleProvider("openai", "gpt-test", "bad", stub_server.replace("/v1", "/unauthorized"))
    with pytest.raises(BrainError, match="rejected the API key"):
        provider.analyze_assignment("t", "d", "Homework")


def test_zai_and_custom_route_through_the_openai_client():
    assert isinstance(build_provider("zai", "glm-5.3-flash", "k"), OpenAICompatibleProvider)
    assert build_provider("zai", "m", "k")._base_url == "https://api.z.ai/api/paas/v4"
    assert build_provider("custom", "m", "k", "https://host/v1/")._base_url == "https://host/v1"


def test_unsupported_and_unconfigured_providers_are_rejected():
    with pytest.raises(BrainError):
        build_provider("gemini", "m", "k")
    with pytest.raises(BrainError):
        build_provider("custom", "m", "k")  # no base URL supplied


def test_credentials_are_process_local():
    credentials.clear()
    assert not credentials.has_key("zai")
    credentials.set_key("zai", "sk-zai")
    assert credentials.get_key("zai") == "sk-zai"
    assert credentials.configured_providers() == ["zai"]
    credentials.set_key("zai", "")
    assert not credentials.has_key("zai")
