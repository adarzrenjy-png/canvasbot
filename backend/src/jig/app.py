"""FastAPI application: part builds, parameter edits, exports, and model status."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jig import __version__
from jig.ai.client import AIError, ModelClient
from jig.ai.config import load_model_config
from jig.ai.cost import CostMeter
from jig.cad.builder import Builder, BuildResult
from jig.cad.program import ProgramError, parse_program, set_param_flags, set_params
from jig.cad.samples import SAMPLES
from jig.fea.ccx import find_ccx
from jig.fea.service import analyze_build
from jig.report.document import build_report
from jig.settings import Settings, get_settings

DOWNLOADS = {
    "step": ("part.step", "application/step"),
    "stl": ("part.stl", "model/stl"),
    "py": ("part.py", "text/x-python"),
}


class Services:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.builder = Builder(settings.builds_dir, timeout_s=settings.build_timeout_s)
        config = load_model_config()
        self.meter = CostMeter(config=config, budget_usd=settings.budget_usd)
        self.models = ModelClient(config, self.meter, key_lookup=Settings.api_key)


class CodeRequest(BaseModel):
    code: str = Field(max_length=200_000)


class ParamsRequest(CodeRequest):
    updates: dict[str, float]


class AnalyzeRequest(CodeRequest):
    build_id: str | None = None


class LockRequest(CodeRequest):
    name: str
    locked: bool


class BudgetRequest(BaseModel):
    budget_usd: float = Field(ge=0, le=150)


def _program_payload(code: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        return parse_program(code).to_dict(), None
    except ProgramError as error:
        return None, {"message": str(error), "line": error.line}


def _part_payload(code: str, result: BuildResult) -> dict[str, Any]:
    program, program_error = _program_payload(code)
    return {
        "code": code,
        "program": program,
        "program_error": program_error,
        "build": {"id": result.build_id, "elapsed_ms": result.elapsed_ms, **result.data},
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = Services(settings)
        services.builder.warm()
        app.state.services = services
        yield
        services.builder.close()

    app = FastAPI(title="Jig", version=__version__, lifespan=lifespan)

    def services() -> Services:
        return app.state.services

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        s = services()
        return {
            "version": __version__,
            "ai": s.models.status(),
            "fea": find_ccx(settings.ccx_path).to_dict(),
            "session": s.meter.summary(),
        }

    @app.get("/api/samples")
    def samples() -> list[str]:
        return sorted(SAMPLES)

    @app.get("/api/samples/{name}")
    async def build_sample(name: str) -> dict[str, Any]:
        code = SAMPLES.get(name)
        if code is None:
            raise HTTPException(404, f"No sample named {name!r}")
        result = await run_in_threadpool(services().builder.build, code)
        return _part_payload(code, result)

    @app.post("/api/parts/build")
    async def build(request: CodeRequest) -> dict[str, Any]:
        result = await run_in_threadpool(services().builder.build, request.code)
        return _part_payload(request.code, result)

    @app.post("/api/parts/parse")
    def parse(request: CodeRequest) -> dict[str, Any]:
        program, program_error = _program_payload(request.code)
        return {"code": request.code, "program": program, "program_error": program_error}

    @app.post("/api/parts/params")
    async def update_params(request: ParamsRequest) -> dict[str, Any]:
        try:
            code = set_params(request.code, request.updates)
        except ProgramError as error:
            raise HTTPException(422, str(error)) from error
        result = await run_in_threadpool(services().builder.build, code)
        return _part_payload(code, result)

    @app.post("/api/parts/lock")
    def lock(request: LockRequest) -> dict[str, Any]:
        try:
            code = set_param_flags(request.code, request.name, locked=request.locked)
        except (ProgramError, KeyError) as error:
            raise HTTPException(422, f"Cannot change lock: {error}") from error
        program, program_error = _program_payload(code)
        return {"code": code, "program": program, "program_error": program_error}

    @app.post("/api/parts/analyze")
    async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
        """Run the part's load case (FEA) on a build of exactly this code."""
        s = services()
        try:
            program = parse_program(request.code)
        except ProgramError as error:
            raise HTTPException(422, str(error)) from error
        build = s.builder.load(request.build_id) if request.build_id else None
        if build is None or (build.out_dir / "part.py").read_text(encoding="utf-8") != request.code:
            build = await run_in_threadpool(s.builder.build, request.code)
        ccx = find_ccx(settings.ccx_path)
        fea = await run_in_threadpool(analyze_build, build, program, ccx)
        return {**_part_payload(request.code, build), "fea": fea}

    @app.get("/api/builds/{build_id}/report", response_class=HTMLResponse)
    def report(build_id: str, download: bool = False) -> HTMLResponse:
        build = services().builder.load(build_id)
        if build is None or not build.ok:
            raise HTTPException(404, "No finished build with that id (it may have been cleaned up)")
        code = (build.out_dir / "part.py").read_text(encoding="utf-8")
        fea_path = build.out_dir / "fea" / "fea.json"
        fea = json.loads(fea_path.read_text(encoding="utf-8")) if fea_path.is_file() else None
        html = build_report(code, parse_program(code), {"id": build_id, **build.data}, fea)
        headers = (
            {"Content-Disposition": 'attachment; filename="jig_report.html"'} if download else {}
        )
        return HTMLResponse(html, headers=headers)

    @app.get("/api/builds/{build_id}/download/{kind}")
    def download(build_id: str, kind: str) -> FileResponse:
        if kind not in DOWNLOADS:
            raise HTTPException(404, "Unknown export type")
        filename, media_type = DOWNLOADS[kind]
        path = services().builder.path_for(build_id, filename)
        if path is None:
            raise HTTPException(404, "That build has no such file (it may have been cleaned up)")
        return FileResponse(path, media_type=media_type, filename=f"jig_part.{kind}")

    @app.get("/api/session")
    def session() -> dict[str, Any]:
        return services().meter.summary()

    @app.put("/api/session/budget")
    def set_budget(request: BudgetRequest) -> dict[str, Any]:
        services().meter.set_budget(request.budget_usd)
        return services().meter.summary()

    @app.post("/api/ai/ping")
    async def ping() -> dict[str, Any]:
        s = services()
        try:
            result = await s.models.chat(
                "orchestrator",
                [{"role": "user", "content": "Reply with the single word: ready"}],
            )
        except AIError as error:
            raise HTTPException(503, str(error)) from error
        return {
            "reply": result.content.strip(),
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "cost_usd": result.cost_usd,
            "session": s.meter.summary(),
        }

    dist = _frontend_dist()
    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def _frontend_dist() -> Path | None:
    configured = os.environ.get("JIG_FRONTEND_DIST")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[3] / "frontend" / "dist")
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


def get_app() -> FastAPI:
    """Uvicorn factory entry point: `uvicorn jig.app:get_app --factory`."""
    return create_app()
