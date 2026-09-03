"""Decides the browser agent's next action.

Deliberately model-agnostic. Rather than a vendor-specific computer-use protocol
built on screenshots and pixel coordinates, the agent is driven by a text
observation of the page plus a constrained action vocabulary returned as JSON.
Any model that can follow a JSON schema can drive it, which is why this runs
through the same LLMProvider abstraction as the rest of the Brain.

The executor tags every interactive element with ``data-cadence-ref``, so the
model selects targets by a ref it was shown rather than inventing CSS. Actions
are validated here and again in the executor before anything touches the page.
"""

from __future__ import annotations

import json
import logging

from sqlmodel import Session

from ..llm.factory import get_brain
from ..llm.providers import BrainError, RemoteBrainProvider
from .schemas import ActionEnvelope, NextActionRequest

logger = logging.getLogger(__name__)

MAX_ELEMENTS_IN_PROMPT = 120
MAX_HISTORY_IN_PROMPT = 12

SYSTEM_PROMPT = """You drive a real web browser to accomplish one goal on a university
Canvas site. You see a text description of the current page and reply with exactly
one next action, as JSON.

Reply shape:
{"thought": "one short sentence on why", "action": {...}}

The action must be exactly one of:
{"action": "click", "selector": "..."}
{"action": "double_click", "selector": "..."}
{"action": "type_text", "selector": "...", "text": "..."}
{"action": "press_key", "key": "Enter"}
{"action": "scroll", "deltaY": 600}
{"action": "navigate", "url": "https://..."}
{"action": "go_back"}
{"action": "wait", "milliseconds": 1000}
{"action": "read_page"}
{"action": "finish", "result": <the data you were asked to collect>}
{"action": "fail", "reason": "..."}

Rules:
- Select elements only by the refs listed under ELEMENTS, written as
  [data-cadence-ref="e12"]. Never invent a CSS selector or guess a ref.
- One action per reply. Observe the result before deciding the next one.
- Never type into a password field and never attempt to sign in. If the page asks
  for credentials, reply with "fail" and say sign-in is required.
- Stay on the allowed academic origins. Navigation elsewhere is rejected.
- When you have gathered what the goal asks for, reply with "finish" and put the
  collected data in "result".
- If the goal cannot be met on this page and no listed element makes progress,
  reply with "fail" and explain why.

Reply with the JSON object and nothing else."""


class AgentError(RuntimeError):
    """The agent cannot plan a step, for a reason worth showing the user."""


def _render_elements(request: NextActionRequest) -> str:
    if not request.observation.elements:
        return "(no interactive elements detected)"
    lines = []
    for element in request.observation.elements[:MAX_ELEMENTS_IN_PROMPT]:
        parts = [f'[data-cadence-ref="{element.ref}"]', element.tag]
        if element.type:
            parts.append(f"type={element.type}")
        if element.name:
            parts.append(f'name="{element.name}"')
        if element.value:
            parts.append(f'value="{element.value}"')
        lines.append("  " + " ".join(parts))
    if len(request.observation.elements) > MAX_ELEMENTS_IN_PROMPT:
        lines.append(f"  … {len(request.observation.elements) - MAX_ELEMENTS_IN_PROMPT} more not shown")
    return "\n".join(lines)


def _render_history(request: NextActionRequest) -> str:
    if not request.history:
        return "(nothing yet, this is the first step)"
    recent = request.history[-MAX_HISTORY_IN_PROMPT:]
    return "\n".join(
        f"  {index}. {json.dumps(step.action)} -> {step.result}"
        for index, step in enumerate(recent, start=len(request.history) - len(recent) + 1)
    )


def build_prompt(request: NextActionRequest) -> str:
    observation = request.observation
    return (
        f"GOAL:\n{request.goal}\n\n"
        f"CURRENT PAGE:\n  url: {observation.url}\n  title: {observation.title}\n\n"
        f"ELEMENTS:\n{_render_elements(request)}\n\n"
        f"PAGE TEXT (truncated):\n{observation.text[:6000]}\n\n"
        f"STEPS SO FAR:\n{_render_history(request)}\n\n"
        "Reply with the JSON object for your next action."
    )


def plan_next_action(session: Session, request: NextActionRequest) -> ActionEnvelope:
    """Ask the configured Brain for one next action.

    Requires a live provider. The deterministic demo Brain cannot drive a
    browser, and inventing actions would be worse than saying so.
    """
    brain = get_brain(session)
    if not isinstance(brain, RemoteBrainProvider):
        raise AgentError(
            "The browser agent needs a live model. Choose a provider and enter an API key "
            "in Settings, then try again."
        )

    try:
        return brain.structured(SYSTEM_PROMPT, build_prompt(request), ActionEnvelope)
    except BrainError as error:
        raise AgentError(str(error)) from error
