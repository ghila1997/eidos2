"""Endpoint WS /chat/stream (Tappa 6, incr.4) - la logica di decisione e'
gia' testata in test_turno_vocale.py; qui si verifica solo il collegamento:
auth, formato dei messaggi sul filo, propagazione della disconnessione."""
from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import app
from orchestratore import agente, azioni, ponte, turno_vocale
from orchestratore.router import _invia_su_websocket, _ricevi_da_websocket

TENANT = "540d61dc-175d-425b-b3a0-7ae1e01eec7f"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


class FakeMotoreOk:
    async def turno(self, messaggio, canale):
        from claude_agent_sdk.types import ResultMessage
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id="s1", result=f"risposta a: {messaggio}",
        )

    async def interrompi(self):
        pass


def test_ws_richiede_sessione_autenticata(monkeypatch):
    client = _client()
    # senza cookie di sessione: il server rifiuta l'handshake chiudendo
    # prima di accept() - TestClient lo segnala come WebSocketDisconnect
    # gia' sull'apertura della connessione (mai stato "accepted").
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/chat/stream"):
            pass
    assert exc_info.value.code == 4401


def test_ws_scambio_completo_con_sessione_valida(monkeypatch):
    async def fake_sessione(request):
        return {"tenant_id": TENANT, "user_id": "user-1", "role": "owner"}

    async def fake_motore_per(tenant_id):
        return FakeMotoreOk()

    async def nessuna_azione(tenant_id):
        return None

    async def niente_ponte(messaggio):
        return None

    monkeypatch.setattr("orchestratore.router.get_sessione_corrente", fake_sessione)
    monkeypatch.setattr(agente, "motore_per", fake_motore_per)
    monkeypatch.setattr(azioni, "ottieni_azioni_pendenti_tenant", nessuna_azione)
    monkeypatch.setattr(ponte, "genera_ponte", niente_ponte)

    client = _client()
    with client.websocket_connect("/chat/stream") as ws:
        ws.send_json({"tipo": "parziale", "testo": "ciao"})
        primo = ws.receive_json()
        assert primo["evento"] == "fine"
        assert primo["risposta"] == "risposta a: ciao"


def test_invia_gestisce_websocket_disconnect():
    """Verifica che _invia_su_websocket (la funzione VERA usata da
    chat_stream_ws, non una riscrittura) converta WebSocketDisconnect
    in ConnessioneChiusa, evitando che una disconnessione del client
    durante l'invio propaghi un'eccezione non gestita."""

    class FakeWebSocket:
        async def send_json(self, data):
            raise WebSocketDisconnect(code=1000)

    async def prova():
        with pytest.raises(turno_vocale.ConnessioneChiusa):
            await _invia_su_websocket(FakeWebSocket(), {"test": "data"})

    asyncio.run(prova())


def test_ricevi_gestisce_websocket_disconnect():
    """Specchio del test sopra per _ricevi_da_websocket: stessa
    conversione di eccezione, stessa funzione vera usata da
    chat_stream_ws."""

    class FakeWebSocket:
        async def receive_json(self):
            raise WebSocketDisconnect(code=1000)

    async def prova():
        with pytest.raises(turno_vocale.ConnessioneChiusa):
            await _ricevi_da_websocket(FakeWebSocket())

    asyncio.run(prova())
