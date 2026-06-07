"""Tests for the /wake-time endpoint and its helpers."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

import main
from tests.conftest import API_KEY


def _timed_event(summary="Dormir", end_iso="2026-06-08T07:30:00+01:00"):
    return {"items": [{"summary": summary, "end": {"dateTime": end_iso}}]}


def test_requires_api_key(client):
    resp = client.get("/wake-time")
    assert resp.status_code == 401


def test_rejects_wrong_api_key(client):
    resp = client.get("/wake-time", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_success_timed_event(client, fake_calendar):
    fake_calendar(_timed_event())
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["wake_time"] == "07:30"
    assert body["hour"] == 7
    assert body["minute"] == 30
    assert body["iso"].startswith("2026-06-08T07:30:00")


def test_success_all_day_event(client, fake_calendar):
    fake_calendar({"items": [{"summary": "Dormir", "end": {"date": "2026-06-08"}}]})
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["wake_time"] == "00:00"
    assert body["hour"] == 0
    assert body["minute"] == 0


def test_no_event_found(client, fake_calendar):
    fake_calendar({"items": []})
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 404


def test_ignores_non_matching_events(client, fake_calendar):
    fake_calendar(
        {
            "items": [
                {"summary": "Gym", "end": {"dateTime": "2026-06-08T07:30:00+01:00"}},
                {"summary": None, "end": {"dateTime": "2026-06-08T08:00:00+01:00"}},
            ]
        }
    )
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 404


def test_keyword_match_is_case_insensitive(client, fake_calendar):
    fake_calendar(_timed_event(summary="DORMIR profundo"))
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200


def test_upstream_http_error(client, fake_calendar):
    resp_obj = SimpleNamespace(status=500, reason="Internal Error")
    fake_calendar(HttpError(resp_obj, b"boom"))
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 502
    assert "Upstream" in resp.json()["detail"]


def test_auth_error(client, fake_calendar):
    fake_calendar(GoogleAuthError("token revoked"))
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 502
    assert "authentication" in resp.json()["detail"].lower()


def test_unexpected_error(client, fake_calendar):
    fake_calendar(RuntimeError("network down"))
    resp = client.get("/wake-time", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 502
    assert "reach" in resp.json()["detail"].lower()


def test_parse_event_end_missing():
    with pytest.raises(HTTPException) as exc:
        main.parse_event_end({}, main.CONFIG["tz"])
    assert exc.value.status_code == 502


def test_parse_event_end_unparseable():
    event = {"end": {"dateTime": "definitely-not-a-date"}}
    with pytest.raises(HTTPException) as exc:
        main.parse_event_end(event, main.CONFIG["tz"])
    assert exc.value.status_code == 502


def test_get_credentials_is_cached():
    first = main._get_credentials()
    second = main._get_credentials()
    assert first is second


def test_get_credentials_refreshes_when_invalid(monkeypatch):
    refreshed = {}

    class _FakeCreds:
        valid = False

        def refresh(self, _request):
            refreshed["called"] = True

    monkeypatch.setattr(main, "Credentials", lambda **_kwargs: _FakeCreds())
    monkeypatch.setattr(main, "Request", lambda: object())
    main._get_credentials()
    assert refreshed.get("called") is True


def test_get_calendar_service_builds(monkeypatch):
    monkeypatch.setattr(main, "_get_credentials", lambda: object())
    monkeypatch.setattr(main, "build", lambda *_a, **_k: "calendar-service")
    assert main.get_calendar_service() == "calendar-service"
