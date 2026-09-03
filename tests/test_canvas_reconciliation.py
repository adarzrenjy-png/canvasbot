from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

from backend.app.canvas.reconcile import normalize_canvas_url, reconcile_scan
from backend.app.canvas.schemas import CanvasScanResult
from backend.app.models import Assignment, CalibrationQuestion, DomainEvent, StudyBlock
from backend.app.pipeline import complete_demo_calibration


def scan_payload(title="Homework 4", due="2026-09-09T23:59:00-04:00"):
    return {
        "scan_id": "scan-1",
        "started_at": "2026-09-02T16:00:00-04:00",
        "completed_at": "2026-09-02T16:02:00-04:00",
        "status": "success",
        "courses": [{
            "canvas_url": "https://rutgers.instructure.com/courses/244",
            "visible_name": "MATH 244 Differential Equations",
            "normalized_title": "Differential Equations",
            "course_code": "MATH 244",
            "term": "Fall 2026",
        }],
        "assignments": [{
            "canvas_url": "https://rutgers.instructure.com/courses/244/assignments/44?module_item_id=3",
            "course_canvas_url": "https://rutgers.instructure.com/courses/244",
            "visible_title": title,
            "normalized_title": title,
            "due_at": due,
            "description": "First-order linear ODEs and integrating factors",
            "assignment_type": "Homework",
        }],
    }


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def test_stable_url_removes_query_identity_noise():
    assert normalize_canvas_url("HTTPS://Rutgers.Instructure.com/courses/1/?x=2#top") == "https://rutgers.instructure.com/courses/1"


def test_invalid_assignment_date_is_rejected():
    payload = scan_payload(due="sometime Friday")
    with pytest.raises(ValidationError):
        CanvasScanResult.model_validate(payload)


def test_new_assignment_creates_three_question_calibration(session):
    summary = reconcile_scan(session, CanvasScanResult.model_validate(scan_payload()))
    assignment = session.exec(select(Assignment)).one()
    questions = session.exec(select(CalibrationQuestion)).all()
    assert summary.assignments_created == 1
    assert assignment.state == "AWAITING_CALIBRATION"
    assert assignment.canonical_url.endswith("/assignments/44")
    assert len(questions) == 3
    assert {question.dimension for question in questions} == {"CONCEPTUAL_UNDERSTANDING", "EXECUTION_CALCULATION", "TRANSFER_APPLICATION"}


def test_same_assignment_is_not_duplicated(session):
    scan = CanvasScanResult.model_validate(scan_payload())
    reconcile_scan(session, scan)
    second = reconcile_scan(session, scan.model_copy(update={"scan_id": "scan-2"}))
    assert len(session.exec(select(Assignment)).all()) == 1
    assert second.assignments_created == 0
    assert second.assignments_updated == 0


def test_title_and_due_date_changes_update_existing_assignment(session):
    reconcile_scan(session, CanvasScanResult.model_validate(scan_payload()))
    changed = scan_payload(title="Homework 4 — Revised", due="2026-09-08T20:00:00-04:00")
    changed["scan_id"] = "scan-2"
    summary = reconcile_scan(session, CanvasScanResult.model_validate(changed))
    assignments = session.exec(select(Assignment)).all()
    events = [event.event_type for event in session.exec(select(DomainEvent)).all()]
    assert len(assignments) == 1
    assert assignments[0].title == "Homework 4 — Revised"
    assert summary.due_dates_changed == 1
    assert "assignment.due_date_changed" in events


def test_calibration_updates_estimate_and_creates_study_plan(session):
    reconcile_scan(session, CanvasScanResult.model_validate(scan_payload()))
    assignment = session.exec(select(Assignment)).one()
    original_estimate = assignment.estimated_minutes
    calibration, run = complete_demo_calibration(
        session,
        assignment,
        ["Detailed conceptual explanation"] * 3,
        [.9, .9, .6],
    )
    blocks = session.exec(select(StudyBlock).where(StudyBlock.assignment_id == assignment.id)).all()
    assert calibration.status == "COMPLETED"
    assert assignment.estimated_minutes != original_estimate
    assert assignment.state == "SCHEDULED"
    assert run.blocks_created == len(blocks)
    assert blocks
    assert all(block.end_at <= assignment.due_at for block in blocks)
