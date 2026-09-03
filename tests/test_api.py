from fastapi.testclient import TestClient

from backend.app.main import app


def test_demo_dashboard_and_openapi_are_available():
    with TestClient(app) as client:
        status = client.get("/api/v1/status")
        dashboard = client.get("/api/v1/dashboard")
        schema = client.get("/openapi.json")
        assert status.status_code == 200
        assert status.json()["mode"] == "demo"
        assert dashboard.status_code == 200
        assert len(dashboard.json()["assignments"]) >= 3
        assert "/api/v1/schedule/recompute" in schema.json()["paths"]


def test_recompute_returns_explainable_summary():
    with TestClient(app) as client:
        response = client.post("/api/v1/schedule/recompute", json={"reason": "test"})
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"
        assert response.json()["blocks_created"] >= 1


def test_brain_model_selection_persists_without_exposing_secret_reference():
    with TestClient(app) as client:
        response = client.put("/api/v1/providers/openai", json={"model": "gpt-test-model"})
        assert response.status_code == 200
        assert response.json()["model"] == "gpt-test-model"
        assert "credential_key" not in response.json()
        providers = client.get("/api/v1/providers").json()
        assert all("api_key" not in str(item).lower() for item in providers)
