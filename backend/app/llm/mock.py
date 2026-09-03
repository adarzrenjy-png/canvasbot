from .schemas import AssignmentAnalysisOutput, CalibrationOutput, DiagnosticQuestionOutput


class DemoBrainProvider:
    """Deterministic semantic substitute used by tests and credential-free demo mode."""

    name = "demo-brain"
    model = "deterministic-v1"

    def analyze_assignment(self, title: str, description: str, assignment_type: str) -> AssignmentAnalysisOutput:
        text = f"{title} {description}".lower()
        if "laplace" in text or "differential" in text:
            topics = ["laplace transforms", "initial value problems"]
            difficulty, minutes = .68, 120
        elif "truss" in text:
            topics = ["method of joints", "method of sections", "equilibrium"]
            difficulty, minutes = .72, 150
        elif "friction" in text:
            topics = ["static friction", "kinetic friction", "free-body diagrams"]
            difficulty, minutes = .55, 60
        else:
            topics = [assignment_type.lower(), "course fundamentals"]
            difficulty, minutes = .5, 90
        return AssignmentAnalysisOutput(
            summary=f"Complete {title} with attention to {', '.join(topics[:2])}.",
            topics=topics,
            estimated_difficulty=difficulty,
            base_time_minutes=minutes,
            prerequisites=topics[-1:],
            assignment_type=assignment_type,
            reasoning_summary="Demo analysis uses transparent keyword rules; configure a Brain provider for semantic analysis.",
        )

    def generate_calibration(self, title: str, topics: list[str]) -> CalibrationOutput:
        primary = topics[0]
        secondary = topics[1] if len(topics) > 1 else topics[0]
        return CalibrationOutput(questions=[
            DiagnosticQuestionOutput(dimension="CONCEPTUAL_UNDERSTANDING", prompt=f"Explain the central idea behind {primary} and when it applies.", topics=[primary]),
            DiagnosticQuestionOutput(dimension="EXECUTION_CALCULATION", prompt=f"Work through a representative {primary} step and justify each operation.", topics=[primary]),
            DiagnosticQuestionOutput(dimension="TRANSFER_APPLICATION", prompt=f"How would you decide between {primary} and {secondary} in an unfamiliar problem?", topics=[primary, secondary]),
        ])

    def grade_calibration(self, answers: list[str]) -> list[float]:
        """Transparent offline demo scoring; live mode delegates rubric grading to the selected Brain."""
        scores = []
        for answer in answers:
            word_count = len(answer.split())
            scores.append(.9 if word_count >= 35 else .67 if word_count >= 15 else .35)
        return scores
