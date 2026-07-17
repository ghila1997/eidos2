import httpx
import pytest
from starlette.testclient import TestClient

from app import app
from fondamenta import auth

SUPABASE_URL = "https://fake.supabase.co"


@pytest.fixture(autouse=True)
def _svuota_cache_sessioni():
    auth._CACHE_SESSIONI.clear()
    yield
    auth._CACHE_SESSIONI.clear()


def make_client() -> TestClient:
    # base_url https: necessario perché i cookie di sessione sono `secure`.
    return TestClient(app, base_url="https://testserver")


def test_me_without_cookie_is_401():
    resp = make_client().get("/me")
    assert resp.status_code == 401


def test_login_with_bad_credentials_is_401(respx_mock):
    respx_mock.post(f"{SUPABASE_URL}/auth/v1/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    resp = make_client().post(
        "/login", json={"email": "x@example.com", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_me_with_invalid_token_is_401(respx_mock):
    respx_mock.get(f"{SUPABASE_URL}/auth/v1/user").mock(
        return_value=httpx.Response(401, json={"error": "invalid token"})
    )
    client = make_client()
    client.cookies.set("sb_access_token", "bad-token")
    resp = client.get("/me")
    assert resp.status_code == 401


def test_login_then_me_returns_tenant(respx_mock):
    respx_mock.post(f"{SUPABASE_URL}/auth/v1/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok-123", "refresh_token": "ref-123"}
        )
    )
    respx_mock.get(f"{SUPABASE_URL}/auth/v1/user").mock(
        return_value=httpx.Response(
            200, json={"id": "user-1", "email": "founder@example.com"}
        )
    )
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/tenant_members").mock(
        return_value=httpx.Response(
            200, json=[{"tenant_id": "tenant-1", "role": "owner"}]
        )
    )

    client = make_client()
    login_resp = client.post(
        "/login", json={"email": "founder@example.com", "password": "correct"}
    )
    assert login_resp.status_code == 200

    me_resp = client.get("/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["user_id"] == "user-1"
    assert body["tenant_id"] == "tenant-1"
    assert body["role"] == "owner"


def test_sessione_valida_in_cache_non_richiama_supabase(respx_mock):
    """Trovato a STOP 2 Tappa 6 (voce): la verifica auth costava ~0,5-0,8s
    di roundtrip Supabase a OGNI turno di conversazione. Una sessione già
    verificata resta valida per il TTL della cache senza richiamare Supabase."""
    user_mock = respx_mock.get(f"{SUPABASE_URL}/auth/v1/user").mock(
        return_value=httpx.Response(200, json={"id": "user-1", "email": "f@x.it"})
    )
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/tenant_members").mock(
        return_value=httpx.Response(200, json=[{"tenant_id": "tenant-1", "role": "owner"}])
    )
    client = make_client()
    client.cookies.set("sb_access_token", "tok-cache")
    assert client.get("/me").status_code == 200
    assert client.get("/me").status_code == 200
    assert user_mock.call_count == 1


def test_cache_sessione_scade_dopo_il_ttl(respx_mock, monkeypatch):
    user_mock = respx_mock.get(f"{SUPABASE_URL}/auth/v1/user").mock(
        return_value=httpx.Response(200, json={"id": "user-1", "email": "f@x.it"})
    )
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/tenant_members").mock(
        return_value=httpx.Response(200, json=[{"tenant_id": "tenant-1", "role": "owner"}])
    )
    client = make_client()
    client.cookies.set("sb_access_token", "tok-scadenza")
    assert client.get("/me").status_code == 200

    orologio = auth.time.monotonic()
    monkeypatch.setattr(auth.time, "monotonic", lambda: orologio + auth._CACHE_TTL_SECONDI + 1)
    assert client.get("/me").status_code == 200
    assert user_mock.call_count == 2


def test_sessione_non_valida_non_finisce_in_cache(respx_mock):
    respx_mock.get(f"{SUPABASE_URL}/auth/v1/user").mock(
        return_value=httpx.Response(401, json={"error": "invalid token"})
    )
    client = make_client()
    client.cookies.set("sb_access_token", "tok-cattivo")
    assert client.get("/me").status_code == 401
    assert auth._CACHE_SESSIONI == {}


def test_me_without_tenant_membership_is_404(respx_mock):
    respx_mock.get(f"{SUPABASE_URL}/auth/v1/user").mock(
        return_value=httpx.Response(
            200, json={"id": "user-orfano", "email": "orfano@example.com"}
        )
    )
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/tenant_members").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = make_client()
    client.cookies.set("sb_access_token", "tok-valido")
    resp = client.get("/me")
    assert resp.status_code == 404
