from .models import AssignmentState


ALLOWED_TRANSITIONS = {
    AssignmentState.DETECTED: {AssignmentState.ANALYZED, AssignmentState.ERROR},
    AssignmentState.ANALYZED: {AssignmentState.AWAITING_CALIBRATION, AssignmentState.CALIBRATED, AssignmentState.ERROR},
    AssignmentState.AWAITING_CALIBRATION: {AssignmentState.CALIBRATION_IN_PROGRESS, AssignmentState.CALIBRATED},
    AssignmentState.CALIBRATION_IN_PROGRESS: {AssignmentState.CALIBRATED, AssignmentState.ERROR},
    AssignmentState.CALIBRATED: {AssignmentState.SCHEDULED, AssignmentState.STALE},
    AssignmentState.SCHEDULED: {AssignmentState.IN_PROGRESS, AssignmentState.COMPLETED, AssignmentState.STALE},
    AssignmentState.IN_PROGRESS: {AssignmentState.SCHEDULED, AssignmentState.COMPLETED, AssignmentState.STALE},
    AssignmentState.STALE: {AssignmentState.ANALYZED, AssignmentState.CALIBRATED},
    AssignmentState.ERROR: {AssignmentState.DETECTED, AssignmentState.ANALYZED},
    AssignmentState.COMPLETED: set(),
}


def can_transition(current: AssignmentState, target: AssignmentState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition(current: AssignmentState, target: AssignmentState) -> AssignmentState:
    if not can_transition(current, target):
        raise ValueError(f"Invalid assignment transition: {current.value} -> {target.value}")
    return target
