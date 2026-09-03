from datetime import datetime, time, timedelta

from sqlmodel import Session, select

from .models import (
    Assignment, AssignmentState, BlockKind, CalendarEvent, CanvasWorkerState, Course,
    DomainEvent, MasteryRecord, RiskLevel, SyncRun, Topic, UserPreferences, utcnow,
    ModelRoute, ProviderConfiguration,
)
from .llm.routing import ModelTask


def seed_provider_routes(session: Session) -> None:
    demo = session.exec(select(ProviderConfiguration).where(ProviderConfiguration.provider == "demo-brain")).first()
    if not demo:
        demo = ProviderConfiguration(provider="demo-brain", model="deterministic-v1")
        session.add(demo)
        session.commit()
        session.refresh(demo)
    canvas = session.exec(select(ProviderConfiguration).where(ProviderConfiguration.provider == "zai")).first()
    if not canvas:
        canvas = ProviderConfiguration(provider="zai", model="glm-5.3-flash", base_url="https://api.z.ai/api/paas/v4", credential_key="zai_api_key")
        session.add(canvas)
        session.commit()
        session.refresh(canvas)
    for task in ModelTask:
        if session.exec(select(ModelRoute).where(ModelRoute.task == task.value)).first():
            continue
        target = canvas if task == ModelTask.CANVAS_COMPUTER_USE else demo
        session.add(ModelRoute(task=task.value, provider_configuration_id=target.id))
    session.commit()


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    today = datetime.now().date()
    return datetime.combine(today + timedelta(days=day_offset), time(hour, minute))


def seed_demo(session: Session) -> None:
    seed_provider_routes(session)
    if session.exec(select(Course)).first():
        return

    courses = [
        Course(name="Engineering Mechanics: Statics", code="ME 201", color="#526D5B"),
        Course(name="Differential Equations", code="MATH 241", color="#A86042"),
        Course(name="Intro to Engineering", code="ENGR 101", color="#60718C"),
    ]
    session.add_all(courses)
    session.commit()
    for course in courses:
        session.refresh(course)

    assignments = [
        Assignment(course_id=courses[0].id, title="Truss Analysis Set", description="Method of joints and sections", due_at=_at(2, 23, 59), state=AssignmentState.SCHEDULED, base_minutes=150, estimated_minutes=180, scheduled_minutes=180, proficiency="MEDIUM", risk=RiskLevel.MEDIUM, priority=5),
        Assignment(course_id=courses[1].id, title="Laplace Transform Problems", description="Solve IVPs with Laplace transforms", due_at=_at(4, 17), state=AssignmentState.AWAITING_CALIBRATION, base_minutes=120, estimated_minutes=120, scheduled_minutes=0, risk=RiskLevel.LOW, priority=4),
        Assignment(course_id=courses[2].id, title="Design Memo — Prototype Review", description="Two-page design review memo", due_at=_at(6, 12), state=AssignmentState.SCHEDULED, base_minutes=90, estimated_minutes=90, scheduled_minutes=90, proficiency="HIGH", risk=RiskLevel.LOW, priority=3),
        Assignment(course_id=courses[0].id, title="Friction Quiz", description="Static and kinetic friction", due_at=_at(1, 11), state=AssignmentState.AWAITING_CALIBRATION, base_minutes=60, estimated_minutes=60, scheduled_minutes=0, risk=RiskLevel.HIGH, priority=5),
    ]
    session.add_all(assignments)

    events = []
    for offset in range(0, 5):
        events.append(CalendarEvent(title="Differential Equations", start_at=_at(offset, 9), end_at=_at(offset, 9, 50), kind=BlockKind.HARD, color="#60718C"))
    events.extend([
        CalendarEvent(title="Engineering Mechanics", start_at=_at(0, 11), end_at=_at(0, 12, 15), kind=BlockKind.HARD, color="#526D5B"),
        CalendarEvent(title="Lunch", start_at=_at(0, 12, 30), end_at=_at(0, 13, 15), kind=BlockKind.PROTECTED, color="#B8AB91"),
        CalendarEvent(title="Gym", start_at=_at(0, 18), end_at=_at(0, 19), kind=BlockKind.PROTECTED, color="#B8AB91"),
        CalendarEvent(title="Engineering Lab", start_at=_at(2, 13), end_at=_at(2, 15), kind=BlockKind.HARD, color="#526D5B"),
    ])
    session.add_all(events)

    topics = [
        Topic(course_id=courses[0].id, topic_key="statics.equilibrium", name="Equilibrium"),
        Topic(course_id=courses[0].id, topic_key="statics.trusses.joints", name="Method of Joints", parent_key="statics.trusses"),
        Topic(course_id=courses[0].id, topic_key="statics.trusses.sections", name="Method of Sections", parent_key="statics.trusses"),
        Topic(course_id=courses[1].id, topic_key="diffeq.laplace", name="Laplace Transforms"),
    ]
    session.add_all(topics)
    session.commit()
    for topic in topics:
        session.refresh(topic)
    session.add_all([
        MasteryRecord(topic_id=topics[0].id, mastery_score=.91, confidence=.82, evidence_count=9),
        MasteryRecord(topic_id=topics[1].id, mastery_score=.84, confidence=.74, evidence_count=7),
        MasteryRecord(topic_id=topics[2].id, mastery_score=.57, confidence=.52, evidence_count=4),
        MasteryRecord(topic_id=topics[3].id, mastery_score=.68, confidence=.48, evidence_count=3),
        UserPreferences(),
        SyncRun(provider="demo", status="SUCCESS", changes=4, finished_at=utcnow()),
        CanvasWorkerState(status="DEMO", session_status="NOT_CONFIGURED", last_scan_at=utcnow(), next_scan_at=utcnow() + timedelta(hours=8), last_result="Demo data loaded", courses_observed=3),
        DomainEvent(event_type="canvas.scan.completed", payload={"changes": 4, "mode": "demo"}),
        DomainEvent(event_type="study_plan.updated", payload={"blocks": 3, "reason": "demo startup"}),
    ])
    session.commit()
