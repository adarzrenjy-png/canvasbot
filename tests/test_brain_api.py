"""Brain provider selection and credential delivery through the HTTP API."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import credentials


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A backend bound to a throwaway database with a known runtime token."""
    database = tmp_path / "planner.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("RUNTIME_TOKEN", "test-token")
    monkeypatch.setenv("DEMO_MODE", "false")

    # Settings and the engine are module-level, so reimport them under the patched env.
    for module in ["backend.app.main", "backend.app.database", "backend.app.config", "backend.app.api"]:
        monkeypatch.delitem(__import__("sys").modules, module, raising=False)

    from backend.app.main import app

    credentials.clear()
    with TestClient(app) as test_client:
        test_client.database_path = database  # type: ignore[attr-defined]
        yield test_client
    credentials.clear()


def test_brain_is_inactive_until_a_provider_is_selected(client):
    body = client.get("/api/v1/providers/brain").json()
    assert body["live"] is False
    assert body["provider"] is None


def test_selecting_a_provider_leaves_it_inactive_without_a_key(client):
    assert client.put("/api/v1/providers/zai", json={"model": "glm-5.3-flash"}).status_code == 200
    body = client.get("/api/v1/providers/brain").json()
    assert body["provider"] == "zai"
    assert body["live"] is False
    assert "API key" in body["reason"]


def test_pushing_a_key_activates_the_brain(client):
    client.put("/api/v1/providers/zai", json={"model": "glm-5.3-flash"})
    response = client.put(
        "/api/v1/providers/zai/credential",
        json={"api_key": "sk-zai-123"},
        headers={"X-Cadence-Runtime-Token": "test-token"},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/providers/brain").json()["live"] is True


def test_credential_push_requires_the_runtime_token(client):
    response = client.put(
        "/api/v1/providers/zai/credential",
        json={"api_key": "sk-should-not-store"},
        headers={"X-Cadence-Runtime-Token": "wrong"},
    )
    assert response.status_code == 403
    assert not credentials.has_key("zai")


def test_unsupported_provider_is_rejected(client):
    assert client.put("/api/v1/providers/gemini", json={"model": "x"}).status_code == 422


def test_custom_provider_requires_a_base_url(client):
    assert client.put("/api/v1/providers/custom", json={"model": "x"}).status_code == 422
    ok = client.put("/api/v1/providers/custom", json={"model": "x", "base_url": "http://localhost:11434/v1"})
    assert ok.status_code == 200
    stored = [item for item in client.get("/api/v1/providers").json() if item["provider"] == "custom"]
    assert stored and stored[0]["base_url"] == "http://localhost:11434/v1"


def test_api_keys_never_reach_sqlite(client):
    client.put("/api/v1/providers/openai", json={"model": "gpt-test"})
    client.put(
        "/api/v1/providers/openai/credential",
        json={"api_key": "sk-secret-value"},
        headers={"X-Cadence-Runtime-Token": "test-token"},
    )

    connection = sqlite3.connect(client.database_path)  # type: ignore[attr-defined]
    tables = [name for (name,) in connection.execute("select name from sqlite_master where type='table'")]
    for table in tables:
        for row in connection.execute(f"select * from {table}"):  # noqa: S608 - table names come from sqlite_master
            assert not any("sk-secret-value" in str(value) for value in row), f"key leaked into {table}"
