from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _canonical_datetime(value):
    if value is None or isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed is not None and parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


class CanvasCourseObservation(BaseModel):
    canvas_url: str
    visible_name: str
    normalized_title: str
    course_code: Optional[str] = None
    term: Optional[str] = None
    instructor: Optional[str] = None
    section: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanvasAssignmentObservation(BaseModel):
    canvas_url: str
    course_canvas_url: str
    visible_title: str
    normalized_title: str
    due_at: datetime
    description: str = ""
    assignment_type: str = "Assignment"
    points_possible: Optional[float] = None
    available_from: Optional[datetime] = None
    lock_at: Optional[datetime] = None
    visible_date: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _normalize_due = field_validator("due_at", "available_from", "lock_at", mode="before")(_canonical_datetime)


class CanvasExamObservation(BaseModel):
    canvas_url: str
    course_canvas_url: str
    title: str
    start_at: datetime
    end_at: Optional[datetime] = None
    location: Optional[str] = None
    coverage: Optional[str] = None

    _normalize_dates = field_validator("start_at", "end_at", mode="before")(_canonical_datetime)


class CanvasAnnouncementObservation(BaseModel):
    canvas_url: str
    course_canvas_url: str
    title: str
    body: str = ""
    posted_at: Optional[datetime] = None
    relevant_dates: list[str] = Field(default_factory=list)

    _normalize_posted = field_validator("posted_at", mode="before")(_canonical_datetime)


class CanvasScanResult(BaseModel):
    scan_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime
    completed_at: datetime
    status: str = "success"
    courses: list[CanvasCourseObservation] = Field(default_factory=list)
    assignments: list[CanvasAssignmentObservation] = Field(default_factory=list)
    exams: list[CanvasExamObservation] = Field(default_factory=list)
    announcements: list[CanvasAnnouncementObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    _normalize_dates = field_validator("started_at", "completed_at", mode="before")(_canonical_datetime)

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str):
        if value not in {"success", "partial", "failed", "auth_required"}:
            raise ValueError("unsupported Canvas scan status")
        return value
