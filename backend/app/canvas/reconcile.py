import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session, select

from ..events import emit_event
from ..models import (
    Announcement, Assignment, AssignmentState, CanvasWorkerState, Course, Exam,
    SyncRun, utcnow,
)
from ..pipeline import prepare_new_assignment
from ..config import settings
from .schemas import CanvasScanResult


def normalize_canvas_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Canvas identity must be an absolute HTTP(S) URL")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def content_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


@dataclass
class ReconciliationSummary:
    scan_id: str
    courses_created: int = 0
    courses_updated: int = 0
    assignments_created: int = 0
    assignments_updated: int = 0
    due_dates_changed: int = 0
    exams_created: int = 0
    announcements_created: int = 0
    events: list[str] = field(default_factory=list)

    @property
    def total_changes(self):
        return sum((self.courses_created, self.courses_updated, self.assignments_created, self.assignments_updated, self.exams_created, self.announcements_created))


def _course_for_observation(session: Session, observation, summary: ReconciliationSummary) -> Course:
    url = normalize_canvas_url(observation.canvas_url)
    course = session.exec(select(Course).where(Course.canvas_url == url)).first()
    if not course and observation.course_code:
        course = session.exec(select(Course).where(Course.code == observation.course_code)).first()
    now = utcnow()
    if not course:
        code = observation.course_code or f"CANVAS-{hashlib.sha1(url.encode()).hexdigest()[:7].upper()}"
        course = Course(name=observation.normalized_title, code=code, canvas_url=url, term=observation.term, instructor=observation.instructor, section=observation.section, first_observed_at=now, last_observed_at=now, metadata_json=observation.metadata)
        session.add(course)
        session.flush()
        summary.courses_created += 1
        summary.events.append("course.discovered")
        emit_event(session, "course.discovered", entity_type="course", entity_id=str(course.id), payload={"canvas_url": url, "name": course.name}, correlation_id=summary.scan_id)
    else:
        changed = course.name != observation.normalized_title or course.canvas_url != url or course.term != observation.term
        course.name = observation.normalized_title
        course.canvas_url = url
        course.term = observation.term
        course.instructor = observation.instructor
        course.section = observation.section
        course.last_observed_at = now
        course.metadata_json = observation.metadata
        if changed:
            summary.courses_updated += 1
            summary.events.append("course.updated")
            emit_event(session, "course.updated", entity_type="course", entity_id=str(course.id), payload={"name": course.name}, correlation_id=summary.scan_id)
    return course


