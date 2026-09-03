from datetime import datetime, timedelta, timezone

from sqlmodel import Session, delete, select

from .models import Assignment, AssignmentState, CalendarEvent, Course, RiskLevel, ScheduleDecision, ScheduleRun, StudyBlock, UserPreferences
from .scheduler import BusyWindow, TaskInput, schedule_tasks


def recompute_schedule(session: Session, reason: str = "manual") -> ScheduleRun:
    preferences = session.exec(select(UserPreferences)).first() or UserPreferences()
    if preferences.id is None:
        session.add(preferences)
        session.commit()
    movable = session.exec(select(StudyBlock).where(StudyBlock.locked == False, StudyBlock.completed == False)).all()  # noqa: E712
    for block in movable:
        session.delete(block)

    now = datetime.now()
    events = session.exec(select(CalendarEvent).where(CalendarEvent.end_at > now)).all()
    locked_study = session.exec(select(StudyBlock).where(StudyBlock.locked == True, StudyBlock.end_at > now)).all()  # noqa: E712
    busy = [BusyWindow(event.start_at, event.end_at) for event in events]
    busy += [BusyWindow(block.start_at, block.end_at) for block in locked_study]
    assignments = session.exec(select(Assignment).where(Assignment.submitted == False, Assignment.due_at > now)).all()  # noqa: E712
    eligible = [a for a in assignments if a.state in {AssignmentState.CALIBRATED, AssignmentState.SCHEDULED, AssignmentState.IN_PROGRESS}]
    tasks = [TaskInput(a.id, a.title, a.due_at, max(a.estimated_minutes - sum(int((b.end_at - b.start_at).total_seconds() / 60) for b in locked_study if b.assignment_id == a.id), 0), a.priority) for a in eligible]

    proposed, remaining = schedule_tasks(tasks, busy, now, day_start=preferences.day_start_hour, day_end=preferences.day_end_hour, min_block=preferences.min_block_minutes, max_block=preferences.max_block_minutes, safety_buffer_hours=preferences.safety_buffer_hours)
    run = ScheduleRun(reason=reason, blocks_created=len(proposed), unscheduled_minutes=sum(remaining.values()))
    session.add(run)
    session.commit()
    session.refresh(run)
    course_by_id = {c.id: c for c in session.exec(select(Course)).all()}
    assignment_by_id = {a.id: a for a in assignments}
    for proposal in proposed:
        assignment = assignment_by_id[proposal.assignment_id]
        session.add(StudyBlock(assignment_id=assignment.id, title=assignment.title, start_at=proposal.start, end_at=proposal.end, schedule_run_id=run.id))
        session.add(ScheduleDecision(schedule_run_id=run.id, assignment_id=assignment.id, decision="PLACED", score=proposal.score, explanation=f"Placed before {assignment.due_at:%a %I:%M %p}; conflicts and the safety buffer were respected."))
        assignment.state = AssignmentState.SCHEDULED
        assignment.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    for assignment in assignments:
        placed_minutes = sum(int((b.end - b.start).total_seconds() / 60) for b in proposed if b.assignment_id == assignment.id)
        locked_minutes = sum(int((b.end_at - b.start_at).total_seconds() / 60) for b in locked_study if b.assignment_id == assignment.id)
        assignment.scheduled_minutes = placed_minutes + locked_minutes
        if remaining.get(assignment.id, 0) > 0:
            assignment.risk = RiskLevel.HIGH
    session.commit()
    return run
