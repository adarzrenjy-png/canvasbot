from dataclasses import dataclass
from datetime import datetime
from math import exp


@dataclass(frozen=True)
class MasteryUpdate:
    score: float
    confidence: float
    evidence_count: int


def update_mastery(
    previous_score: float,
    previous_confidence: float,
    evidence_count: int,
    question_score: float,
    difficulty: float,
    days_since_tested: float = 0,
) -> MasteryUpdate:
    """Conservative weighted update; no single answer can move mastery by over 0.2."""
    prior = min(max(previous_score, 0), 1)
    result = min(max(question_score, 0), 1)
    difficulty = min(max(difficulty, 0), 1)
    recency = exp(-max(days_since_tested, 0) / 180)
    evidence_weight = min(0.2, 1 / (evidence_count + 4))
    difficulty_weight = 0.75 + difficulty * 0.5
    delta = (result - prior) * evidence_weight * difficulty_weight * (0.85 + 0.15 * recency)
    new_score = min(max(prior + delta, 0), 1)
    confidence_gain = (1 - previous_confidence) * min(0.12, 1 / (evidence_count + 8))
    return MasteryUpdate(round(new_score, 4), round(min(previous_confidence + confidence_gain, 1), 4), evidence_count + 1)
