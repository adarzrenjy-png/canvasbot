"""The agent loop and the Verifier's deterministic checks.

Model calls go to a scripted mock of the Meta Model API (no network, no credits). The
script plays each subagent; everything else (builds, checks, routing, DRC/ERC) is real.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from jig.agents.checks import (
    enforce_locks,
    fea_check,
    part_checks,
    requirement_values,
    verdict,
)
from jig.agents.guides import BOARD_FORMAT, PART_FORMAT
from jig.agents.loop import AgentDeps, run_agents
from jig.ai.client import ModelClient
from jig.ai.config import load_model_config
from jig.ai.cost import CostMeter
from jig.app import _part_payload, create_app
from jig.cad.program import ProgramError, parse_program, set_param_flags
from jig.cad.samples import L_BRACKET
from jig.fea.ccx import CcxStatus
from jig.pcb.library import PARTS
from jig.pcb.samples import PICO_SERVO
from jig.pcb.service import BoardService
from jig.settings import Settings

PLAN = {
    "name": "L-bracket",
    "summary": "Holds a camera off a wall.",
    "approach": "Two plates joined at a filleted corner.",
    "material": "petg",
    "envelope_mm": [60, 40, 45],
    "features": [{"kind": "extrude", "label": "Base flange", "description": "The base."}],
    "parameters": [
        {"name": "WIDTH", "value": 40, "unit": "mm", "description": "Width", "min": 10, "max": 200}
    ],
    "load_case": {
        "applies": True,
        "description": "Camera on the base",
        "fixtures": "wall bolts",
        "loads": "camera",
        "force_n": 60,
    },
    "assumptions": [],
}
BOARD_PLAN = {
    "name": "Pico servo board",
    "summary": "Drives two servos from a Pico.",
    "width_mm": 72,
    "height_mm": 45,
    "parts": [{"ref": "U1", "part": "raspberry_pi_pico", "value": "", "why": "controller"}],
    "nets": [
        {"name": "GND", "kind": "ground", "voltage_v": 0, "current_a": 3.3, "connects": ["U1.3"]}
    ],
    "placement": "Pico in the middle.",
    "assumptions": [],
}
OK_REVIEW = {"matches_request": True, "summary": "Does what was asked.", "issues": []}
BROKEN = L_BRACKET.replace(
    "Cylinder(HOLE_DIAMETER / 2, THICKNESS * 2)\n    return part",
    "Cylinder(HOLE_DIA / 2, THICKNESS * 2)\n    return part",
)


def completion(data: dict) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": json.dumps(data)}}],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 800},
    }


class Script:
    """Answers each subagent's calls in order; records what each one was asked."""

    def __init__(self, **answers: list[dict]) -> None:
        self.answers = {role: list(items) for role, items in answers.items()}
        self.asked: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        role = body["response_format"]["json_schema"]["name"]
        self.asked.append((role, body["messages"][-1]["content"]))
        if not self.answers.get(role):
            return httpx.Response(400, json={"error": {"message": f"unexpected {role} call"}})
        return httpx.Response(200, json=completion(self.answers[role].pop(0)))

    def roles(self) -> list[str]:
        return [role for role, _ in self.asked]


def models_for(script: Script, keys: dict[str, str] | None = None) -> ModelClient:
    config = load_model_config()
    meter = CostMeter(config=config, budget_usd=20)
    return ModelClient(
        config,
        meter,
        key_lookup=(keys if keys is not None else {"MODEL_API_KEY": "test"}).get,
        transport=httpx.MockTransport(script),
        backoff_s=0,
    )


def run(deps: AgentDeps, domain: str, prompt: str, current: str | None = None, **kw):
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    asyncio.run(run_agents(deps, emit, domain, prompt, current, **kw))
    return events


@pytest.fixture
def deps_for(builder, tmp_path: Path):
    def make(script: Script, **kw) -> AgentDeps:
        return AgentDeps(
            models=models_for(script, kw.pop("keys", None)),
            builder=builder,
            boards=BoardService(tmp_path / "boards"),
            ccx=lambda: CcxStatus(available=False, path=None, version=None, message="no ccx"),
            part_payload=_part_payload,
            **kw,
        )

    return make


# ------------------------------------------------------- deterministic checks


def test_locked_parameters_are_put_back() -> None:
    code = L_BRACKET.replace("THICKNESS = 5.0", "THICKNESS = 3.0")
    fixed, moved = enforce_locks(code, {"THICKNESS": 5.0, "MISSING": 1.0})
    assert "THICKNESS = 5.0" in fixed
    assert moved == ["THICKNESS 3 -> 5"]
    assert enforce_locks(L_BRACKET, {"THICKNESS": 5.0}) == (L_BRACKET, [])


