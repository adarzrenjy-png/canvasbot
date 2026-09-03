from datetime import datetime, timedelta

from backend.app.scheduler import BusyWindow, TaskInput, schedule_tasks


NOW = datetime(2026, 9, 2, 8, 0)


def test_scheduler_splits_long_work_and_avoids_busy_time():
    busy = [BusyWindow(datetime(2026, 9, 2, 9), datetime(2026, 9, 2, 11))]
    task = TaskInput(1, "Truss set", datetime(2026, 9, 3, 20), 180, 5)
    blocks, remaining = schedule_tasks([task], busy, NOW, max_block=90)
    assert sum(int((b.end - b.start).total_seconds() / 60) for b in blocks) == 180
    assert all(not (b.start < busy[0].end and b.end > busy[0].start) for b in blocks)
    assert max(int((b.end - b.start).total_seconds() / 60) for b in blocks) <= 90
    assert remaining[1] == 0


def test_scheduler_respects_calibration_gate_by_accepting_only_given_tasks():
    calibrated = TaskInput(1, "Ready", NOW + timedelta(days=2), 60)
    blocks, remaining = schedule_tasks([calibrated], [], NOW)
    assert {block.assignment_id for block in blocks} == {1}
    assert 2 not in remaining


def test_scheduler_reports_unplaced_minutes_when_calendar_is_full():
    busy = [BusyWindow(datetime(2026, 9, 2, 8), datetime(2026, 9, 3, 22))]
    task = TaskInput(1, "No room", datetime(2026, 9, 3, 12), 120)
    blocks, remaining = schedule_tasks([task], busy, NOW)
    assert blocks == []
    assert remaining[1] == 120


def test_urgent_task_is_scheduled_before_later_task():
    urgent = TaskInput(1, "Urgent", NOW + timedelta(days=1), 30)
    later = TaskInput(2, "Later", NOW + timedelta(days=4), 30)
    blocks, _ = schedule_tasks([later, urgent], [], NOW)
    assert blocks[0].assignment_id == 1
