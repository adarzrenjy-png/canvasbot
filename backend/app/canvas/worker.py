from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select

from ..models import BackgroundJob, CanvasWorkerState, utcnow
from .reconcile import reconcile_scan
from .schemas import CanvasAssignmentObservation, CanvasCourseObservation, CanvasScanResult


def demo_scan(now: datetime | None = None) -> CanvasScanResult:
    now = now or utcnow()
    course_url = "https://rutgers.instructure.com/courses/4242"
    return CanvasScanResult(
        started_at=now,
        completed_at=now + timedelta(seconds=2),
        courses=[
            CanvasCourseObservation(
                canvas_url=course_url,
                visible_name="Engineering Mechanics: Statics",
                normalized_title="Engineering Mechanics: Statics",
                course_code="ME 201",
                term="Fall 2026",
                instructor="Professor Rivera",
            )
        ],
        assignments=[
            CanvasAssignmentObservation(
                canvas_url=f"{course_url}/assignments/9001",
                course_canvas_url=course_url,
                visible_title="Centroid and Moment of Inertia Set",
                normalized_title="Centroid and Moment of Inertia Set",
                due_at=(now + timedelta(days=5)).replace(hour=23, minute=59, second=0, microsecond=0),
                description="Solve the assigned centroid and area moment of inertia problems. Show the composite-area setup.",
                assignment_type="Problem set",
                points_possible=40,
                visible_date="Friday at 11:59 PM",
                metadata={"source": "demo_computer_use_worker"},
            )
        ],
    )


def run_pending_job_once(session: Session, *, demo_mode: bool) -> bool:
    job = session.exec(
        select(BackgroundJob)
        .where(
            BackgroundJob.job_type.in_(["canvas.scan", "canvas.daily_integrity_scan"]),
            BackgroundJob.status == "PENDING",
        )
        .order_by(BackgroundJob.scheduled_at)
    ).first()
    if not job:
        return False

    if not demo_mode:
        # The desktop computer-use worker claims live jobs. Keeping them pending here
        # avoids a second process racing or fabricating observations.
        return False

    state = session.exec(select(CanvasWorkerState)).first() or CanvasWorkerState()
    job.status = "RUNNING"
    job.started_at = utcnow()
    state.scan_in_progress = True
    state.status = "SCANNING"
    session.add(job)
    session.add(state)
    session.commit()

    try:
        reconcile_scan(session, demo_scan())
        job.status = "COMPLETED"
        job.finished_at = utcnow()
        session.add(job)
        session.commit()
    except Exception as error:
        session.rollback()
        failed = session.get(BackgroundJob, job.id)
        if failed:
            failed.status = "FAILED"
            failed.finished_at = utcnow()
            failed.last_error = str(error)
            failed.retry_count += 1
            session.add(failed)
            session.commit()
        raise
    return True
