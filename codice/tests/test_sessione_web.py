"""Sessione web (Tappa 7.1): canale WS persistente che esegue un turno di
solo testo alla volta, riusando la traduzione turno->eventi condivisa
(`orchestratore/streaming.py`). Nessun ponte/speculativo (semantica vocale,
fuori posto nel testo - vedi DECISIONS.md 2026-07-28 pt.3)."""
from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk.types import ResultMessage, StreamEvent

from orchestratore import agente, azioni
from interfaccia_utente.sessione_web import ConnessioneChiusa, gestisci_sessione

pytestmark = pytest.mark.asyncio


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
    """Un elenco di eventi SDK per turno (index-esimo turno -> lista i-esima);
    se ne arrivano piu' del previsto, riusa l'ultima lista."""

    def __init__(self, turni):
        self._turni = turni
        self.testi_ricevuti = []

    async def turno(self, messaggio, canale):
        self.testi_ricevuti.append((messaggio, canale))
        indice = min(len(self.testi_ricevuti) - 1, len(self._turni) - 1)
        for e in self._turni[indice]:
            yield e


class RicevitoreScriptato:
    """Restituisce i messaggi dati in ordine, poi solleva ConnessioneChiusa."""

    def __init__(self, messaggi):
        self._it = iter(messaggi)

    async def __call__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise ConnessioneChiusa()


class RegistroInviati:
    def __init__(self):
        self.eventi = []

    async def __call__(self, evento):
        self.eventi.append(evento)


@pytest.fixture(autouse=True)
def _fake_motore_per(monkeypatch):
    motori = {}

    async def fake_motore_per(tenant_id):
        return motori[tenant_id]

    async def nessuna_azione_pendente(tenant_id):
        return None

    monkeypatch.setattr(agente, "motore_per", fake_motore_per)
    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", nessuna_azione_pendente)
    monkeypatch.setattr(azioni, "azione_bloccante", nessuna_azione_pendente)
    return motori


async def test_un_messaggio_produce_delta_e_fine(_fake_motore_per):
    _fake_motore_per["t1"] = FakeMotore([[_delta("Ciao"), _result("Ciao")]])
    ricevi = RicevitoreScriptato([{"tipo": "messaggio", "testo": "ciao"}])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    tipi = [e["evento"] for e in invia.eventi]
    assert tipi == ["delta", "fine"]
    assert invia.eventi[0] == {"evento": "delta", "testo": "Ciao"}
    assert invia.eventi[-1]["risposta"] == "Ciao"


async def test_turno_di_testo_usa_canale_testo(_fake_motore_per):
    motore = FakeMotore([[_result("ok")]])
    _fake_motore_per["t1"] = motore
    ricevi = RicevitoreScriptato([{"tipo": "messaggio", "testo": "ciao"}])

    await gestisci_sessione("t1", ricevi, RegistroInviati())

    assert motore.testi_ricevuti == [("ciao", "testo")]


async def test_tool_in_corso_senza_prefisso_mcp(_fake_motore_per):
    _fake_motore_per["t1"] = FakeMotore([[_tool_start("mcp__eidos__search_events"), _result("ok")]])
    ricevi = RicevitoreScriptato([{"tipo": "messaggio", "testo": "impegni?"}])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    tool_eventi = [e for e in invia.eventi if e["evento"] == "tool_in_corso"]
    assert tool_eventi and tool_eventi[0]["tool"] == "search_events"
    assert tool_eventi[0]["etichetta"] == "Cerco nel calendario"


async def test_due_messaggi_sulla_stessa_connessione(_fake_motore_per):
    motore = FakeMotore([[_delta("Uno"), _result("Uno")], [_delta("Due"), _result("Due")]])
    _fake_motore_per["t1"] = motore
    ricevi = RicevitoreScriptato([
        {"tipo": "messaggio", "testo": "primo"},
        {"tipo": "messaggio", "testo": "secondo"},
    ])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    assert [t for t, _ in motore.testi_ricevuti] == ["primo", "secondo"]
    tipi = [e["evento"] for e in invia.eventi]
    assert tipi == ["delta", "fine", "delta", "fine"]


async def test_errore_del_motore_pulito_mai_traceback(_fake_motore_per):
    class MotoreRotto:
        def __init__(self):
            self.testi_ricevuti = []

        async def turno(self, messaggio, canale):
            raise RuntimeError("dettaglio privato interno")
            yield  # pragma: no cover - rende la funzione un generatore

    _fake_motore_per["t1"] = MotoreRotto()
    ricevi = RicevitoreScriptato([{"tipo": "messaggio", "testo": "ciao"}])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    assert invia.eventi[-1]["evento"] == "errore"
    assert "dettaglio privato" not in invia.eventi[-1]["messaggio"]


async def test_errore_non_chiude_la_sessione(_fake_motore_per):
    """Un turno che fallisce emette errore ma il canale resta vivo: il
    messaggio successivo deve ancora essere servito."""
    class MotoreRottoPoiOk:
        def __init__(self):
            self.testi_ricevuti = []

        async def turno(self, messaggio, canale):
            self.testi_ricevuti.append(messaggio)
            if len(self.testi_ricevuti) == 1:
                raise RuntimeError("boom")
            yield _result("ripreso")

    _fake_motore_per["t1"] = MotoreRottoPoiOk()
    ricevi = RicevitoreScriptato([
        {"tipo": "messaggio", "testo": "che rompe"},
        {"tipo": "messaggio", "testo": "che va"},
    ])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    tipi = [e["evento"] for e in invia.eventi]
    assert tipi == ["errore", "fine"]


async def test_azione_pendente_diventa_scheda_non_errore(monkeypatch, _fake_motore_per):
    """Tappa 7.2: con un'azione già in attesa non parte un nuovo turno e il
    client riceve la **scheda** di conferma (evento azione_in_attesa con
    descrizione leggibile), non un errore rosso."""
    async def azione_pendente(tenant_id):
        return {"id": "az-1", "tipo": "send_email",
                "payload": {"destinatario": "x@y.it", "oggetto": "Ciao", "corpo": "Testo"}}

    monkeypatch.setattr(azioni, "azione_bloccante", azione_pendente)
    motore = FakeMotore([[_result("mai chiamato")]])
    _fake_motore_per["t1"] = motore
    ricevi = RicevitoreScriptato([{"tipo": "messaggio", "testo": "manda la mail"}])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    assert invia.eventi[0]["evento"] == "azione_in_attesa"
    assert invia.eventi[0]["azione"]["id"] == "az-1"
    assert invia.eventi[0]["azione"]["descrizione"]["titolo"] == "Invio email"
    assert motore.testi_ricevuti == []  # nessun turno avviato


async def test_messaggio_vuoto_ignorato(_fake_motore_per):
    motore = FakeMotore([[_result("ok")]])
    _fake_motore_per["t1"] = motore
    ricevi = RicevitoreScriptato([
        {"tipo": "messaggio", "testo": "   "},
        {"tipo": "messaggio", "testo": ""},
    ])
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)

    assert motore.testi_ricevuti == []
    assert invia.eventi == []


async def test_chiusura_connessione_ritorna_pulito(_fake_motore_per):
    _fake_motore_per["t1"] = FakeMotore([[_result("ok")]])
    ricevi = RicevitoreScriptato([])  # subito ConnessioneChiusa
    invia = RegistroInviati()

    await gestisci_sessione("t1", ricevi, invia)  # non solleva

    assert invia.eventi == []
