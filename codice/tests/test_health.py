from starlette.testclient import TestClient

from app import app

client = TestClient(app, base_url="https://testserver")


def test_health_is_public():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["message"] == "hello world"
