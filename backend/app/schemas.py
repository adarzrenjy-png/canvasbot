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