def reconcile_scan(session: Session, scan: CanvasScanResult) -> ReconciliationSummary:
    summary = ReconciliationSummary(scan_id=scan.scan_id)
    emit_event(session, "canvas.scan.started", payload={"started_at": scan.started_at.isoformat()}, correlation_id=scan.scan_id)
    if scan.status in {"failed", "auth_required"}:
        state = session.exec(select(CanvasWorkerState)).first() or CanvasWorkerState()
        state.status = "AUTH_REQUIRED" if scan.status == "auth_required" else "ERROR"
        state.session_status = "EXPIRED" if scan.status == "auth_required" else state.session_status
        state.last_scan_at = scan.completed_at
        state.last_error = "; ".join(scan.warnings) or scan.status
        state.scan_in_progress = False
        session.add(state)
        emit_event(session, "canvas.scan.failed", payload={"status": scan.status, "warnings": scan.warnings}, correlation_id=scan.scan_id)
        session.commit()
        return summary

    course_map = {}
    for observation in scan.courses:
        course = _course_for_observation(session, observation, summary)
        course_map[normalize_canvas_url(observation.canvas_url)] = course

    new_assignments = []
    for observation in scan.assignments:
        url = normalize_canvas_url(observation.canvas_url)
        course_url = normalize_canvas_url(observation.course_canvas_url)
        course = course_map.get(course_url) or session.exec(select(Course).where(Course.canvas_url == course_url)).first()
        if not course:
            continue
        fingerprint = content_hash({"title": observation.normalized_title, "description": observation.description, "due_at": observation.due_at, "points": observation.points_possible, "type": observation.assignment_type})
        assignment = session.exec(select(Assignment).where(Assignment.canonical_url == url)).first()
        if not assignment:
            assignment = Assignment(course_id=course.id, title=observation.normalized_title, description=observation.description, due_at=observation.due_at, state=AssignmentState.DETECTED, assignment_type=observation.assignment_type, source_lms="canvas_browser", canonical_url=url, points_possible=observation.points_possible, available_from=observation.available_from, lock_at=observation.lock_at, first_observed_at=scan.completed_at, last_observed_at=scan.completed_at, content_hash=fingerprint, raw_metadata=observation.metadata)
            session.add(assignment)
            session.flush()
            new_assignments.append(assignment)
            summary.assignments_created += 1
            summary.events.append("assignment.created")
            emit_event(session, "assignment.created", entity_type="assignment", entity_id=str(assignment.id), payload={"title": assignment.title, "due_at": assignment.due_at.isoformat(), "canvas_url": url}, correlation_id=scan.scan_id)
        else:
            old_due = assignment.due_at
            changed = assignment.content_hash != fingerprint
            assignment.title = observation.normalized_title
            assignment.description = observation.description
            assignment.due_at = observation.due_at
            assignment.points_possible = observation.points_possible
            assignment.available_from = observation.available_from
            assignment.lock_at = observation.lock_at
            assignment.last_observed_at = scan.completed_at
            assignment.raw_metadata = observation.metadata
            assignment.content_hash = fingerprint
            if old_due != assignment.due_at:
                summary.due_dates_changed += 1
                summary.events.append("assignment.due_date_changed")
                emit_event(session, "assignment.due_date_changed", entity_type="assignment", entity_id=str(assignment.id), payload={"from": old_due.isoformat(), "to": assignment.due_at.isoformat()}, correlation_id=scan.scan_id)
            elif changed:
                summary.events.append("assignment.updated")
                emit_event(session, "assignment.updated", entity_type="assignment", entity_id=str(assignment.id), correlation_id=scan.scan_id)
            if changed:
                summary.assignments_updated += 1

    for observation in scan.exams:
        url = normalize_canvas_url(observation.canvas_url)
        if session.exec(select(Exam).where(Exam.source_url == url)).first():
            continue
        course = course_map.get(normalize_canvas_url(observation.course_canvas_url))
        if course:
            exam = Exam(course_id=course.id, title=observation.title, start_at=observation.start_at, end_at=observation.end_at, location=observation.location, coverage=observation.coverage, source_url=url, confidence=.9)
            session.add(exam)
            session.flush()
            summary.exams_created += 1
            emit_event(session, "exam.discovered", entity_type="exam", entity_id=str(exam.id), payload={"title": exam.title, "start_at": exam.start_at.isoformat()}, correlation_id=scan.scan_id)

    for observation in scan.announcements:
        url = normalize_canvas_url(observation.canvas_url)
        if session.exec(select(Announcement).where(Announcement.canonical_url == url)).first():
            continue
        course = course_map.get(normalize_canvas_url(observation.course_canvas_url))
        if course:
            announcement = Announcement(course_id=course.id, title=observation.title, body=observation.body, posted_at=observation.posted_at, canonical_url=url, first_observed_at=scan.completed_at, relevant_dates=observation.relevant_dates)
            session.add(announcement)
            session.flush()
            summary.announcements_created += 1
            emit_event(session, "announcement.created", entity_type="announcement", entity_id=str(announcement.id), payload={"title": announcement.title}, correlation_id=scan.scan_id)

    for assignment in new_assignments:
        prepare_new_assignment(session, assignment, scan.scan_id)

    state = session.exec(select(CanvasWorkerState)).first() or CanvasWorkerState()
    state.status = "CONNECTED"
    state.session_status = "AUTHENTICATED"
    state.last_scan_at = scan.completed_at
    state.last_success_at = scan.completed_at
    state.next_scan_at = scan.completed_at + timedelta(hours=settings.canvas_scan_interval_hours)
    state.last_result = f"{summary.total_changes} changes"
    state.courses_observed = len(scan.courses)
    state.last_error = None
    state.scan_in_progress = False
    session.add(state)
    session.add(SyncRun(provider="canvas_browser", status="SUCCESS", changes=summary.total_changes, finished_at=scan.completed_at))
    emit_event(session, "canvas.scan.completed", payload={"changes": summary.total_changes, "warnings": scan.warnings}, correlation_id=scan.scan_id)
    session.commit()
    return summary
