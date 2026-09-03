from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlmodel import Session, select

from . import credentials
from .agent.planner import AgentError, plan_next_action
from .agent.schemas import NextActionRequest
from .config import settings
from .database import get_session
from .canvas.reconcile import reconcile_scan
from .canvas.schemas import CanvasScanResult
from .models import Assignment, AssignmentState, BackgroundJob, CalendarEvent, CanvasWorkerState, Course, DomainEvent, MasteryRecord, ModelRoute, ProviderConfiguration, StudyBlock, SyncRun, Topic
from .llm.factory import brain_status, get_brain
from .llm.providers import SUPPORTED_PROVIDERS
from .llm.routing import ModelTask
from .pipeline import complete_demo_calibration, ensure_calibration
from .schemas import AssignmentRead, BlockPatch, CalendarItemRead, CalibrationSubmission, CanvasScanRequest, CourseRead, ProviderCredential, ProviderSelection, ScheduleRequest
from .services import recompute_schedule


router = APIRouter()


def assignment_view(assignment: Assignment, course: Course) -> AssignmentRead:
    return AssignmentRead(**assignment.model_dump(), course=CourseRead.model_validate(course))


@router.get("/status")
def status(session: Session = Depends(get_session)):
    last_sync = session.exec(select(SyncRun).order_by(SyncRun.created_at.desc())).first()
    return {"status": "ok", "mode": "demo", "last_sync": last_sync.finished_at if last_sync else None}


@router.get("/courses", response_model=list[CourseRead])
def courses(session: Session = Depends(get_session)):
    return session.exec(select(Course).order_by(Course.code)).all()


@router.get("/assignments", response_model=list[AssignmentRead])
def assignments(session: Session = Depends(get_session)):
    course_map = {c.id: c for c in session.exec(select(Course)).all()}
    items = session.exec(select(Assignment).order_by(Assignment.due_at)).all()
    return [assignment_view(item, course_map[item.course_id]) for item in items]


@router.get("/assignments/upcoming", response_model=list[AssignmentRead])
def upcoming_assignments(session: Session = Depends(get_session)):
    now = datetime.now()
    course_map = {c.id: c for c in session.exec(select(Course)).all()}
    items = session.exec(select(Assignment).where(Assignment.due_at >= now, Assignment.submitted == False).order_by(Assignment.due_at)).all()  # noqa: E712
    return [assignment_view(item, course_map[item.course_id]) for item in items]


@router.get("/calendar", response_model=list[CalendarItemRead])
def calendar(start: Optional[datetime] = None, end: Optional[datetime] = None, session: Session = Depends(get_session)):
    start = start or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = end or start + timedelta(days=7)
    events = session.exec(select(CalendarEvent).where(CalendarEvent.end_at > start, CalendarEvent.start_at < end)).all()
    blocks = session.exec(select(StudyBlock).where(StudyBlock.end_at > start, StudyBlock.start_at < end)).all()
    result = [CalendarItemRead(id=f"event-{e.id}", title=e.title, start_at=e.start_at, end_at=e.end_at, kind=e.kind, color=e.color, locked=e.locked) for e in events]
    result += [CalendarItemRead(id=f"block-{b.id}", title=b.title, start_at=b.start_at, end_at=b.end_at, kind=b.kind, color="#D9895B", locked=b.locked, assignment_id=b.assignment_id) for b in blocks]
    return sorted(result, key=lambda item: item.start_at)


