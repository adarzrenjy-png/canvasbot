"""The agent loop: Planner -> Modeler -> checks -> Verifier review -> Fixer, until it passes.

Models plan, write and repair. Code measures: every build, check, FEA run and board
DRC/ERC in this loop is deterministic, and only those decide the verdict. Each step is
streamed as an event so the UI can show the trace live:

    {"type": "progress", "agent": ..., "title": ...}       something started
    {"type": "trace", "agent": ..., "kind": "agent"|"check"|"system",
     "status": "ok"|"fail"|"info", "title": ..., "detail": ..., ...}
    {"type": "part", "part": <part payload>}               a new build to show
    {"type": "board", "board": <board payload>}            a new board to show
    {"type": "result", ...}                                the final verdict
    {"type": "error", "message": ...}                      the run stopped
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi.concurrency import run_in_threadpool

from jig.agents import prompts, schemas
from jig.agents.checks import (
    Check,
    code_from_reply,
    enforce_locks,
    fea_check,
    nearest_feature,
    part_checks,
    requirement_values,
    verdict,
)
from jig.ai.client import AIError, ModelClient
from jig.ai.cost import BudgetExceeded
from jig.cad.builder import Builder, BuildResult
from jig.cad.program import Program, ProgramError, parse_params, parse_program
from jig.fea.ccx import CcxStatus
from jig.fea.service import analyze_build
from jig.pcb.service import BoardService

Emit = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class AgentDeps:
    models: ModelClient
    builder: Builder
    boards: BoardService
    ccx: Callable[[], CcxStatus]
    part_payload: Callable[[str, BuildResult], dict[str, Any]]
    max_rounds: int = 3


@dataclass
class Evaluation:
    code: str
    program: Program | None
    build: BuildResult | None
    checks: list[Check]
    fea: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    board_checks: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


class StopRun(Exception):
    """A model call failed in a way that ends the run (no key, budget, provider down)."""


def _locked(code: str | None) -> dict[str, float]:
    if not code:
        return {}
    try:
        return {p.name: p.value for p in parse_params(code) if p.locked}
    except ProgramError:
        return {}


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


class AgentRun:
    def __init__(self, deps: AgentDeps, emit: Emit) -> None:
        self.deps = deps
        self.emit = emit
        self.started_spend = deps.models.meter.spent_usd

    @property
    def cost(self) -> float:
        return round(self.deps.models.meter.spent_usd - self.started_spend, 4)

    async def trace(
        self, agent: str, kind: str, status: str, title: str, detail: str = "", **extra: Any
    ) -> None:
        await self.emit(
            {
                "type": "trace",
                "agent": agent,
                "kind": kind,
                "status": status,
                "title": title,
                "detail": detail,
                **extra,
            }
        )

    async def ask(
        self,
        agent: str,
        role: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        doing: str,
    ) -> dict[str, Any]:
        await self.emit({"type": "progress", "agent": agent, "title": doing})
        try:
            result = await self.deps.models.chat(
                role,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                schema=schema,
                schema_name=role,
            )
        except (AIError, BudgetExceeded) as error:
            await self.trace(agent, "agent", "fail", f"{agent} could not answer", str(error))
            raise StopRun(str(error)) from error
        if not isinstance(result.data, dict):
            await self.trace(agent, "agent", "fail", f"{agent} returned no usable answer")
            raise StopRun(f"The {agent} returned an answer Jig could not read")
        model = f"{result.model} via {result.provider}"
        if result.fell_back:
            model += " (fallback)"
        await self.emit(
            {
                "type": "call",
                "agent": agent,
                "model": result.model,
                "provider": result.provider,
                "fell_back": result.fell_back,
                "cost_usd": round(result.cost_usd, 5),
                "latency_ms": result.latency_ms,
                "session": self.deps.models.meter.summary(),
            }
        )
        result.data["_meta"] = {"model": model, "cost": result.cost_usd, "ms": result.latency_ms}
        return result.data

    @staticmethod
    def meta(data: dict[str, Any]) -> str:
        m = data.get("_meta") or {}
        return f"{m.get('model', '')} · {m.get('ms', 0) / 1000:.1f} s · ${m.get('cost', 0):.4f}"

    # ------------------------------------------------------------------ parts

    async def part(self, request: str, current: str | None, *, fea: bool = True) -> dict:
        locked = _locked(current)
        context = ""
        if current:
            context = (
                f"\n\nCurrent program (change it, do not start over):\n```python\n{current}```"
                f"\nLocked parameters (never change): {', '.join(locked) or 'none'}"
            )
        plan = await self.ask(
            "Planner",
            "planner",
            prompts.PART_PLANNER,
            f"Request: {request}{context}",
            schemas.PART_PLAN,
            "Planning the part",
        )
        await self.trace(
            "Planner",
            "agent",
            "ok",
            f"Plan: {plan.get('name', 'part')} in {plan.get('material', '?')}, "
            f"{len(plan.get('features', []))} features, "
            f"{len(plan.get('parameters', []))} parameters",
            f"{plan.get('summary', '')}\n{self.meta(plan)}",
        )
        plan_text = json.dumps({k: v for k, v in plan.items() if k != "_meta"}, indent=1)
        written = await self.ask(
            "Modeler",
            "modeler",
            prompts.PART_MODELER,
            f"Request: {request}\n\nPlan:\n{plan_text}{context}",
            schemas.PROGRAM,
            "Writing the part program",
        )
        code = code_from_reply(written.get("code", ""))
        await self.trace(
            "Modeler",
            "agent",
            "ok",
            f"Wrote the part program ({code.count(chr(10))} lines)",
            f"{written.get('notes', '')}\n{self.meta(written)}",
        )

        requirements: dict[str, Any] | None = None
        review: dict[str, Any] | None = None
        rounds = 0
        while True:
            evaluation = await self.evaluate_part(code, plan, locked, requirements, fea)
            code = evaluation.code
            if requirements is None and evaluation.program is not None:
                requirements = requirement_values(evaluation.program)
            result = verdict(evaluation.checks)
            blocking: list[dict[str, Any]] = []
            review = None
            if result["status"] != "fail":
                review = await self.review_part(request, plan_text, evaluation)
                blocking = [i for i in review.get("issues", []) if i.get("severity") == "blocking"]
            if (result["status"] != "fail" and not blocking) or rounds >= self.deps.max_rounds:
                break
            rounds += 1
            code = await self.fix_part(request, plan_text, evaluation, blocking, locked, rounds)

        status = result["status"]
        fea_result = next((c for c in evaluation.checks if c.id == "fea"), None)
        why = (
            "FEA did not run"
            if fea_result is None or fea_result.status == "skip"
            else "the FEA result is not trusted"
        )
        title = {
            "pass": "PASS: every check passed",
            "unverified": f"Built and checked, but its strength is not shown: {why}",
            "fail": f"FAIL after {rounds} fix rounds: {result['errors']} checks still fail",
        }[status]
        await self.trace(
            "Verifier",
            "check",
            "ok" if status == "pass" else "fail",
            title,
            fea_result.message if fea_result and status == "unverified" else "",
        )
        return {
            "type": "result",
            "domain": "part",
            "verdict": result,
            "review": _clean(review),
            "plan": _clean(plan),
            "rounds": rounds,
            "cost_usd": self.cost,
            "part": evaluation.payload,
            "fea": evaluation.fea,
        }

    async def evaluate_part(
        self,
        code: str,
        plan: dict[str, Any],
        locked: dict[str, float],
        requirements: dict[str, Any] | None,
        fea: bool,
    ) -> Evaluation:
        code, moved = enforce_locks(code, locked)
        if moved:
            await self.trace(
                "Verifier", "check", "info", "Put locked parameters back", ", ".join(moved)
            )
        program: Program | None = None
        program_error: ProgramError | None = None
        try:
            program = parse_program(code)
        except ProgramError as error:
            program_error = error
        await self.emit({"type": "progress", "agent": "Builder", "title": "Building the part"})
        build = await run_in_threadpool(self.deps.builder.build, code)
        payload = self.deps.part_payload(code, build)
        await self.emit({"type": "part", "part": payload})
        if build.ok:
            stats = build.data["stats"]
            size = " x ".join(f"{v:.0f}" for v in stats["bbox"]["size"])
            await self.trace(
                "Builder", "check", "ok", f"Built in {build.elapsed_ms / 1000:.1f} s: {size} mm"
            )
        else:
            error = build.data.get("error") or {}
            where = f" in {error['feature']}" if error.get("feature") else ""
            await self.trace(
                "Builder", "check", "fail", f"Build failed{where}", error.get("message", "")
            )
        checks = part_checks(
            code,
            program,
            program_error,
            build.data,
            plan=plan,
            locked=locked,
            requirements=requirements,
        )
        evaluation = Evaluation(code, program, build, checks, payload=payload)
        failed = [c for c in checks if c.status == "fail"]
        if fea and program is not None and program.analysis is not None and not failed:
            ccx = self.deps.ccx()
            if ccx.available:
                await self.emit(
                    {"type": "progress", "agent": "FEA Critic", "title": "Running the load case"}
                )
                evaluation.fea = await run_in_threadpool(analyze_build, build, program, ccx)
                check = fea_check(evaluation.fea)
                checks.append(check)
                await self.trace(
                    "FEA Critic",
                    "check",
                    {"pass": "ok", "fail": "fail"}.get(check.status, "info"),
                    f"FEA {check.status.upper()}: {check.message}",
                )
            else:
                checks.append(Check("fea", "Survives its load case (FEA)", "skip", ccx.message))
        for check in checks:
            if check.status in ("fail", "warn") and check.id != "fea":
                await self.trace(
                    "Verifier",
                    "check",
                    "fail" if check.status == "fail" else "info",
                    f"{check.label}: {check.status}",
                    check.message,
                )
        passed = sum(1 for c in checks if c.status == "pass")
        await self.trace(
            "Verifier",
            "check",
            "fail" if any(c.status == "fail" for c in checks) else "ok",
            f"{passed} of {len(checks)} checks pass",
        )
        return evaluation

    async def review_part(
        self, request: str, plan_text: str, evaluation: Evaluation
    ) -> dict[str, Any]:
        build = evaluation.build
        facts = []
        if build is not None and build.ok:
            stats = build.data["stats"]
            facts.append(
                "Measured: size "
                + " x ".join(f"{v:.1f}" for v in stats["bbox"]["size"])
                + f" mm, volume {stats['volume_mm3'] / 1000:.1f} cm^3, {stats['faces']} faces"
            )
        if evaluation.fea and evaluation.fea.get("ok"):
            facts.append(f"FEA: {fea_check(evaluation.fea).message}")
        facts += [f"Check {c.label}: {c.status} {c.message}" for c in evaluation.checks]
        try:
            review = await self.ask(
                "Verifier",
                "verifier",
                prompts.REVIEWER,
                f"Request: {request}\n\nPlan:\n{plan_text}\n\nProgram:\n```python\n"
                f"{evaluation.code}```\n\n" + "\n".join(facts),
                schemas.REVIEW,
                "Reviewing the design against the request",
            )
        except StopRun:
            await self.trace(
                "Verifier", "agent", "info", "Skipped the design review; the checks still stand"
            )
            return {"matches_request": None, "summary": "Review unavailable", "issues": []}
        issues = review.get("issues", [])
        blocking = [i for i in issues if i.get("severity") == "blocking"]
        await self.trace(
            "Verifier",
            "agent",
            "fail" if blocking else "ok",
            "Review: "
            + (
                f"{len(blocking)} blocking issues"
                if blocking
                else "matches the request" + (f" ({len(issues)} minor notes)" if issues else "")
            ),
            "\n".join(f"{i.get('where')}: {i.get('message')}" for i in issues)
            + f"\n{self.meta(review)}",
        )
        return review

    async def fix_part(
        self,
        request: str,
        plan_text: str,
        evaluation: Evaluation,
        blocking: list[dict[str, Any]],
        locked: dict[str, float],
        round_no: int,
    ) -> str:
        failures = []
        for check in evaluation.checks:
            if check.status != "fail":
                continue
            where = []
            if check.feature:
                where.append(f"feature {check.feature}")
            if check.line:
                where.append(f"line {check.line}")
            text = f"[{check.id}] {check.label}: {check.message}"
            if where:
                text += f" ({', '.join(where)})"
            if check.id == "fea" and evaluation.fea and evaluation.build is not None:
                peak = (evaluation.fea.get("result") or {}).get("peak_at")
                near = nearest_feature(evaluation.build.data, peak)
                if peak:
                    text += f"; stress peaks at ({', '.join(f'{v:.1f}' for v in peak)}) mm"
                if near:
                    text += f", on faces made by {near}"
            failures.append(text)
        failures += [f"[review] {i.get('where')}: {i.get('message')}" for i in blocking]
        fixed = await self.ask(
            "Fixer",
            "fixer",
            prompts.PART_FIXER,
            f"Request: {request}\n\nPlan:\n{plan_text}\n\nProgram:\n```python\n{evaluation.code}"
            f"```\n\nFailures:\n{_bullets(failures)}\n\nLocked parameters: "
            f"{', '.join(locked) or 'none'}",
            schemas.FIX,
            f"Fixing round {round_no}",
        )
        await self.trace(
            "Fixer",
            "agent",
            "ok",
            f"Round {round_no}: {fixed.get('diagnosis', '')}",
            _bullets(fixed.get("changes", [])) + f"\n{self.meta(fixed)}",
        )
        return code_from_reply(fixed.get("code", ""))

    # ----------------------------------------------------------------- boards

    async def board(self, request: str, current: str | None) -> dict:
        locked = _locked(current)
        context = ""
        if current:
            context = (
                f"\n\nCurrent board program (change it, do not start over):\n```python\n"
                f"{current}```\nLocked parameters (never change): {', '.join(locked) or 'none'}"
            )
        plan = await self.ask(
            "Planner",
            "planner",
            prompts.BOARD_PLANNER,
            f"Request: {request}{context}",
            schemas.BOARD_PLAN,
            "Planning the board",
        )
        await self.trace(
            "Planner",
            "agent",
            "ok",
            f"Plan: {plan.get('name', 'board')}, {len(plan.get('parts', []))} parts, "
            f"{len(plan.get('nets', []))} nets",
            f"{plan.get('summary', '')}\n{self.meta(plan)}",
        )
        plan_text = json.dumps({k: v for k, v in plan.items() if k != "_meta"}, indent=1)
        written = await self.ask(
            "Modeler",
            "modeler",
            prompts.BOARD_MODELER,
            f"Request: {request}\n\nPlan:\n{plan_text}{context}",
            schemas.PROGRAM,
            "Writing the board program",
        )
        code = code_from_reply(written.get("code", ""))
        await self.trace(
            "Modeler",
            "agent",
            "ok",
            f"Wrote the board program ({code.count(chr(10))} lines)",
            f"{written.get('notes', '')}\n{self.meta(written)}",
        )
        rounds = 0
        review: dict[str, Any] | None = None
        while True:
            evaluation = await self.evaluate_board(code, locked)
            code = evaluation.code
            result = evaluation.board_checks or {}
            blocking: list[dict[str, Any]] = []
            review = None
            if result.get("status") == "pass":
                review = await self.review_board(request, plan_text, evaluation)
                blocking = [i for i in review.get("issues", []) if i.get("severity") == "blocking"]
            if (result.get("status") == "pass" and not blocking) or rounds >= self.deps.max_rounds:
                break
            rounds += 1
            code = await self.fix_board(request, plan_text, evaluation, blocking, locked, rounds)

        passed = result.get("status") == "pass"
        await self.trace(
            "Verifier",
            "check",
            "ok" if passed else "fail",
            "PASS: every design and electrical rule check passed"
            if passed
            else f"FAIL after {rounds} fix rounds: {result.get('errors', 0)} errors remain",
        )
        return {
            "type": "result",
            "domain": "board",
            "verdict": result,
            "review": _clean(review),
            "plan": _clean(plan),
            "rounds": rounds,
            "cost_usd": self.cost,
            "board": evaluation.payload,
        }

    async def evaluate_board(self, code: str, locked: dict[str, float]) -> Evaluation:
        code, moved = enforce_locks(code, locked)
        if moved:
            await self.trace(
                "Verifier", "check", "info", "Put locked parameters back", ", ".join(moved)
            )
        await self.emit(
            {"type": "progress", "agent": "Router", "title": "Routing and checking the board"}
        )
        try:
            payload = await run_in_threadpool(self.deps.boards.design, code)
        except (ProgramError, KeyError) as error:
            line = getattr(error, "line", None)
            message = error.args[0] if isinstance(error, KeyError) else str(error)
            check = {
                "id": "program",
                "label": "Board program is valid",
                "kind": "program",
                "status": "fail",
                "looked_at": 1,
                "findings": [
                    {
                        "check": "program",
                        "severity": "error",
                        "message": message + (f" (line {line})" if line else ""),
                        "at": None,
                        "nets": [],
                    }
                ],
            }
            await self.trace("Verifier", "check", "fail", "Board program is invalid", message)
            return Evaluation(
                code,
                None,
                None,
                [],
                board_checks={"status": "fail", "errors": 1, "warnings": 0, "checks": [check]},
            )
        await self.emit({"type": "board", "board": payload})
        routing = payload["routing"]
        checks = payload["checks"]
        await self.trace(
            "Router",
            "check",
            "fail" if routing["unrouted"] else "ok",
            f"Routed {routing['routed_nets']} of {routing['nets']} nets: "
            f"{routing['tracks']} tracks, {routing['vias']} vias",
        )
        for check in checks["checks"]:
            if check["status"] == "fail":
                await self.trace(
                    "Verifier",
                    "check",
                    "fail",
                    f"{check['kind'].upper()} {check['label']}: fail",
                    "\n".join(f["message"] for f in check["findings"][:6]),
                )
        await self.trace(
            "Verifier",
            "check",
            "ok" if checks["status"] == "pass" else "fail",
            f"{checks['status'].upper()}: {checks['errors']} errors, {checks['warnings']} warnings",
        )
        return Evaluation(code, None, None, [], payload=payload, board_checks=checks)

    async def review_board(
        self, request: str, plan_text: str, evaluation: Evaluation
    ) -> dict[str, Any]:
        payload = evaluation.payload or {}
        facts = [
            f"Board {payload['board']['width']} x {payload['board']['height']} mm",
            "Parts: " + ", ".join(f"{p['ref']} {p['name']} {p['value']}" for p in payload["parts"]),
            "Nets: "
            + "; ".join(
                f"{n['name']} ({n['kind']}, {n['current']} A): {' '.join(n['pins'])}"
                for n in payload["nets"]
            ),
            f"DRC/ERC: {payload['checks']['status']}, {payload['checks']['warnings']} warnings",
        ]
        try:
            review = await self.ask(
                "Verifier",
                "verifier",
                prompts.REVIEWER,
                f"Request: {request}\n\nPlan:\n{plan_text}\n\nBoard program:\n```python\n"
                f"{evaluation.code}```\n\n" + "\n".join(facts),
                schemas.REVIEW,
                "Reviewing the board against the request",
            )
        except StopRun:
            await self.trace(
                "Verifier", "agent", "info", "Skipped the design review; the checks still stand"
            )
            return {"matches_request": None, "summary": "Review unavailable", "issues": []}
        issues = review.get("issues", [])
        blocking = [i for i in issues if i.get("severity") == "blocking"]
        await self.trace(
            "Verifier",
            "agent",
            "fail" if blocking else "ok",
            "Review: "
            + (f"{len(blocking)} blocking issues" if blocking else "matches the request"),
            "\n".join(f"{i.get('where')}: {i.get('message')}" for i in issues)
            + f"\n{self.meta(review)}",
        )
        return review

    async def fix_board(
        self,
        request: str,
        plan_text: str,
        evaluation: Evaluation,
        blocking: list[dict[str, Any]],
        locked: dict[str, float],
        round_no: int,
    ) -> str:
        failures = []
        for check in (evaluation.board_checks or {}).get("checks", []):
            for finding in check["findings"]:
                if finding["severity"] == "error":
                    at = finding.get("at")
                    where = f" at ({at[0]:.1f}, {at[1]:.1f}) mm" if at else ""
                    failures.append(f"[{check['id']}] {finding['message']}{where}")
        for item in (evaluation.payload or {}).get("routing", {}).get("unrouted", []):
            failures.append(f"[unrouted] {json.dumps(item)}")
        failures += [f"[review] {i.get('where')}: {i.get('message')}" for i in blocking]
        fixed = await self.ask(
            "Fixer",
            "fixer",
            prompts.BOARD_FIXER,
            f"Request: {request}\n\nPlan:\n{plan_text}\n\nBoard program:\n```python\n"
            f"{evaluation.code}```\n\nFailures:\n{_bullets(failures[:40])}\n\nLocked "
            f"parameters: {', '.join(locked) or 'none'}",
            schemas.FIX,
            f"Fixing round {round_no}",
        )
        await self.trace(
            "Fixer",
            "agent",
            "ok",
            f"Round {round_no}: {fixed.get('diagnosis', '')}",
            _bullets(fixed.get("changes", [])) + f"\n{self.meta(fixed)}",
        )
        return code_from_reply(fixed.get("code", ""))


def _clean(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    return {k: v for k, v in data.items() if k != "_meta"}


async def run_agents(
    deps: AgentDeps,
    emit: Emit,
    domain: str,
    request: str,
    current: str | None = None,
    *,
    fea: bool = True,
) -> None:
    """Run one request end to end, emitting events. Never raises for model failures."""
    run = AgentRun(deps, emit)
    try:
        if domain == "board":
            result = await run.board(request, current)
        else:
            result = await run.part(request, current, fea=fea)
    except StopRun as error:
        await emit({"type": "error", "message": str(error), "cost_usd": run.cost})
        return
    await emit(result)
