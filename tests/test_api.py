import sqlite3

from fastapi.testclient import TestClient

import app.web as web
from app.web import api, connection_dependency, settings


def _client() -> TestClient:
    return TestClient(api)


def _auth_headers(value: str | None = None) -> dict[str, str]:
    key = value if value is not None else settings.api_key
    return {"X-API-Key": key or ""}


def test_trades_endpoint_empty(monkeypatch):
    monkeypatch.setattr("app.web.get_trades", lambda limit, conn=None: [])
    client = _client()
    resp = client.get("/trades", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json() == []


def test_protected_endpoints_require_api_key_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    client = _client()

    resp_missing = client.get("/pnl")
    assert resp_missing.status_code == 401

    resp_invalid = client.get("/pnl", headers=_auth_headers("wrong-key"))
    assert resp_invalid.status_code == 401

    resp_valid = client.get("/pnl", headers=_auth_headers("secret-key"))
    assert resp_valid.status_code == 200


def test_pnl_totals_are_returned(monkeypatch):
    monkeypatch.setattr(
        "app.web.get_pnl_totals",
        lambda conn=None: {"net": 5.0, "positive": 8.0, "negative": 3.0},
    )

    client = _client()

    resp = client.get("/pnl", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json() == {"net": 5.0, "positive": 8.0, "negative": 3.0}


def test_requests_fail_when_api_key_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    client = _client()

    resp = client.get("/pnl", headers=_auth_headers("any"))
    assert resp.status_code == 503
    assert resp.json()["detail"] == "API_KEY is not configured"


def test_healthz_returns_200_for_liveness(monkeypatch):
    monkeypatch.setattr(settings, "use_live_feed", False)
    monkeypatch.setattr(settings, "use_ice_live", False)
    monkeypatch.setattr(settings, "use_powerledger_live", False)
    client = _client()

    resp = client.get("/healthz", params={"probe": "liveness"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["probe"] == "liveness"
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"


def test_healthz_flags_database_failure(monkeypatch):
    class BrokenConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("boom")

    api.dependency_overrides[connection_dependency] = lambda: BrokenConn()
    client = _client()

    resp = client.get("/healthz")

    api.dependency_overrides.clear()

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "error"
    assert "boom" in body["checks"]["database"]["detail"]


def test_healthz_reports_adapter_failures(monkeypatch):
    monkeypatch.setattr(settings, "use_live_feed", False)
    monkeypatch.setattr(settings, "use_powerledger_live", False)
    monkeypatch.setattr(settings, "use_ice_live", True)
    monkeypatch.setattr(settings, "ice_api_url", "https://ice.example")
    monkeypatch.setattr(settings, "ice_symbol", "TEST")
    monkeypatch.setattr("app.web._probe_ice_live", lambda: {"status": "error", "detail": "timeout"})

    client = _client()
    resp = client.get("/healthz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["adapters"]["ice_live"]["detail"] == "timeout"


def test_ui_service_start_enforces_fixed_command(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(web, "_orchestrator_process", None)

    started = {}

    class DummyProcess:
        pid = 999

        def __init__(self, args, env=None):
            started["args"] = args
            started["env"] = env or {}
            self.args = args

        def poll(self):
            return None

    monkeypatch.setattr(web.subprocess, "Popen", lambda args, env=None: DummyProcess(args, env))

    client = _client()
    resp = client.post(
        "/ui/services/start",
        headers=_auth_headers("secret-key"),
        json={
            "command": web._ORCHESTRATOR_CMD.copy(),
            "env": {"ENV_FILE": ".env.custom", "USE_LIVE_FEED": "0"},
        },
    )

    assert resp.status_code == 200
    assert started["args"] == web._ORCHESTRATOR_CMD
    assert started["env"]["ENV_FILE"] == ".env.custom"
    assert started["env"]["USE_LIVE_FEED"] == "0"


def test_ui_service_start_rejects_custom_command(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(web, "_orchestrator_process", None)
    monkeypatch.setattr(web.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))
    warnings: list[tuple[tuple, dict]] = []

    def _fake_warning(*args, **kwargs):
        warnings.append((args, kwargs))

    monkeypatch.setattr(web.logger, "warning", _fake_warning)

    client = _client()
    resp = client.post(
        "/ui/services/start",
        headers=_auth_headers("secret-key"),
        json={"command": ["/bin/echo", "hi"]},
    )

    assert resp.status_code == 400
    assert warnings
    assert "disallowed_command" in warnings[0][0][0]


def test_ui_service_start_rejects_unapproved_env(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(web, "_orchestrator_process", None)
    called = {}
    warnings: list[tuple[tuple, dict]] = []

    def _fake_popen(*_args, **_kwargs):
        called["invoked"] = True
        raise AssertionError("Popen should not be called when env is invalid")

    def _fake_warning(*args, **kwargs):
        warnings.append((args, kwargs))

    monkeypatch.setattr(web.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(web.logger, "warning", _fake_warning)

    client = _client()
    resp = client.post(
        "/ui/services/start",
        headers=_auth_headers("secret-key"),
        json={"env": {"UNSAFE": "1"}},
    )

    assert resp.status_code == 400
    assert warnings
    assert "disallowed_env" in warnings[0][0][0]
    assert not called
