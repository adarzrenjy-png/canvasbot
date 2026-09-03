import logging
from typing import Iterable

from sqlmodel import Session, select

from .estimation import estimate_time
from .events import emit_event
from .llm.factory import get_brain
from .llm.mock import DemoBrainProvider
from .llm.providers import BrainError
from .models import (
    Assignment, AssignmentAnalysis, AssignmentState, Calibration, CalibrationAnswer,
    CalibrationQuestion, ModelUsageRecord,
)
from .services import recompute_schedule
from .state_machine import transition

logger = logging.getLogger(__name__)


def _with_fallback(session: Session, call, *args):
    """Run a Brain call, degrading to the deterministic Brain if the live one fails.

    A provider outage, a bad key, or a malformed reply must never block an
    assignment from being analysed, so the demo Brain answers instead.
    """
    brain = get_brain(session)
    try:
        return getattr(brain, call)(*args), brain
    except BrainError as error:
        logger.warning("Brain call %s failed, using the demo Brain: %s", call, error)
        demo = DemoBrainProvider()
        return getattr(demo, call)(*args), demo


def ensure_calibration(session: Session, assignment: Assignment, correlation_id: str | None = None) -> Calibration:
    existing = session.exec(select(Calibration).where(Calibration.assignment_id == assignment.id).order_by(Calibration.id.desc())).first()
    if existing:
        return existing
    calibration = Calibration(assignment_id=assignment.id, status="PENDING")
    session.add(calibration)
    session.flush()
    topics = assignment.extracted_topics or [assignment.assignment_type.lower(), "course fundamentals"]
    generated, _ = _with_fallback(session, "generate_calibration", assignment.title, topics)
    for position, question in enumerate(generated.questions, start=1):
        session.add(CalibrationQuestion(calibration_id=calibration.id, position=position, dimension=question.dimension, prompt=question.prompt, expected_topics=question.topics))
    emit_event(session, "diagnostic.required", entity_type="assignment", entity_id=str(assignment.id), payload={"question_count": 3}, correlation_id=correlation_id)
    session.commit()
    session.refresh(calibration)
    return calibration


def prepare_new_assignment(session: Session, assignment: Assignment, correlation_id: str) -> Calibration:
    output, brain = _with_fallback(session, "analyze_assignment", assignment.title, assignment.description, assignment.assignment_type)
    assignment.state = transition(assignment.state, AssignmentState.ANALYZED)
    assignment.base_minutes = output.base_time_minutes
    assignment.estimated_minutes = output.base_time_minutes
    assignment.extracted_topics = output.topics
    assignment.inferred_difficulty = output.estimated_difficulty
    session.add(AssignmentAnalysis(
        assignment_id=assignment.id,
        summary=output.summary,
        topics=output.topics,
        estimated_difficulty=output.estimated_difficulty,
        base_time_minutes=output.base_time_minutes,
        prerequisites=output.prerequisites,
        assignment_type=output.assignment_type,
        reasoning_summary=output.reasoning_summary,
    ))
    assignment.state = transition(assignment.state, AssignmentState.AWAITING_CALIBRATION)
    session.add(ModelUsageRecord(provider=brain.name, model=brain.model, task="ASSIGNMENT_ANALYSIS"))
    session.commit()
    return ensure_calibration(session, assignment, correlation_id)


def complete_demo_calibration(session: Session, assignment: Assignment, answers: list[str], scores: Iterable[float]):
    calibration = session.exec(select(Calibration).where(Calibration.assignment_id == assignment.id).order_by(Calibration.id.desc())).first()
    if not calibration:
        raise ValueError("No calibration is available for this assignment")
    questions = session.exec(select(CalibrationQuestion).where(CalibrationQuestion.calibration_id == calibration.id).order_by(CalibrationQuestion.position)).all()
    scores = [min(max(float(score), 0), 1) for score in scores]
    if len(answers) != 3 or len(scores) != 3 or len(questions) != 3:
        raise ValueError("Calibration requires exactly three answers and scores")
    for question, answer, score in zip(questions, answers, scores):
        session.add(CalibrationAnswer(question_id=question.id, answer=answer, score=score, error_type=None if score >= .8 else "INCOMPLETE_KNOWLEDGE", feedback_summary="Demo grading; configure a Brain provider for rubric-based feedback."))
    overall = sum(scores) / 3
    classification = "HIGH" if overall >= .85 else "MEDIUM" if overall >= .55 else "LOW"
    estimate = estimate_time(assignment.base_minutes, classification, assignment.inferred_difficulty or .5)
    calibration.status = "COMPLETED"
    calibration.overall_score = overall
    calibration.mastery_classification = classification
    assignment.proficiency = classification
    assignment.estimated_minutes = estimate.total_minutes
    assignment.state = transition(assignment.state, AssignmentState.CALIBRATION_IN_PROGRESS)
    assignment.state = transition(assignment.state, AssignmentState.CALIBRATED)
    emit_event(session, "diagnostic.completed", entity_type="assignment", entity_id=str(assignment.id), payload={"classification": classification, "estimated_minutes": estimate.total_minutes})
    emit_event(session, "study_plan.recompute_required", entity_type="assignment", entity_id=str(assignment.id), payload={"reason": "calibration_completed"})
    session.commit()
    run = recompute_schedule(session, "calibration completed")
    return calibration, run
