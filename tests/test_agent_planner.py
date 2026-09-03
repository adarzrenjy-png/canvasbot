"""Browser agent planning: prompt construction, action validation, and guard rails."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.agent.planner import AgentError, build_prompt, plan_next_action
from backend.app.agent.schemas import ActionEnvelope, NextActionRequest


def _request(**overrides) -> NextActionRequest:
    payload = {
        "goal": "List my courses",
        "observation": {
            "url": "https://rutgers.instructure.com/",
            "title": "Dashboard",
            "text": "Welcome back",
            "elements": [
                {"ref": "e1", "tag": "a", "name": "Courses"},
                {"ref": "e2", "tag": "input", "type": "password", "name": "Password"},
            ],
        },
        "history": [],
    }
    payload.update(overrides)
    return NextActionRequest.model_validate(payload)


def test_prompt_lists_refs_as_usable_selectors():
    prompt = build_prompt(_request())
    assert '[data-cadence-ref="e1"]' in prompt
    assert 'name="Courses"' in prompt
    assert "List my courses" in prompt


def test_prompt_reports_an_empty_page_and_a_fresh_run():
    prompt = build_prompt(_request(observation={"url": "https://x.test/", "elements": []}))
    assert "(no interactive elements detected)" in prompt
    assert "(nothing yet, this is the first step)" in prompt


def test_prompt_includes_recent_history():
    history = [{"action": {"action": "click", "selector": "[data-cadence-ref=\"e1\"]"}, "result": "{\"ok\":true}"}]
    prompt = build_prompt(_request(history=history))
    assert "click" in prompt and "ok" in prompt


def test_prompt_truncates_long_element_lists():
    elements = [{"ref": f"e{index}", "tag": "a", "name": f"Link {index}"} for index in range(1, 200)]
    prompt = build_prompt(_request(observation={"url": "https://x.test/", "elements": elements}))
    assert "more not shown" in prompt


@pytest.mark.parametrize(
    "action",
    [
        {"action": "click", "selector": '[data-cadence-ref="e1"]'},
        {"action": "type_text", "selector": "#q", "text": "statics"},
        {"action": "scroll", "deltaY": 600},
        {"action": "navigate", "url": "https://rutgers.instructure.com/courses"},
        {"action": "wait", "milliseconds": 500},
        {"action": "read_page"},
        {"action": "go_back"},
        {"action": "finish", "result": ["ME 201"]},
        {"action": "fail", "reason": "sign-in required"},
    ],
)
def test_every_action_in_the_vocabulary_validates(action):
    assert ActionEnvelope.model_validate({"thought": "because", "action": action}).action


@pytest.mark.parametrize(
    "action",
    [
        {"action": "teleport", "selector": "#x"},          # not in the vocabulary
        {"action": "click"},                                # missing selector
        {"action": "scroll", "deltaY": 99999},              # out of range
        {"action": "wait", "milliseconds": 10},             # below the floor
        {"action": "press_key", "key": "k" * 100},          # over the length cap
    ],
)
def test_actions_outside_the_vocabulary_are_rejected(action):
    with pytest.raises(ValidationError):
        ActionEnvelope.model_validate({"thought": "t", "action": action})


def test_agent_refuses_to_run_without_a_live_model(monkeypatch):
    """The deterministic Brain cannot drive a browser, and must say so rather than guess."""
    from backend.app.llm.mock import DemoBrainProvider

    monkeypatch.setattr("backend.app.agent.planner.get_brain", lambda session: DemoBrainProvider())
    with pytest.raises(AgentError, match="needs a live model"):
        plan_next_action(session=None, request=_request())


def test_planner_returns_the_model_action(monkeypatch):
    from backend.app.llm.providers import OpenAICompatibleProvider

    class StubBrain(OpenAICompatibleProvider):
        def __init__(self):
            super().__init__("openai", "gpt-test", "sk-test", "https://example.test/v1")

        def _complete(self, system, user):
            return '```json\n{"thought":"open courses","action":{"action":"click","selector":"[data-cadence-ref=\\"e1\\"]"}}\n```'

    monkeypatch.setattr("backend.app.agent.planner.get_brain", lambda session: StubBrain())
    envelope = plan_next_action(session=None, request=_request())
    assert envelope.action.action == "click"
    assert envelope.action.selector == '[data-cadence-ref="e1"]'
