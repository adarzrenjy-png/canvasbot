"""User preferences, onboarding state, and the additive schema shim."""

from __future__ import annotations

import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'planner.db'}")
    monkeypatch.setenv("DEMO_MODE", "false")
    for module in ["backend.app.main", "backend.app.database", "backend.app.config", "backend.app.api"]:
        monkeypatch.delitem(sys.modules, module, raising=False)

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_a_fresh_install_seeds_no_sample_courses(client):
    """Demo mode is off by default, so nobody starts on someone else's coursework."""
    assert client.get("/api/v1/courses").json() == []
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["assignments"] == []
    assert dashboard["events"] == []


def test_preferences_start_unconfigured(client):
    body = client.get("/api/v1/preferences").json()
    assert body["display_name"] == ""
    assert body["onboarding_completed"] is False
    assert body["day_start_hour"] == 8 and body["day_end_hour"] == 22


def test_onboarding_can_save_everything_at_once(client):
    body = client.put(
        "/api/v1/preferences",
        json={
            "display_name": "Advaith",
            "term_label": "Fall 2026",
            "day_start_hour": 11,
            "day_end_hour": 24,
            "max_block_minutes": 120,
            "safety_buffer_hours": 24,
            "onboarding_completed": True,
        },
    ).json()
    assert body["display_name"] == "Advaith"
    assert body["day_end_hour"] == 24
    assert body["onboarding_completed"] is True
    # Survives a re-read, so onboarding is never shown twice.
    assert client.get("/api/v1/preferences").json()["onboarding_completed"] is True


def test_settings_can_patch_a_single_field(client):
    client.put("/api/v1/preferences", json={"display_name": "Advaith", "onboarding_completed": True})
    body = client.put("/api/v1/preferences", json={"max_block_minutes": 60}).json()
    assert body["max_block_minutes"] == 60
    # Untouched fields are preserved rather than reset to defaults.
    assert body["display_name"] == "Advaith"
    assert body["onboarding_completed"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"day_start_hour": 20, "day_end_hour": 8},   # day ends before it starts
        {"min_block_minutes": 120, "max_block_minutes": 45},  # longest shorter than shortest
        {"day_start_hour": 25},                       # outside the clock
        {"safety_buffer_hours": -1},                  # negative buffer
    ],
)
def test_incoherent_preferences_are_rejected(client, payload):
    assert client.put("/api/v1/preferences", json=payload).status_code == 422


def test_schema_shim_adds_columns_to_an_older_database(tmp_path, monkeypatch):
    """An install predating a new field must gain the column, not crash on every read."""
    database = tmp_path / "old.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("DEMO_MODE", "false")
    for module in ["backend.app.main", "backend.app.database", "backend.app.config", "backend.app.api"]:
        monkeypatch.delitem(sys.modules, module, raising=False)

    from backend.app.database import create_db_and_tables, ensure_schema

    create_db_and_tables()

    # Simulate the older schema by dropping and recreating the table without the
    # columns added in this change.
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE userpreferences"))
        connection.execute(text(
            "CREATE TABLE userpreferences ("
            " id INTEGER PRIMARY KEY, created_at DATETIME, updated_at DATETIME,"
            " day_start_hour INTEGER, day_end_hour INTEGER, preferred_start_hour INTEGER,"
            " min_block_minutes INTEGER, max_block_minutes INTEGER, safety_buffer_hours INTEGER)"
        ))
        connection.execute(text("INSERT INTO userpreferences (id, day_start_hour) VALUES (1, 9)"))

    columns = {row[1] for row in sqlite3.connect(database).execute("PRAGMA table_info(userpreferences)")}
    assert "display_name" not in columns

    ensure_schema()

    columns = {row[1] for row in sqlite3.connect(database).execute("PRAGMA table_info(userpreferences)")}
    assert {"display_name", "term_label", "onboarding_completed"} <= columns

    # The existing row survives, with defaults filled in for the new columns.
    row = sqlite3.connect(database).execute(
        "SELECT day_start_hour, display_name, onboarding_completed FROM userpreferences WHERE id = 1"
    ).fetchone()
    assert row[0] == 9
    assert row[1] == ""
    assert not row[2]


def test_schema_shim_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'repeat.db'}")
    for module in ["backend.app.main", "backend.app.database", "backend.app.config"]:
        monkeypatch.delitem(sys.modules, module, raising=False)

    from backend.app.database import create_db_and_tables, ensure_schema

    create_db_and_tables()
    ensure_schema()
    ensure_schema()  # would raise "duplicate column name" if it re-added anything
