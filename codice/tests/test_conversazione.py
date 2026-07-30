"""Record della conversazione (Tappa 7.3): messaggi utente/assistente/esito
persistiti per tenant. Stesso pattern di test del resto del DB: respx mocka
PostgREST, si verifica la forma della richiesta (anti-leak, ordine, bound,
passi sul messaggio giusto) senza toccare un Supabase vero."""
from __future__ import annotations

import json

import httpx
import pytest

from orchestratore import conversazione

SUPABASE_URL = "https://fake.supabase.co"
TENANT = "11111111-1111-1111-1111-111111111111"
ALTRO = "22222222-2222-2222-2222-222222222222"
TABELLA = f"{SUPABASE_URL}/rest/v1/conversazione_messaggi"


@pytest.mark.asyncio
async def test_salva_turno_scrive_due_messaggi_utente_poi_assistente(respx_mock):
    route = respx_mock.post(TABELLA).mock(return_value=httpx.Response(201, json=[]))

    await conversazione.salva_turno(TENANT, "ciao", "Ciao!", passi=None)

    righe = json.loads(route.calls.last.request.content)
    assert [r["ruolo"] for r in righe] == ["utente", "assistente"]
    assert righe[0]["contenuto"] == "ciao"
    assert righe[1]["contenuto"] == "Ciao!"
    assert all(r["tenant_id"] == TENANT for r in righe)
    # ordine garantito: l'assistente ha un created_at successivo all'utente
    assert righe[0]["created_at"] < righe[1]["created_at"]
    # PGRST102: in un insert batch tutte le righe devono avere le STESSE chiavi,
    # o PostgREST rifiuta con 400 (bug reale: `passi` solo sull'assistente ->
    # conversazione mai salvata, mascherato dai mock che non lo verificano).
    assert set(righe[0].keys()) == set(righe[1].keys())


@pytest.mark.asyncio
async def test_salva_turno_mette_i_passi_sul_messaggio_assistente(respx_mock):
    """Le 'cose fatte in mezzo' stanno sull'assistente, non sull'utente."""
    route = respx_mock.post(TABELLA).mock(return_value=httpx.Response(201, json=[]))
    passi = [{"etichetta": "Cerco nel calendario", "esito": "ok"}]

    await conversazione.salva_turno(TENANT, "che settimana?", "Hai 3 scadenze.", passi=passi)

    righe = json.loads(route.calls.last.request.content)
    assert righe[0].get("passi") is None
    assert righe[1]["passi"] == passi


@pytest.mark.asyncio
async def test_get_messaggi_filtra_tenant_bound_e_solo_conversazione(respx_mock):
    """Anti-leak + niente fetch illimitato + solo la conversazione (gli esiti
    delle azioni non entrano in cronologia, vedi DECISIONS.md 2026-07-29)."""
    route = respx_mock.get(TABELLA).mock(return_value=httpx.Response(200, json=[]))

    await conversazione.get_messaggi(TENANT)

    params = route.calls.last.request.url.params
    assert params["tenant_id"] == f"eq.{TENANT}"
    assert params["limit"] == str(conversazione.MAX_MESSAGGI)
    assert params["ruolo"] == "in.(utente,assistente)"


@pytest.mark.asyncio
async def test_get_messaggi_ordine_cronologico_crescente(respx_mock):
    """Si chiedono gli N piu' recenti (desc + limit) ma si mostrano dal piu'
    vecchio al piu' nuovo: la funzione inverte."""
    respx_mock.get(TABELLA).mock(
        return_value=httpx.Response(200, json=[
            {"ruolo": "assistente", "contenuto": "recente", "passi": None, "created_at": "2026-07-29T10:00:00Z"},
            {"ruolo": "utente", "contenuto": "vecchio", "passi": None, "created_at": "2026-07-29T09:00:00Z"},
        ])
    )

    messaggi = await conversazione.get_messaggi(TENANT)

    assert [m["contenuto"] for m in messaggi] == ["vecchio", "recente"]


@pytest.mark.asyncio
async def test_get_messaggi_di_tenant_diversi_non_condividono_scoping(respx_mock):
    route = respx_mock.get(TABELLA).mock(return_value=httpx.Response(200, json=[]))

    await conversazione.get_messaggi(TENANT)
    await conversazione.get_messaggi(ALTRO)

    assert route.calls[0].request.url.params["tenant_id"] == f"eq.{TENANT}"
    assert route.calls[1].request.url.params["tenant_id"] == f"eq.{ALTRO}"
