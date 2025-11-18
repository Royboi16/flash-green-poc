from fastapi.testclient import TestClient

from app.web import api, settings


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
