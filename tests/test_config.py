"""Tests for configuration loading and validation."""

import json

import pytest

import main


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "timezone": "Europe/Lisbon"}


def test_load_config_success_with_defaults(monkeypatch):
    monkeypatch.delenv("CALENDAR_ID", raising=False)
    monkeypatch.delenv("EVENT_KEYWORD", raising=False)
    monkeypatch.delenv("SEARCH_WINDOW_HOURS", raising=False)
    cfg = main.load_config()
    assert cfg["calendar_id"] == "primary"
    assert cfg["event_keyword"] == "Dormir"
    assert cfg["window_hours"] == 18
    assert cfg["tz_name"] == "Europe/Lisbon"


def test_load_config_success_with_overrides(monkeypatch):
    monkeypatch.setenv("CALENDAR_ID", "work@calendar")
    monkeypatch.setenv("EVENT_KEYWORD", "Sleep")
    monkeypatch.setenv("SEARCH_WINDOW_HOURS", "6")
    monkeypatch.setenv("TIMEZONE", "America/New_York")
    cfg = main.load_config()
    assert cfg["calendar_id"] == "work@calendar"
    assert cfg["event_keyword"] == "Sleep"
    assert cfg["window_hours"] == 6
    assert cfg["tz_name"] == "America/New_York"


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("ALARM_API_KEY", raising=False)
    with pytest.raises(main.ConfigError, match="ALARM_API_KEY"):
        main.load_config()


def test_invalid_timezone(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Not/ARealZone")
    with pytest.raises(main.ConfigError, match="Invalid TIMEZONE"):
        main.load_config()


def test_malformed_token_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", "{not valid json")
    with pytest.raises(main.ConfigError, match="not valid JSON"):
        main.load_config()


def test_token_missing_keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_JSON", json.dumps({"client_id": "x"}))
    with pytest.raises(main.ConfigError, match="missing keys"):
        main.load_config()


def test_window_not_an_integer(monkeypatch):
    monkeypatch.setenv("SEARCH_WINDOW_HOURS", "soon")
    with pytest.raises(main.ConfigError, match="must be an integer"):
        main.load_config()


def test_window_not_positive(monkeypatch):
    monkeypatch.setenv("SEARCH_WINDOW_HOURS", "0")
    with pytest.raises(main.ConfigError, match="positive integer"):
        main.load_config()
