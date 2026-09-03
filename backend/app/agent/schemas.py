"""Wire types for the browser agent.

The action union mirrors ``computerActionSchema`` in
``apps/desktop/src/main/computer-use.ts``. The duplication is deliberate: this
is a protocol boundary between the Python planner and the TypeScript executor,
and both sides validate independently so a malformed action from a model is
rejected twice rather than trusted once.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class ClickAction(BaseModel):
    action: Literal["click"]
    selector: str


class DoubleClickAction(BaseModel):
    action: Literal["double_click"]
    selector: str


class ScrollAction(BaseModel):
    action: Literal["scroll"]
    deltaY: int = Field(ge=-5000, le=5000)


class TypeTextAction(BaseModel):
    action: Literal["type_text"]
    selector: str
    text: str = Field(max_length=10000)


class PressKeyAction(BaseModel):
    action: Literal["press_key"]
    key: str = Field(max_length=40)


class NavigateAction(BaseModel):
    action: Literal["navigate"]
    url: str


class GoBackAction(BaseModel):
    action: Literal["go_back"]


class WaitAction(BaseModel):
    action: Literal["wait"]
    milliseconds: int = Field(ge=50, le=10000)


class ReadPageAction(BaseModel):
    action: Literal["read_page"]


class FinishAction(BaseModel):
    action: Literal["finish"]
    result: Any = None


class FailAction(BaseModel):
    action: Literal["fail"]
    reason: str


AgentAction = Annotated[
    Union[
        ClickAction, DoubleClickAction, ScrollAction, TypeTextAction, PressKeyAction,
        NavigateAction, GoBackAction, WaitAction, ReadPageAction, FinishAction, FailAction,
    ],
    Field(discriminator="action"),
]


class ActionEnvelope(BaseModel):
    """What the model is asked to return: one action plus its reasoning."""

    thought: str = Field(default="", max_length=1000)
    action: AgentAction


class ObservedElement(BaseModel):
    """An interactive element the executor tagged with a stable ref."""

    ref: str = Field(max_length=20)
    tag: str = Field(max_length=20)
    type: str | None = Field(default=None, max_length=40)
    name: str = Field(default="", max_length=300)
    value: str | None = Field(default=None, max_length=300)


class Observation(BaseModel):
    url: str
    title: str = ""
    text: str = Field(default="", max_length=20000)
    elements: list[ObservedElement] = Field(default_factory=list, max_length=200)


class HistoryStep(BaseModel):
    action: dict = Field(default_factory=dict)
    result: str = Field(default="", max_length=2000)


class NextActionRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    observation: Observation
    history: list[HistoryStep] = Field(default_factory=list, max_length=50)
