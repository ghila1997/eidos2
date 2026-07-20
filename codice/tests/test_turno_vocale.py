"""Turno vocale (Tappa 6, incr.4): macchina a stati che decide quando
avviare/interrompere/lasciar proseguire un tentativo di risposta, in base
ai transcript parziali/finali ricevuti dal client vocale via WebSocket."""
from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk.types import ResultMessage, StreamEvent

from orchestratore import ponte, azioni
from orchestratore.turno_vocale import _normalizza, _esegui_tentativo


def test_normalizza_ignora_maiuscole_e_punteggiatura_finale():
    """Deepgram ripulisce il transcript finale (maiuscole/punteggiatura)
    anche senza parole nuove - un confronto a stringa esatta butterebbe via
    quasi ogni tentativo speculativo per differenze cosmetiche."""
    assert _normalizza("Che impegni ho domani?") == _normalizza("che impegni ho domani")


def test_normalizza_collassa_spazi_multipli():
    assert _normalizza("che   impegni  ho domani") == _normalizza("che impegni ho domani")


def test_normalizza_testi_diversi_restano_diversi():
    assert _normalizza("che impegni ho domani") != _normalizza("che impegni ho dopodomani")


def _delta(testo: str) -> StreamEvent:
    return StreamEvent(
        uuid="u1", session_id="s1",
        event={"type": "content_block_delta", "index": 0,
               "delta": {"type": "text_delta", "text": testo}},
    )


def _tool_start(nome_mcp: str) -> StreamEvent:
    return StreamEvent(
        uuid="u2", session_id="s1",
        event={"type": "content_block_start", "index": 1,
               "content_block": {"type": "tool_use", "id": "tu_1", "name": nome_mcp, "input": {}}},
    )


def _result(testo="ok") -> ResultMessage:
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=1, session_id="s1", result=testo,
    )


class FakeMotore:
    def __init__(self, eventi_turno):
        self._eventi = eventi_turno
        self.testi_ricevuti = []

    async def turno(self, messaggio, canale):
        self.testi_ricevuti.append(messaggio)
        for e in self._eventi:
            yield e


async def _svuota_coda(coda: asyncio.Queue) -> list:
    eventi = []
    while not coda.empty():
        eventi.append(coda.get_nowait())
    return eventi


def _monta_ponte(monkeypatch, ritorno=None):
    async def fake(messaggio):
        return ritorno

    monkeypatch.setattr(ponte, "genera_ponte", fake)


def _monta_azioni(monkeypatch, azione_ritorno=None):
    async def fake(tenant_id):
        return azione_ritorno

    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", fake)


@pytest.mark.asyncio
async def test_esegui_tentativo_mette_delta_e_fine_in_coda(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)  # astensione, niente ponte
    _monta_azioni(monkeypatch, azione_ritorno=None)
    motore = FakeMotore([_delta("Ciao"), _result("Ciao")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "ciao", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    tipi = [e[2]["evento"] for e in eventi]
    assert "delta" in tipi
    assert tipi[-1] == "fine"
    assert all(e[1] == 1 for e in eventi)  # tutti taggati col tentativo_id giusto


@pytest.mark.asyncio
async def test_esegui_tentativo_include_ponte_se_generato(monkeypatch):
    _monta_ponte(monkeypatch, ritorno="Vediamo subito...")
    _monta_azioni(monkeypatch, azione_ritorno=None)
    motore = FakeMotore([_result("ok")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "che impegni ho domani", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert eventi[0][2] == {"evento": "ponte", "testo": "Vediamo subito..."}


@pytest.mark.asyncio
async def test_esegui_tentativo_traduce_tool_in_corso_senza_prefisso_mcp(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)
    _monta_azioni(monkeypatch, azione_ritorno=None)
    motore = FakeMotore([_tool_start("mcp__eidos__search_events"), _result("ok")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "impegni?", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert {"evento": "tool_in_corso", "tool": "search_events"} in [e[2] for e in eventi]


@pytest.mark.asyncio
async def test_esegui_tentativo_errore_pulito_mai_traceback(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)
    _monta_azioni(monkeypatch, azione_ritorno=None)

    class MotoreRotto:
        async def turno(self, messaggio, canale):
            raise RuntimeError("boom interno con dettagli privati")
            yield  # pragma: no cover - rende la funzione un generatore

    coda = asyncio.Queue()
    await _esegui_tentativo(MotoreRotto(), "ciao", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert eventi[-1][2]["evento"] == "errore"
    assert "boom interno" not in eventi[-1][2]["messaggio"]
