from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    # SQLite does not preserve timezone offsets; persist UTC as a naive value.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AssignmentState(str, Enum):
    DETECTED = "DETECTED"
    ANALYZED = "ANALYZED"
    AWAITING_CALIBRATION = "AWAITING_CALIBRATION"
    CALIBRATION_IN_PROGRESS = "CALIBRATION_IN_PROGRESS"
    CALIBRATED = "CALIBRATED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    STALE = "STALE"
    ERROR = "ERROR"


class BlockKind(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    PROTECTED = "PROTECTED"
    FLOATING = "FLOATING"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Timestamped(SQLModel):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UserPreferences(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    day_start_hour: int = 8
    day_end_hour: int = 22
    preferred_start_hour: int = 16
    min_block_minutes: int = 30
    max_block_minutes: int = 90
    safety_buffer_hours: int = 12


class Course(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    code: str = Field(index=True, unique=True)
    color: str = "#526D5B"
    external_id: Optional[str] = Field(default=None, index=True)
    term: Optional[str] = None
    institution: str = "Rutgers University"
    department: Optional[str] = None
    section: Optional[str] = None
    instructor: Optional[str] = None
    canvas_url: Optional[str] = Field(default=None, index=True)
    status: str = "ACTIVE"
    first_observed_at: Optional[datetime] = None
    last_observed_at: Optional[datetime] = None
    archived: bool = False
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Assignment(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    title: str
    description: str = ""
    due_at: datetime = Field(index=True)
    state: AssignmentState = Field(default=AssignmentState.DETECTED, index=True)
    priority: int = 3
    base_minutes: int = 90
    estimated_minutes: int = 90
    scheduled_minutes: int = 0
    proficiency: Optional[str] = None
    risk: RiskLevel = RiskLevel.LOW
    assignment_type: str = "Homework"
    submitted: bool = False
    external_id: Optional[str] = Field(default=None, index=True)
    source_lms: str = "local"
    canonical_url: Optional[str] = Field(default=None, index=True)
    points_possible: Optional[float] = None
    available_from: Optional[datetime] = None
    lock_at: Optional[datetime] = None
    first_observed_at: Optional[datetime] = None
    last_observed_at: Optional[datetime] = None
    content_hash: Optional[str] = Field(default=None, index=True)
    raw_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    extracted_topics: list = Field(default_factory=list, sa_column=Column(JSON))
    inferred_difficulty: Optional[float] = None
    actual_minutes: Optional[int] = None
    duration_override_minutes: Optional[int] = None
    completion_override: Optional[bool] = None


class AssignmentSnapshot(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id", index=True)
    content_hash: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))


class AssignmentAnalysis(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id", index=True)
    summary: str = ""
    topics: list = Field(default_factory=list, sa_column=Column(JSON))
    estimated_difficulty: float = 0.5
    base_time_minutes: int = 60
    prerequisites: list = Field(default_factory=list, sa_column=Column(JSON))
    assignment_type: str = ""
    reasoning_summary: str = ""


class Calibration(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id", index=True)
    status: str = "PENDING"
    overall_score: Optional[float] = None
    mastery_classification: Optional[str] = None


class CalibrationQuestion(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    calibration_id: int = Field(foreign_key="calibration.id", index=True)
    position: int
    dimension: str
    prompt: str
    expected_topics: list = Field(default_factory=list, sa_column=Column(JSON))


class CalibrationAnswer(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="calibrationquestion.id", index=True)
    answer: str = ""
    score: Optional[float] = None
    error_type: Optional[str] = None
    feedback_summary: str = ""


class CalendarEvent(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)
    kind: BlockKind = Field(default=BlockKind.HARD, index=True)
    color: str = "#8A6B4C"
    locked: bool = True
    source: str = "local"


class StudyBlock(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id", index=True)
    title: str
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)
    kind: BlockKind = BlockKind.FLOATING
    locked: bool = False
    completed: bool = False
    schedule_run_id: Optional[int] = Field(default=None, foreign_key="schedulerun.id")


class ScheduleRun(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reason: str = "manual"
    status: str = "COMPLETED"
    blocks_created: int = 0
    unscheduled_minutes: int = 0


class ScheduleDecision(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    schedule_run_id: int = Field(foreign_key="schedulerun.id")
    assignment_id: int = Field(foreign_key="assignment.id")
    decision: str
    score: float = 0.0
    explanation: str = ""


class Topic(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id")
    topic_key: str = Field(index=True, unique=True)
    name: str
    parent_key: Optional[str] = None


class MasteryRecord(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    mastery_score: float = 0.5
    confidence: float = 0.2
    evidence_count: int = 0
    last_tested: Optional[datetime] = None
    recent_error_types: list = Field(default_factory=list, sa_column=Column(JSON))


class SyncRun(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = "demo"
    status: str = "SUCCESS"
    changes: int = 0
    finished_at: Optional[datetime] = None


class HistoricalWorkRecord(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="assignment.id")
    estimated_minutes: int
    actual_minutes: int


class ProviderConfiguration(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(index=True)
    model: str
    base_url: Optional[str] = None
    temperature: float = 0.2
    credential_key: Optional[str] = None


class ModelRoute(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task: str = Field(index=True, unique=True)
    provider_configuration_id: int = Field(foreign_key="providerconfiguration.id")


class Notification(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    body: str
    severity: str = "INFO"
    read: bool = False


class Exam(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    title: str
    start_at: datetime = Field(index=True)
    end_at: Optional[datetime] = None
    exam_type: str = "EXAM"
    location: Optional[str] = None
    coverage: Optional[str] = None
    source_url: Optional[str] = Field(default=None, index=True)
    confidence: float = 0.5
    preparation_start_at: Optional[datetime] = None
    format_notes: Optional[str] = None
    source_classification: str = "CANVAS_CURRENT"


class Announcement(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    title: str
    body: str = ""
    posted_at: Optional[datetime] = None
    canonical_url: str = Field(index=True)
    first_observed_at: datetime = Field(default_factory=utcnow)
    relevant_dates: list = Field(default_factory=list, sa_column=Column(JSON))
    affects_planning: Optional[bool] = None


class AcademicDocument(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    document_type: str = "SYLLABUS"
    title: str
    source_url: Optional[str] = None
    local_path: Optional[str] = None
    extracted_text: str = ""
    content_hash: str = Field(index=True)
    metadata_json: dict = Field(default_factory=dict, sa_column=Column(JSON))


class DomainEvent(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    entity_type: Optional[str] = Field(default=None, index=True)
    entity_id: Optional[str] = Field(default=None, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    correlation_id: Optional[str] = Field(default=None, index=True)


class BackgroundJob(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_key: str = Field(index=True, unique=True)
    job_type: str = Field(index=True)
    status: str = Field(default="PENDING", index=True)
    scheduled_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))


class CanvasWorkerState(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = "DISCONNECTED"
    session_status: str = "NOT_CONFIGURED"
    last_scan_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    next_scan_at: Optional[datetime] = None
    last_result: Optional[str] = None
    courses_observed: int = 0
    last_error: Optional[str] = None
    scan_in_progress: bool = False


class ModelUsageRecord(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    provider: str = Field(index=True)
    model: str = Field(index=True)
    task: str = Field(index=True)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    approximate_cost_usd: float = 0
    latency_ms: int = 0


class StudySession(Timestamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    study_block_id: int = Field(foreign_key="studyblock.id", index=True)
    started_at: datetime = Field(default_factory=utcnow)
    paused_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    active_seconds: int = 0
    completion_fraction: Optional[float] = None
