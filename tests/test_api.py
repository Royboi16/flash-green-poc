from fastapi.testclient import TestClient
from app.web import api

client = TestClient(api)


def test_trades_endpoint_empty(monkeypatch):
    monkeypatch.setattr("app.web.get_trades", lambda limit=100: [])
    resp = client.get("/trades")
    assert resp.status_code == 200
    assert resp.json() == []


def test_loan_events_endpoint_empty(monkeypatch):
    monkeypatch.setattr("app.web.get_loan_events", lambda limit=100: [])
    resp = client.get("/loans/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_loan_balances_endpoint_empty(monkeypatch):
    monkeypatch.setattr("app.web.get_loan_balances", lambda: [])
    resp = client.get("/loans/balances")
    assert resp.status_code == 200
    assert resp.json() == []
