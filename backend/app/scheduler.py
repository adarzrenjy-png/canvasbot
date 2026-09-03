from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


@dataclass(frozen=True)
class BusyWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class TaskInput:
    assignment_id: int
    title: str
    due_at: datetime
    minutes: int
    priority: int = 3


@dataclass(frozen=True)
class ProposedBlock:
    assignment_id: int
    title: str
    start: datetime
    end: datetime
    score: float


def overlaps(start: datetime, end: datetime, busy: BusyWindow) -> bool:
    return start < busy.end and end > busy.start


def _candidate_windows(now: datetime, deadline: datetime, day_start: int, day_end: int, step: int = 30):
    cursor = now.replace(minute=(now.minute // step + 1) * step % 60, second=0, microsecond=0)
    if cursor <= now:
        cursor += timedelta(minutes=step)
    while cursor < deadline:
        if day_start <= cursor.hour < day_end:
            yield cursor
        cursor += timedelta(minutes=step)


def schedule_tasks(
    tasks: Iterable[TaskInput],
    busy: Iterable[BusyWindow],
    now: datetime,
    *,
    day_start: int = 8,
    day_end: int = 22,
    min_block: int = 30,
    max_block: int = 90,
    safety_buffer_hours: int = 12,
) -> tuple[list[ProposedBlock], dict[int, int]]:
    """Greedy, deterministic scheduler prioritizing urgency and larger priority values."""
    occupied = list(busy)
    blocks: list[ProposedBlock] = []
    remaining: dict[int, int] = {}
    ordered = sorted(tasks, key=lambda t: (t.due_at, -t.priority, t.assignment_id))

    for task in ordered:
        minutes_left = task.minutes
        deadline = task.due_at - timedelta(hours=safety_buffer_hours)
        if deadline <= now:
            deadline = task.due_at
        for start in _candidate_windows(now, deadline, day_start, day_end):
            if minutes_left <= 0:
                break
            duration = min(max_block, minutes_left)
            if duration < min_block and blocks and blocks[-1].assignment_id == task.assignment_id:
                last = blocks[-1]
                extension = timedelta(minutes=duration)
                if last.end + extension <= deadline and not any(overlaps(last.end, last.end + extension, item) for item in occupied):
                    blocks[-1] = ProposedBlock(last.assignment_id, last.title, last.start, last.end + extension, last.score)
                    occupied.append(BusyWindow(last.end, last.end + extension))
                    minutes_left = 0
                    break
            duration = max(min_block, duration)
            end = start + timedelta(minutes=duration)
            if end > deadline or end.hour > day_end or any(overlaps(start, end, item) for item in occupied):
                continue
            hours_until_due = max((task.due_at - start).total_seconds() / 3600, 1)
            score = round(task.priority * 10 + 100 / hours_until_due, 2)
            block = ProposedBlock(task.assignment_id, task.title, start, end, score)
            blocks.append(block)
            occupied.append(BusyWindow(start, end))
            minutes_left -= duration
        remaining[task.assignment_id] = max(minutes_left, 0)
    return sorted(blocks, key=lambda b: b.start), remaining
