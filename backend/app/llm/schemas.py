from pydantic import BaseModel, Field


class AssignmentAnalysisOutput(BaseModel):
    summary: str
    topics: list[str] = Field(min_length=1)
    estimated_difficulty: float = Field(ge=0, le=1)
    base_time_minutes: int = Field(ge=15, le=1440)
    prerequisites: list[str] = Field(default_factory=list)
    assignment_type: str
    reasoning_summary: str


class DiagnosticQuestionOutput(BaseModel):
    dimension: str
    prompt: str
    topics: list[str]


class CalibrationOutput(BaseModel):
    questions: list[DiagnosticQuestionOutput] = Field(min_length=3, max_length=3)
