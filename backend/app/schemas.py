from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import AssignmentState, BlockKind, RiskLevel


class CourseRead(BaseModel):
    id: int
    name: str
    code: str
    color: str
    model_config = ConfigDict(from_attributes=True)


class AssignmentRead(BaseModel):
    id: int
    title: str
    description: str
    due_at: datetime
    state: AssignmentState
    base_minutes: int
    estimated_minutes: int
    scheduled_minutes: int
    proficiency: Optional[str]
    risk: RiskLevel
    assignment_type: str
    course: CourseRead


class CalendarItemRead(BaseModel):
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    kind: BlockKind
    color: str
    locked: bool
    assignment_id: Optional[int] = None


class ScheduleRequest(BaseModel):
    reason: str = "manual"


class BlockPatch(BaseModel):
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    locked: Optional[bool] = None
    completed: Optional[bool] = None


class CalibrationSubmission(BaseModel):
    answers: list[str]
    demo_scores: Optional[list[float]] = None


class CanvasScanRequest(BaseModel):
    integrity_scan: bool = False


class ProviderSelection(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    # Required for the "custom" provider, optional elsewhere to override the default host.
    base_url: Optional[str] = Field(default=None, max_length=500)


class PreferencesRead(BaseModel):
    display_name: str
    term_label: str
    day_start_hour: int
    day_end_hour: int
    min_block_minutes: int
    max_block_minutes: int
    safety_buffer_hours: int
    onboarding_completed: bool


class PreferencesUpdate(BaseModel):
    """Every field optional so the onboarding flow and Settings can both patch."""

    display_name: Optional[str] = Field(default=None, max_length=80)
    term_label: Optional[str] = Field(default=None, max_length=80)
    day_start_hour: Optional[int] = Field(default=None, ge=0, le=23)
    day_end_hour: Optional[int] = Field(default=None, ge=1, le=24)
    min_block_minutes: Optional[int] = Field(default=None, ge=10, le=240)
    max_block_minutes: Optional[int] = Field(default=None, ge=15, le=480)
    safety_buffer_hours: Optional[int] = Field(default=None, ge=0, le=168)
    onboarding_completed: Optional[bool] = None


class ProviderCredential(BaseModel):
    """An API key pushed in from the desktop vault. Held in memory, never stored."""

    api_key: str = Field(min_length=1, max_length=500)