def test_checks_catch_ranges_locks_and_a_weakened_load_case() -> None:
    requirements = requirement_values(parse_program(L_BRACKET))
    assert requirements["loads"] == [("Camera", (0.0, 0.0, -60.0))]

    cheat = L_BRACKET.replace("LOAD_N = 60.0", "LOAD_N = 10.0").replace(
        "WIDTH = 40.0", "WIDTH = 400.0"
    )
    checks = part_checks(
        cheat,
        parse_program(cheat),
        None,
        None,
        locked={"HOLE_INSET": 12.0},
        requirements=requirements,
    )
    status = {c.id: c.status for c in checks}
    assert status["ranges"] == "fail" and "WIDTH = 400" in checks[2].message
    assert status["locked"] == "fail"
    assert status["requirements"] == "fail"
    assert verdict(checks)["status"] == "fail"

    softer = L_BRACKET.replace('"min_safety_factor": 2.0', '"min_safety_factor": 1.2')
    soft = part_checks(softer, parse_program(softer), None, None, requirements=requirements)
    assert {c.id: c.status for c in soft}["requirements"] == "fail"


def test_a_loaded_part_without_a_load_case_fails() -> None:
    code = L_BRACKET.split("# The load case")[0] + "\n\ndef build():\n    return None\n"
    checks = part_checks(code, parse_program(code), None, None, plan=PLAN)
    assert {c.id: c.status for c in checks}["load_case"] == "fail"


def test_program_and_build_failures_carry_line_and_feature() -> None:
    error = ProgramError("FEATURES must be a list", 40)
    (check,) = part_checks("x", None, error, None)
    assert (check.status, check.line) == ("fail", 40)

    build = {
        "ok": False,
        "features": [],
        "error": {"stage": "feature", "message": "NameError", "line": 64, "feature": "base_holes"},
    }
    checks = part_checks(L_BRACKET, parse_program(L_BRACKET), None, build)
    failed = [c for c in checks if c.status == "fail"]
    assert [(c.id, c.line, c.feature) for c in failed] == [("build", 64, "base_holes")]


def test_verdict_needs_fea_to_pass_a_loaded_part(builder) -> None:
    built = builder.build(L_BRACKET).data
    program = parse_program(L_BRACKET)
    checks = part_checks(L_BRACKET, program, None, built, plan=PLAN)
    assert all(c.status == "pass" for c in checks), [c for c in checks if c.status != "pass"]
    assert verdict(checks)["status"] == "unverified"

    passed = fea_check(
        {"ok": True, "status": "pass", "safety_factor": 2.6, "checks": [], "result": {}}
    )
    assert verdict([*checks, passed])["status"] == "pass"
    failed = fea_check(
        {"ok": True, "status": "fail", "safety_factor": 1.7, "checks": [], "result": {}}
    )
    assert verdict([*checks, failed])["status"] == "fail"
    shaky = fea_check(
        {"ok": True, "status": "unconverged", "safety_factor": 2.2, "checks": [], "result": {}}
    )
    assert shaky.status == "warn" and verdict([*checks, shaky])["status"] == "unverified"


def test_agent_guides_match_what_jig_accepts() -> None:
    parse_program(L_BRACKET)  # the example the Modeler copies is valid
    assert "L-bracket" in PART_FORMAT and "ANALYSIS" in PART_FORMAT
    for part_id in PARTS:
        assert f"- {part_id} [" in BOARD_FORMAT


# ------------------------------------------------------------ the agent loop


def test_part_loop_fixes_a_broken_build(deps_for) -> None:
    script = Script(
        planner=[PLAN],
        modeler=[{"code": BROKEN, "notes": "Used M5 holes."}],
        fixer=[
            {
                "diagnosis": "base_holes used an undefined name",
                "changes": ["HOLE_DIA -> HOLE_DIAMETER"],
                "code": L_BRACKET,
            }
        ],
        verifier=[OK_REVIEW],
    )
    events = run(deps_for(script), "part", "An L-bracket for a 2 kg camera", fea=True)
    assert script.roles() == ["planner", "modeler", "fixer", "verifier"]
    result = events[-1]
    assert result["type"] == "result", events[-1]
    assert result["rounds"] == 1
    assert result["verdict"]["status"] == "unverified"  # built and checked; no ccx to test it
    assert result["part"]["build"]["ok"]
    assert result["cost_usd"] > 0

    # The Fixer was told exactly what failed and where.
    fixer_prompt = script.asked[2][1]
    assert "base_holes" in fixer_prompt and "HOLE_DIA" in fixer_prompt
    titles = [e["title"] for e in events if e["type"] == "trace"]
    assert any(t.startswith("Build failed in base_holes") for t in titles)
    assert sum(1 for e in events if e["type"] == "part") == 2


