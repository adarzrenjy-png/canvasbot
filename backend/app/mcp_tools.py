from __future__ import annotations

from datetime import datetime, timedelta
from secrets import compare_digest
from uuid import uuid4

from sqlmodel import Session, select

from .config import settings
from .database import engine
from .models import Assignment, BackgroundJob, CanvasWorkerState, Course, DomainEvent, StudyBlock


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def list_courses() -> list[dict]:
    with Session(engine) as session:
        courses = session.exec(select(Course).where(Course.archived == False).order_by(Course.code)).all()  # noqa: E712
        return [
            {
                "id": course.id,
                "code": course.code,
                "name": course.name,
                "term": course.term,
                "instructor": course.instructor,
                "status": course.status,
            }
            for course in courses
        ]


def list_assignments(days: int = 30, include_completed: bool = False) -> list[dict]:
    days = min(max(days, 1), 180)
    now = datetime.now()
    with Session(engine) as session:
        courses = {course.id: course for course in session.exec(select(Course)).all()}
        query = select(Assignment).where(Assignment.due_at >= now, Assignment.due_at <= now + timedelta(days=days))
        if not include_completed:
            query = query.where(Assignment.submitted == False)  # noqa: E712
        assignments = session.exec(query.order_by(Assignment.due_at)).all()
        return [
            {
                "id": item.id,
                "course": courses[item.course_id].code,
                "title": item.title,
                "due_at": _iso(item.due_at),
                "state": item.state.value,
                "risk": item.risk.value,
                "estimated_minutes": item.estimated_minutes,
                "scheduled_minutes": item.scheduled_minutes,
                "canonical_url": item.canonical_url,
            }
            for item in assignments
        ]


def get_week_plan(days: int = 7) -> list[dict]:
    days = min(max(days, 1), 31)
    now = datetime.now()
    with Session(engine) as session:
        assignments = {item.id: item for item in session.exec(select(Assignment)).all()}
        blocks = session.exec(
            select(StudyBlock)
            .where(StudyBlock.end_at >= now, StudyBlock.start_at <= now + timedelta(days=days))
            .order_by(StudyBlock.start_at)
        ).all()
        return [
            {
                "id": block.id,
                "assignment_id": block.assignment_id,
                "title": block.title,
                "start_at": _iso(block.start_at),
                "end_at": _iso(block.end_at),
                "locked": block.locked,
                "completed": block.completed,
                "due_at": _iso(assignments[block.assignment_id].due_at) if block.assignment_id in assignments else None,
            }
            for block in blocks
        ]


def planner_status() -> dict[str, object]:
    with Session(engine) as session:
        state = session.exec(select(CanvasWorkerState)).first()
        active_job = session.exec(
            select(BackgroundJob).where(BackgroundJob.status.in_(["PENDING", "RUNNING"])).order_by(BackgroundJob.created_at)
        ).first()
        return {
            "mode": "demo" if settings.demo_mode else "live",
            "canvas": {
                "status": state.status if state else "DISCONNECTED",
                "session_status": state.session_status if state else "NOT_CONFIGURED",
                "last_scan_at": _iso(state.last_scan_at) if state else None,
                "next_scan_at": _iso(state.next_scan_at) if state else None,
                "last_result": state.last_result if state else None,
            },
            "active_job": {"id": active_job.id, "type": active_job.job_type, "status": active_job.status} if active_job else None,
        }


def recent_changes(limit: int = 20) -> list[dict]:
    limit = min(max(limit, 1), 100)
    with Session(engine) as session:
        events = session.exec(select(DomainEvent).order_by(DomainEvent.created_at.desc()).limit(limit)).all()
        return [
            {
                "id": event.id,
                "type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "payload": event.payload,
                "created_at": _iso(event.created_at),
            }
            for event in events
        ]


def request_canvas_scan(write_token: str, integrity_scan: bool = False) -> dict[str, object]:
    expected = settings.mcp_write_token
    if not expected or not compare_digest(write_token, expected):
        raise PermissionError("A valid local MCP write token is required")

    with Session(engine) as session:
        active = session.exec(
            select(BackgroundJob).where(
                BackgroundJob.job_type.in_(["canvas.scan", "canvas.daily_integrity_scan"]),
                BackgroundJob.status.in_(["PENDING", "RUNNING"]),
            )
        ).first()
        if active:
            return {"job_id": active.id, "status": active.status, "deduplicated": True}

        job = BackgroundJob(
            job_key=f"canvas.scan:{uuid4()}",
            job_type="canvas.daily_integrity_scan" if integrity_scan else "canvas.scan",
            payload={"integrity_scan": integrity_scan, "source": "mcp"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return {"job_id": job.id, "status": job.status, "deduplicated": False}
