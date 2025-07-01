from fastapi.testclient import TestClient
from app.web import api, get_trades

client = TestClient(api)

def test_trades_endpoint_empty(monkeypatch):
    monkeypatch.setattr("app.web.get_trades", lambda limit: [])
    resp = client.get("/trades")
    assert resp.status_code == 200
    assert resp.json() == []



