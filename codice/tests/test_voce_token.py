"""POST /voice/token (Tappa 6, incremento 1): il server emette token
effimeri per il client vocale — Deepgram grant (JWT, TTL 30s) e ElevenLabs
single-use token (15 min, `tts_websocket`). Le key permanenti dei fornitori
non lasciano mai il server: il client riceve solo credenziali a scadenza.
"""
from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app import app
from orchestratore import router as router_mod

DEEPGRAM_GRANT_URL = "https://api.deepgram.com/v1/auth/grant"
ELEVENLABS_TOKEN_URL = "https://api.elevenlabs.io/v1/single-use-token/tts_websocket"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture()
def sessione_finta(monkeypatch):
    async def fake_sessione(request):
        return {"tenant_id": "tenant-1", "user_id": "user-1", "role": "owner"}

    monkeypatch.setattr(router_mod, "get_sessione_corrente", fake_sessione)


@pytest.fixture()
def chiavi_voce(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-key-segreta")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xi-key-segreta")


def test_voice_token_senza_cookie_e_401():
    resp = _client().post("/voice/token")
    assert resp.status_code == 401


def test_voice_token_emette_entrambi_i_token(sessione_finta, chiavi_voce, respx_mock):
    grant = respx_mock.post(DEEPGRAM_GRANT_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "jwt-dg", "expires_in": 30})
    )
    single_use = respx_mock.post(ELEVENLABS_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"token": "sutkn-xi"})
    )

    resp = _client().post("/voice/token")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deepgram"] == {"token": "jwt-dg", "scadenza_secondi": 30}
    assert body["elevenlabs"] == {"token": "sutkn-xi", "scadenza_secondi": 900}

    # le key permanenti si usano solo server-side, negli header giusti
    assert grant.calls[0].request.headers["authorization"] == "Token dg-key-segreta"
    assert single_use.calls[0].request.headers["xi-api-key"] == "xi-key-segreta"
    # e non compaiono mai nella risposta al client
    assert "dg-key-segreta" not in resp.text
    assert "xi-key-segreta" not in resp.text


def test_voice_token_key_mancanti_e_503(sessione_finta, monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    resp = _client().post("/voice/token")
    assert resp.status_code == 503
    assert "voce" in resp.json()["detail"].lower()


def test_voice_token_provider_giu_e_502(sessione_finta, chiavi_voce, respx_mock):
    respx_mock.post(DEEPGRAM_GRANT_URL).mock(return_value=httpx.Response(500, text="kaput"))
    respx_mock.post(ELEVENLABS_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"token": "sutkn-xi"})
    )
    resp = _client().post("/voice/token")
    assert resp.status_code == 502
    # messaggio pulito, niente dettagli interni del fornitore
    assert "kaput" not in resp.text