@router.get("/mastery")
def mastery(session: Session = Depends(get_session)):
    topics = {t.id: t for t in session.exec(select(Topic)).all()}
    courses = {c.id: c for c in session.exec(select(Course)).all()}
    records = session.exec(select(MasteryRecord)).all()
    return [{"topic": topics[r.topic_id].name, "topic_key": topics[r.topic_id].topic_key, "course": courses[topics[r.topic_id].course_id].name, "score": r.mastery_score, "confidence": r.confidence, "evidence_count": r.evidence_count} for r in records]


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session)):
    all_assignments = assignments(session)
    events = calendar(session=session)
    calibration = [a for a in all_assignments if a.state == AssignmentState.AWAITING_CALIBRATION]
    scheduled = sum(a.scheduled_minutes for a in all_assignments if a.due_at >= datetime.now())
    return {"assignments": all_assignments, "events": events, "calibration_count": len(calibration), "high_risk_count": sum(a.risk == "HIGH" for a in all_assignments), "scheduled_minutes": scheduled}


@router.get("/activity")
def activity(limit: int = 50, session: Session = Depends(get_session)):
    events = session.exec(select(DomainEvent).order_by(DomainEvent.created_at.desc()).limit(min(max(limit, 1), 200))).all()
    return [{"id": event.id, "type": event.event_type, "entity_type": event.entity_type, "entity_id": event.entity_id, "payload": event.payload, "created_at": event.created_at, "correlation_id": event.correlation_id} for event in events]


@router.get("/canvas/status")
def canvas_status(session: Session = Depends(get_session)):
    state = session.exec(select(CanvasWorkerState)).first()
    if not state:
        return {"status": "DISCONNECTED", "session_status": "NOT_CONFIGURED", "last_scan_at": None, "next_scan_at": None, "courses_observed": 0, "last_result": "Connect Canvas to begin"}
    return state


@router.get("/providers")
def providers(session: Session = Depends(get_session)):
    items = session.exec(select(ProviderConfiguration).order_by(ProviderConfiguration.provider)).all()
    return [{"provider": item.provider, "model": item.model, "base_url": item.base_url} for item in items]


@router.get("/providers/brain")
def brain(session: Session = Depends(get_session)):
    """Which Brain is selected and whether it can actually be called right now."""
    return brain_status(session)


