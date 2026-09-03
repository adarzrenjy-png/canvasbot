from sqlmodel import Session, select
from uuid import uuid4

from backend.app.canvas.worker import run_pending_job_once
from backend.app.database import engine
from backend.app.models import Assignment, BackgroundJob, Calibration, CalibrationQuestion


def test_demo_worker_runs_the_assignment_pipeline():
    with Session(engine) as session:
        for existing in session.exec(select(BackgroundJob).where(BackgroundJob.status.in_(["PENDING", "RUNNING"]))).all():
            existing.status = "COMPLETED"
            session.add(existing)
        job = BackgroundJob(job_key=f"test:demo-worker:{uuid4()}", job_type="canvas.scan")
        session.add(job)
        session.commit()

        assert run_pending_job_once(session, demo_mode=True) is True
        session.refresh(job)
        assert job.status == "COMPLETED"

        assignment = session.exec(select(Assignment).where(Assignment.canonical_url == "https://rutgers.instructure.com/courses/4242/assignments/9001")).first()
        assert assignment is not None
        calibration = session.exec(select(Calibration).where(Calibration.assignment_id == assignment.id)).first()
        questions = session.exec(select(CalibrationQuestion).where(CalibrationQuestion.calibration_id == calibration.id)).all()
        assert len(questions) == 3
