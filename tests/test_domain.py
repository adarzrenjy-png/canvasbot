import pytest

from backend.app.estimation import estimate_time
from backend.app.mastery import update_mastery
from backend.app.models import AssignmentState
from backend.app.state_machine import can_transition, transition


def test_valid_assignment_progression():
    assert transition(AssignmentState.DETECTED, AssignmentState.ANALYZED) == AssignmentState.ANALYZED
    assert can_transition(AssignmentState.ANALYZED, AssignmentState.AWAITING_CALIBRATION)


def test_assignment_cannot_skip_calibration():
    with pytest.raises(ValueError):
        transition(AssignmentState.ANALYZED, AssignmentState.SCHEDULED)


def test_mastery_update_is_incremental():
    result = update_mastery(.50, .30, 0, 1.0, .8)
    assert .50 < result.score <= .70
    assert result.confidence > .30
    assert result.evidence_count == 1


def test_mastery_update_uses_prior_evidence_to_reduce_volatility():
    early = update_mastery(.7, .5, 1, 0, .5)
    established = update_mastery(.7, .8, 20, 0, .5)
    assert abs(early.score - .7) > abs(established.score - .7)


def test_low_mastery_adds_concept_review():
    low = estimate_time(120, "LOW", difficulty=.5)
    high = estimate_time(120, "HIGH", difficulty=.5)
    assert low.review_minutes == 30
    assert high.review_minutes == 0
    assert low.total_minutes > high.total_minutes


def test_unknown_mastery_is_rejected():
    with pytest.raises(ValueError):
        estimate_time(60, "GUESS")
