"""The engineering report: complete, honest about what it did not check, and data-driven."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import pytest

from jig.cad.builder import Builder
from jig.cad.program import parse_program
from jig.cad.samples import L_BRACKET
from jig.fea.ccx import find_ccx
from jig.fea.service import analyze_build
from jig.report.document import build_report, direction_words

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def test_direction_words_read_naturally() -> None:
    assert direction_words([0, 0, -60]) == "60.0 N straight down (−Z)"
    assert direction_words([25, 0, 0]) == "25.0 N toward +X (+X)"
    assert "along" in direction_words([1, 1, 0])


def test_report_without_fea_says_so_and_still_documents_the_part(builder: Builder) -> None:
    result = builder.build(L_BRACKET)
    html = build_report(
        L_BRACKET, parse_program(L_BRACKET), {"id": result.build_id, **result.data}, None, now=NOW
    )
    assert "NOT ANALYSED" in html
    assert "Design parameters" in html and "THICKNESS" in html
    assert "Not checked" in html and "Fatigue" in html
    assert "Appendix A" in html and "def inside_fillet" in html
    assert "<svg" in html  # the part picture
    assert "nan" not in html.lower().replace("nanoseconds", "")


@pytest.mark.skipif(shutil.which("ccx") is None, reason="needs CalculiX")
def test_report_with_fea_carries_the_verdict_and_its_evidence(builder: Builder) -> None:
    pytest.importorskip("gmsh")
    result = builder.build(L_BRACKET)
    program = parse_program(L_BRACKET)
    fea = analyze_build(result, program, find_ccx())
    html = build_report(L_BRACKET, program, {"id": result.build_id, **result.data}, fea, now=NOW)
    assert fea["status"] == "fail"
    assert ">FAIL<" in html
    assert "The test: what the part has to survive" in html
    assert "Wall bolts" in html and "60.0 N straight down" in html
    assert "converged" in html and "balance the applied loads" in html
    assert f"{fea['safety_factor']:.2f}" in html
    assert len(html) < 1_500_000  # pictures stay light enough to email
