"""Shared pytest fixtures and test configuration.

Environment variables must be set *before* ``main`` is imported, because
``main`` validates its configuration at import time.
"""

import json
import os

os.environ.setdefault("ALARM_API_KEY", "test-secret-key")
os.environ.setdefault(
    "GOOGLE_TOKEN_JSON",
    json.dumps(
        {
            "token": "fake-access-token",
            "refresh_token": "fake-refresh-token",
            "client_id": "fake-client-id",
            "client_secret": "fake-client-secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    ),
)
os.environ.setdefault("TIMEZONE", "Europe/Lisbon")

import pytest
from fastapi.testclient import TestClient

from sleep_alarm_service import main

API_KEY = os.environ["ALARM_API_KEY"]


@pytest.fixture(autouse=True)
def _clear_creds_cache():
    """Reset the module credential cache around every test."""
    main._creds_cache.clear()
    yield
    main._creds_cache.clear()


@pytest.fixture
def client():
    """A FastAPI test client bound to the app."""
    return TestClient(main.app)


class _FakeEventsRequest:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeEvents:
    def __init__(self, result):
        self._result = result

    def list(self, **_kwargs):
        return _FakeEventsRequest(self._result)


class _FakeService:
    def __init__(self, result):
        self._result = result

    def events(self):
        return _FakeEvents(self._result)


@pytest.fixture
def fake_calendar(monkeypatch):
    """Install a fake calendar service.

    Pass a dict to be returned by ``execute()``, or an Exception to be raised.
    """

    def _install(result):
        monkeypatch.setattr(main, "get_calendar_service", lambda: _FakeService(result))

    return _install
