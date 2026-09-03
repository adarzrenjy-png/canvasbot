from dataclasses import dataclass


@dataclass(frozen=True)
class TimeEstimate:
    assignment_minutes: int
    review_minutes: int
    total_minutes: int


MASTERY_MULTIPLIER = {"HIGH": 0.75, "MEDIUM": 1.05, "LOW": 1.5}


def estimate_time(base_minutes: int, mastery: str, difficulty: float = 0.5, personal_speed: float = 1.0, buffer_ratio: float = 0.1) -> TimeEstimate:
    if mastery not in MASTERY_MULTIPLIER:
        raise ValueError(f"Unknown mastery classification: {mastery}")
    difficulty_multiplier = 0.85 + min(max(difficulty, 0), 1) * 0.5
    raw = base_minutes * MASTERY_MULTIPLIER[mastery] * difficulty_multiplier * max(personal_speed, 0.25)
    assignment = int(round(raw / 5) * 5)
    review = 30 if mastery == "LOW" else 0
    buffer = int(round((assignment * max(buffer_ratio, 0)) / 5) * 5)
    return TimeEstimate(assignment, review, assignment + review + buffer)
