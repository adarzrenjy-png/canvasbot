from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from backend.app import mcp_tools
from backend.app.config import settings
from backend.app.database import engine
from backend.app.models import BackgroundJob, Course


def test_read_only_mcp_tools_return_safe_structured_data():
    courses = mcp_tools.list_courses()
    assignments = mcp_tools.list_assignments(days=180)
    status = mcp_tools.planner_status()

    assert courses
    assert {"id", "code", "name", "status"}.issubset(courses[0])
    assert "canvas" in status
    if assignments:
        assert "description" not in assignments[0]
        assert "raw_metadata" not in assignments[0]


def test_scan_write_requires_explicit_token(monkeypatch):
    monkeypatch.setattr(settings, "mcp_write_token", "local-test-token")
    with pytest.raises(PermissionError):
        mcp_tools.request_canvas_scan("wrong-token")


def test_scan_write_is_deduplicated(monkeypatch):
    monkeypatch.setattr(settings, "mcp_write_token", "local-test-token")
    with Session(engine) as session:
        for job in session.exec(select(BackgroundJob).where(BackgroundJob.status.in_(["PENDING", "RUNNING"]))).all():
            job.status = "COMPLETED"
            session.add(job)
        session.commit()

    first = mcp_tools.request_canvas_scan("local-test-token")
    second = mcp_tools.request_canvas_scan("local-test-token")
    assert first["deduplicated"] is False
    assert second == {"job_id": first["job_id"], "status": "PENDING", "deduplicated": True}