def test_part_loop_keeps_locks_and_refuses_a_weaker_test(deps_for) -> None:
    current = set_param_flags(L_BRACKET, "THICKNESS", locked=True)
    thinner = current.replace("THICKNESS = 5.0", "THICKNESS = 3.0").replace(
        "WIDTH = 40.0", "WIDTH = 50.0"
    )
    cheat = thinner.replace("LOAD_N = 60.0", "LOAD_N = 5.0")
    script = Script(
        planner=[PLAN],
        modeler=[{"code": thinner, "notes": ""}],
        verifier=[
            {
                "matches_request": False,
                "summary": "Holes are too close to the edge.",
                "issues": [{"severity": "blocking", "where": "HOLE_INSET", "message": "Too close"}],
            },
            OK_REVIEW,
        ],
        fixer=[
            {"diagnosis": "Lower the load", "changes": ["LOAD_N 5"], "code": cheat},
            {"diagnosis": "Restored the load", "changes": ["LOAD_N 60"], "code": thinner},
        ],
    )
    events = run(deps_for(script), "part", "Make it 50 mm wide", current)
    result = events[-1]
    assert result["type"] == "result"
    assert "THICKNESS = 5.0" in result["part"]["code"]  # the lock held
    assert "WIDTH = 50.0" in result["part"]["code"]
    assert "LOAD_N = 60.0" in result["part"]["code"]
    assert result["rounds"] == 2
    traces = [e for e in events if e["type"] == "trace"]
    assert any(e["title"] == "Put locked parameters back" for e in traces)
    assert any("Loads and safety margin" in e["title"] for e in traces)
    assert "Locked parameters (never change): THICKNESS" in script.asked[0][1]


def test_missing_key_stops_with_a_clear_message(deps_for) -> None:
    script = Script()
    events = run(deps_for(script, keys={}), "part", "A bracket")
    assert events[-1]["type"] == "error"
    assert "MODEL_API_KEY" in events[-1]["message"]
    assert script.asked == []


def test_board_loop_fixes_overlapping_parts(deps_for) -> None:
    crowded = PICO_SERVO.replace('"at": (BOARD_W - 8.5, 21)', '"at": (35, 28)')
    script = Script(
        planner=[BOARD_PLAN],
        modeler=[{"code": crowded, "notes": ""}],
        fixer=[{"diagnosis": "C2 sat on U1", "changes": ["Moved C2"], "code": PICO_SERVO}],
        verifier=[OK_REVIEW],
    )
    events = run(deps_for(script), "board", "A Pico board that drives two servos")
    result = events[-1]
    assert result["type"] == "result", result
    assert result["domain"] == "board"
    assert result["rounds"] == 1
    assert result["verdict"]["status"] == "pass"
    fixer_prompt = script.asked[2][1]
    assert "C2" in fixer_prompt and "U1" in fixer_prompt
    assert [e["type"] for e in events].count("board") == 2


def test_agents_endpoint_streams_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    settings = Settings(data_dir=tmp_path, budget_usd=20, build_timeout_s=90, ccx_path=None)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/agents/run", json={"prompt": "A bracket for a camera"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines() if line]
        assert events[0] == {"type": "progress", "agent": "Planner", "title": "Planning the part"}
        assert events[-1]["type"] == "error" and "MODEL_API_KEY" in events[-1]["message"]

        script = Script(
            planner=[PLAN],
            modeler=[{"code": L_BRACKET, "notes": ""}],
            verifier=[OK_REVIEW],
        )
        client.app.state.services.models = models_for(script)
        response = client.post(
            "/api/agents/run", json={"prompt": "A bracket for a camera", "fea": False}
        )
        events = [json.loads(line) for line in response.text.splitlines() if line]
        assert events[-1]["type"] == "result"
        assert events[-1]["verdict"]["status"] == "unverified"
        calls = [e for e in events if e["type"] == "call"]
        assert [c["agent"] for c in calls] == ["Planner", "Modeler", "Verifier"]
        assert calls[-1]["fell_back"] is True  # no Baseten key: Muse Spark Open -> Meta
