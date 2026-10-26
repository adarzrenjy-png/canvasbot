from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jig.app import create_app
from jig.settings import Settings


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    settings = Settings(data_dir=tmp_path, budget_usd=20, build_timeout_s=90, ccx_path=None)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_health_reports_ai_fea_and_budget(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["ai"]["ready"] is False
    assert "available" in body["fea"] and body["fea"]["install_hint"]
    assert body["session"]["budget_usd"] == 20


def test_sample_build_then_param_edit_then_download(client: TestClient) -> None:
    sample = client.get("/api/samples/l_bracket").json()
    assert sample["build"]["ok"]
    assert len(sample["program"]["features"]) == 5

    edited = client.post(
        "/api/parts/params", json={"code": sample["code"], "updates": {"WIDTH": 50}}
    ).json()
    assert "WIDTH = 50.0" in edited["code"]
    assert edited["build"]["stats"]["bbox"]["size"][1] == pytest.approx(50.0)

    step = client.get(f"/api/builds/{edited['build']['id']}/download/step")
    assert step.status_code == 200
    assert step.content.startswith(b"ISO-10303-21")


def test_out_of_range_param_is_rejected(client: TestClient) -> None:
    code = client.get("/api/samples/l_bracket").json()["code"]
    response = client.post("/api/parts/params", json={"code": code, "updates": {"THICKNESS": 0}})
    assert response.status_code == 422


def test_ping_without_a_key_explains_what_to_do(client: TestClient) -> None:
    response = client.post("/api/ai/ping")
    assert response.status_code == 503
    assert "MODEL_API_KEY" in response.json()["detail"]


def test_download_rejects_path_tricks(client: TestClient) -> None:
    assert client.get("/api/builds/..%2F..%2Fetc/download/step").status_code == 404


def test_program_payload_carries_the_material(client: TestClient) -> None:
    program = client.get("/api/samples/l_bracket").json()["program"]
    assert program["material"]["id"] == "petg"
    assert program["material"]["density_g_cm3"] == pytest.approx(1.27)


def test_report_without_fea_is_served_as_html(client: TestClient) -> None:
    build_id = client.get("/api/samples/l_bracket").json()["build"]["id"]
    response = client.get(f"/api/builds/{build_id}/report")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "NOT ANALYSED" in response.text
    download = client.get(f"/api/builds/{build_id}/report?download=true")
    assert "attachment" in download.headers["content-disposition"]


@pytest.mark.skipif(shutil.which("ccx") is None, reason="needs CalculiX")
def test_analyze_then_report_with_results(client: TestClient) -> None:
    pytest.importorskip("gmsh")
    sample = client.get("/api/samples/l_bracket").json()
    body = client.post(
        "/api/parts/analyze", json={"code": sample["code"], "build_id": sample["build"]["id"]}
    ).json()
    assert body["build"]["id"] == sample["build"]["id"]  # reused, not rebuilt
    assert body["fea"]["status"] == "fail"
    report = client.get(f"/api/builds/{body['build']['id']}/report").text
    assert ">FAIL<" in report and "safety factor" in report.lower()


def test_blocks_can_be_switched_off_and_reordered(client: TestClient) -> None:
    sample = client.get("/api/samples/l_bracket").json()
    off = client.post(
        "/api/parts/features/enabled",
        json={"code": sample["code"], "feature": "inside_fillet", "enabled": False},
    ).json()
    assert "SUPPRESSED = [inside_fillet]" in off["code"]
    assert off["build"]["ok"] and off["build"]["stats"]["faces"] == 12

    order = ["base_flange", "upright_flange", "base_holes", "upright_holes", "inside_fillet"]
    moved = client.post(
        "/api/parts/features/order", json={"code": sample["code"], "order": order}
    ).json()
    assert [f["id"] for f in moved["program"]["features"]] == order
    assert moved["build"]["ok"]

    bad = client.post(
        "/api/parts/features/order", json={"code": sample["code"], "order": order[:2]}
    )
    assert bad.status_code == 422