@router.put("/providers/{provider}/credential", status_code=204)
def push_provider_credential(provider: str, payload: ProviderCredential, x_cadence_runtime_token: str | None = Header(default=None)):
    """Receive an API key from the desktop vault for this process only.

    The key is held in memory and never written to SQLite. The desktop app
    re-pushes it on every launch. When a runtime token is configured, callers
    must present it, so another local process cannot seed credentials.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported Brain provider")
    if settings.runtime_token and x_cadence_runtime_token != settings.runtime_token:
        raise HTTPException(status_code=403, detail="Invalid runtime token")
    credentials.set_key(provider, payload.api_key)
    return Response(status_code=204)


@router.put("/providers/{provider}")
def select_brain_provider(provider: str, payload: ProviderSelection, session: Session = Depends(get_session)):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=422, detail="Unsupported Brain provider")
    if provider == "custom" and not (payload.base_url or "").strip():
        raise HTTPException(status_code=422, detail="A base URL is required for a custom provider")
    configuration = session.exec(select(ProviderConfiguration).where(ProviderConfiguration.provider == provider)).first()
    if not configuration:
        configuration = ProviderConfiguration(provider=provider, model=payload.model, base_url=payload.base_url, credential_key=f"{provider}_api_key")
        session.add(configuration)
        session.flush()
    else:
        configuration.model = payload.model
        if payload.base_url is not None:
            configuration.base_url = payload.base_url
        configuration.credential_key = f"{provider}_api_key"
    for task in ModelTask:
        if task == ModelTask.CANVAS_COMPUTER_USE:
            continue
        route = session.exec(select(ModelRoute).where(ModelRoute.task == task.value)).first()
        if route:
            route.provider_configuration_id = configuration.id
            session.add(route)
        else:
            session.add(ModelRoute(task=task.value, provider_configuration_id=configuration.id))
    session.commit()
    return {"provider": configuration.provider, "model": configuration.model, "brain_routes_updated": len(ModelTask) - 1}


@router.post("/agent/next-action")
def agent_next_action(payload: NextActionRequest, session: Session = Depends(get_session)):
    """Plan one browser-agent step from a page observation.

    The executor holds the browser; this only decides what to do next, so a
    rejected or malformed action costs a step rather than touching the page.
    """
    try:
        envelope = plan_next_action(session, payload)
    except AgentError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return envelope.model_dump()


@router.post("/canvas/scans")
def ingest_canvas_scan(scan: CanvasScanResult, session: Session = Depends(get_session)):
    return reconcile_scan(session, scan)


@router.post("/canvas/scan-requests")
def request_canvas_scan(payload: CanvasScanRequest, session: Session = Depends(get_session)):
    active = session.exec(select(BackgroundJob).where(BackgroundJob.job_type.in_(["canvas.scan", "canvas.daily_integrity_scan"]), BackgroundJob.status.in_(["PENDING", "RUNNING"]))).first()
    if active:
        return {"job_id": active.id, "status": active.status, "deduplicated": True}
    job = BackgroundJob(job_key=f"canvas.scan:{uuid4()}", job_type="canvas.daily_integrity_scan" if payload.integrity_scan else "canvas.scan", payload=payload.model_dump())
    session.add(job)
    session.commit()
    session.refresh(job)
    return {"job_id": job.id, "status": job.status, "deduplicated": False}


@router.get("/assignments/{assignment_id}/calibration")
def get_calibration(assignment_id: int, session: Session = Depends(get_session)):
    from .models import Calibration, CalibrationQuestion
    calibration = session.exec(select(Calibration).where(Calibration.assignment_id == assignment_id).order_by(Calibration.id.desc())).first()
    assignment = session.get(Assignment, assignment_id)
    if not calibration and assignment and assignment.state == AssignmentState.AWAITING_CALIBRATION:
        calibration = ensure_calibration(session, assignment)
    if not calibration:
        raise HTTPException(status_code=404, detail="Calibration not found")
    questions = session.exec(select(CalibrationQuestion).where(CalibrationQuestion.calibration_id == calibration.id).order_by(CalibrationQuestion.position)).all()
    return {"id": calibration.id, "status": calibration.status, "questions": [{"id": q.id, "position": q.position, "dimension": q.dimension, "prompt": q.prompt, "topics": q.expected_topics} for q in questions]}


@router.post("/assignments/{assignment_id}/calibration")
def submit_calibration(assignment_id: int, payload: CalibrationSubmission, session: Session = Depends(get_session)):
    assignment = session.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    try:
        if payload.demo_scores is not None:
            scores = payload.demo_scores
        else:
            from .llm.mock import DemoBrainProvider
            from .llm.providers import BrainError
            try:
                scores = get_brain(session).grade_calibration(payload.answers)
            except BrainError:
                # A provider outage must not block calibration; grade deterministically.
                scores = DemoBrainProvider().grade_calibration(payload.answers)
        calibration, run = complete_demo_calibration(session, assignment, payload.answers, scores)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"calibration_id": calibration.id, "classification": calibration.mastery_classification, "overall_score": calibration.overall_score, "estimated_minutes": assignment.estimated_minutes, "schedule_run_id": run.id, "blocks_created": run.blocks_created}


@router.post("/schedule/recompute")
def recompute(payload: ScheduleRequest, session: Session = Depends(get_session)):
    run = recompute_schedule(session, payload.reason)
    return {"id": run.id, "status": run.status, "blocks_created": run.blocks_created, "unscheduled_minutes": run.unscheduled_minutes}


@router.patch("/calendar/blocks/{block_id}")
def patch_block(block_id: int, payload: BlockPatch, session: Session = Depends(get_session)):
    block = session.get(StudyBlock, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Study block not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(block, key, value)
    if block.end_at <= block.start_at:
        raise HTTPException(status_code=422, detail="Block must end after it starts")
    session.add(block)
    session.commit()
    session.refresh(block)
    return block
