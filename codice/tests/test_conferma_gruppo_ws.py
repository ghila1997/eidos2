"""Il percorso completo della conferma di un gruppo, sul filo vero: la POST
risponde 202 e l'avanzamento arriva sul WebSocket di sessione gia' aperto
(`azione_progresso`/`azione_fine`).

Le parti erano gia' testate separatamente (`test_azioni` per l'esecuzione,
`test_canali` per la consegna) e passavano tutte, ma l'utente **non vedeva
niente a schermo**: e' il collegamento tra le due a non essere mai stato
provato insieme. Questo test lo copre.
"""
from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app import app
from orchestratore import agente, azioni, conversazione, gmail_client

TENANT = "540d61dc-175d-425b-b3a0-7ae1e01eec7f"
SUPABASE_URL = "https://fake.supabase.co"


@pytest.fixture
def _sessione_finta(monkeypatch):
    async def fake_sessione(request):
        return {"tenant_id": TENANT, "user_id": "user-1", "role": "owner"}

    async def fake_motore_per(tenant_id):
        return object()

    async def storico_vuoto(tenant_id):
        return []

    monkeypatch.setattr("interfaccia_utente.router.get_sessione_corrente", fake_sessione)
    monkeypatch.setattr("orchestratore.router.get_sessione_corrente", fake_sessione)
    monkeypatch.setattr(agente, "motore_per", fake_motore_per)
    monkeypatch.setattr(conversazione, "get_messaggi", storico_vuoto)


def test_conferma_gruppo_risponde_subito_e_racconta_sul_websocket(
    respx_mock, monkeypatch, _sessione_finta
):
    righe = [
        {
            "id": f"az-{i}", "tenant_id": TENANT, "tipo": azioni.TIPO_TRASH_EMAIL,
            "payload": {"message_id": f"m{i}", "mittente": "Tizio", "oggetto": f"Ogg {i}"},
            "stato": azioni.STATO_IN_ATTESA,
        }
        for i in range(3)
    ]
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        side_effect=[httpx.Response(200, json=[r]) for r in righe]
    )
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[])
    )

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_cestina(access_token, message_id):
        return {"id": message_id}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "cestina_messaggio", fake_cestina)

    client = TestClient(app, base_url="https://testserver")
    with client.websocket_connect("/ws/session") as ws:
        assert ws.receive_json()["evento"] == "storico"   # primo evento del canale

        risposta = client.post(
            "/azioni/conferma-gruppo",
            json={"decisioni": {f"az-{i}": True for i in range(3)}},
        )
        # 202: preso in carico, NON finito - la scheda puo' sparire subito
        assert risposta.status_code == 202
        assert risposta.json() == {"avviate": 3}

        eventi = []
        while True:
            evento = ws.receive_json()
            eventi.append(evento)
            if evento["evento"] == "azione_fine":
                break

    progressi = [e for e in eventi if e["evento"] == "azione_progresso"]
    assert [e["fatte"] for e in progressi] == [1, 2, 3]
    assert all(e["totale"] == 3 for e in progressi)
    assert eventi[-1] == {
        "evento": "azione_fine",
        "esito": "3 mail spostate nel cestino",
        "errore": False,
    }


def test_conferma_gruppo_informa_il_modello_dell_esito(
    respx_mock, monkeypatch, _sessione_finta
):
    """L'esito deve rientrare nel contesto: senza, al turno dopo il modello
    risponde "non ancora" e ripropone azioni gia' eseguite."""
    riga = {
        "id": "az-1", "tenant_id": TENANT, "tipo": azioni.TIPO_TRASH_EMAIL,
        "payload": {"message_id": "m1", "mittente": "Tizio", "oggetto": "Ogg"},
        "stato": azioni.STATO_IN_ATTESA,
    }
    respx_mock.get(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[riga])
    )
    respx_mock.patch(f"{SUPABASE_URL}/rest/v1/azioni_pending").mock(
        return_value=httpx.Response(200, json=[])
    )

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_cestina(access_token, message_id):
        return {"id": message_id}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "cestina_messaggio", fake_cestina)
    agente._consuma_esiti(TENANT)   # parte pulito

    client = TestClient(app, base_url="https://testserver")
    with client.websocket_connect("/ws/session") as ws:
        ws.receive_json()
        client.post("/azioni/conferma-gruppo", json={"decisioni": {"az-1": True}})
        while ws.receive_json()["evento"] != "azione_fine":
            pass

    assert agente._consuma_esiti(TENANT) == ["Mail spostata nel cestino"]
