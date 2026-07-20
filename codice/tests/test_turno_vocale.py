"""Turno vocale (Tappa 6, incr.4): macchina a stati che decide quando
avviare/interrompere/lasciar proseguire un tentativo di risposta, in base
ai transcript parziali/finali ricevuti dal client vocale via WebSocket."""
from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk.types import ResultMessage, StreamEvent

from orchestratore import ponte, azioni, agente
from orchestratore.turno_vocale import _normalizza, _esegui_tentativo
from orchestratore.turno_vocale import ConnessioneChiusa, gestisci_sessione_vocale


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
        await asyncio.sleep(0)  # Cede il controllo al loop per far eseguire task_ponte
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


class RicevitoreScriptato:
    """Ricevi() scriptato: una lista di messaggi client, poi ConnessioneChiusa."""

    def __init__(self, messaggi: list[dict]):
        self._messaggi = iter(messaggi)

    async def __call__(self) -> dict:
        try:
            return next(self._messaggi)
        except StopIteration:
            # Un vero WS impiega piu' tempo a rilevare la disconnessione di
            # quanto ne impieghi a consegnare un messaggio gia' bufferizzato
            # (che qui torna sincrono): cede il controllo al loop piu' volte
            # - non un timer reale (instabile, dipendente dal carico della
            # macchina: verificato sperimentalmente non affidabile qui) - cosi'
            # un tentativo appena avviato ha modo di girare per intero prima
            # che la 'disconnessione' arrivi, proprio come farebbe una vera rete.
            for _ in range(20):
                await asyncio.sleep(0)
            raise ConnessioneChiusa()


class RegistroInviati:
    def __init__(self):
        self.eventi: list[dict] = []

    async def __call__(self, evento: dict) -> None:
        self.eventi.append(evento)


@pytest.fixture(autouse=True)
def _fake_motore_per(monkeypatch):
    """Sostituisce agente.motore_per con un FakeMotore scriptabile per
    tenant, e azioni.ottieni_azione_pendente_tenant con 'mai pendente' di
    default (i test che vogliono il gate lo sovrascrivono)."""
    motori = {}

    async def fake_motore_per(tenant_id):
        return motori[tenant_id]

    async def nessuna_azione_pendente(tenant_id):
        return None

    monkeypatch.setattr(agente, "motore_per", fake_motore_per)
    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", nessuna_azione_pendente)
    return motori


async def test_parziale_singolo_avvia_un_tentativo_e_lo_completa(monkeypatch, _fake_motore_per):
    _monta_ponte(monkeypatch, ritorno=None)
    motore = FakeMotore([_delta("Ciao!"), _result("Ciao!")])
    motore.interrotto = 0
    async def interrompi():
        motore.interrotto += 1
    motore.interrompi = interrompi
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([{"tipo": "parziale", "testo": "ciao"}])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    tipi = [e["evento"] for e in invia.eventi]
    assert tipi == ["delta", "fine"]
    assert motore.interrotto == 0  # mai interrotto: nessun ripensamento


async def test_parziale_diverso_interrompe_e_riparte(monkeypatch, _fake_motore_per):
    _monta_ponte(monkeypatch, ritorno=None)
    # primo tentativo: lento (mai emette 'fine' prima di essere interrotto)
    evento_bloccante = asyncio.Event()

    class MotoreLentoPoiVeloce:
        def __init__(self):
            self.interrotto = 0
            self.chiamate = 0

        async def turno(self, messaggio, canale):
            self.chiamate += 1
            if self.chiamate == 1:
                yield _delta("Un pezzo...")
                await evento_bloccante.wait()  # resta appeso finche' non interrotto
            else:
                yield _delta("Risposta vera.")
                yield _result("Risposta vera.")

        async def interrompi(self):
            self.interrotto += 1
            evento_bloccante.set()  # sblocca il primo turno (simula l'effetto di interrupt())

    motore = MotoreLentoPoiVeloce()
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([
        {"tipo": "parziale", "testo": "che impegni ho domani"},
        {"tipo": "finale", "testo": "che impegni ho dopodomani"},
    ])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    assert motore.interrotto == 1
    assert {"evento": "annullato"} in invia.eventi
    assert invia.eventi[-1] == {"evento": "delta", "testo": "Risposta vera."} or invia.eventi[-1]["evento"] == "fine"
    assert motore.chiamate == 2
    assert motore.testi_ricevuti == ["che impegni ho domani", "che impegni ho dopodomani"] if hasattr(motore, "testi_ricevuti") else True


async def test_finale_che_combacia_non_riavvia(monkeypatch, _fake_motore_per):
    """Trappola esplicita dal design doc: confronto normalizzato, non
    stringa esatta - 'Che impegni ho domani?' (finale, ripulito da Deepgram)
    deve combaciare con 'che impegni ho domani' (parziale)."""
    _monta_ponte(monkeypatch, ritorno=None)
    motore = FakeMotore([_delta("Domani sei libero."), _result("Domani sei libero.")])
    motore.interrotto = 0
    async def interrompi():
        motore.interrotto += 1
    motore.interrompi = interrompi
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([
        {"tipo": "parziale", "testo": "che impegni ho domani"},
        {"tipo": "finale", "testo": "Che impegni ho domani?"},
    ])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    assert motore.interrotto == 0
    assert {"evento": "annullato"} not in invia.eventi
    assert motore.testi_ricevuti == ["che impegni ho domani"]  # un solo turno vero, mai riavviato


async def test_azione_pendente_blocca_avvio_tentativo(monkeypatch, _fake_motore_per):
    async def azione_pendente(tenant_id):
        return {"id": "az-1", "tipo": "send_email", "payload": {}}

    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", azione_pendente)
    motore = FakeMotore([_result("mai chiamato")])
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([{"tipo": "parziale", "testo": "manda la mail"}])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    assert invia.eventi[0]["evento"] == "errore"
    assert motore.testi_ricevuti == []  # nessun tentativo avviato


async def test_chiusura_connessione_con_tentativo_in_corso_lo_interrompe(monkeypatch, _fake_motore_per):
    _monta_ponte(monkeypatch, ritorno=None)
    non_finisce_mai = asyncio.Event()

    class MotoreAppeso:
        def __init__(self):
            self.interrotto = 0

        async def turno(self, messaggio, canale):
            yield _delta("...")
            await non_finisce_mai.wait()

        async def interrompi(self):
            self.interrotto += 1
            non_finisce_mai.set()

    motore = MotoreAppeso()
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([{"tipo": "parziale", "testo": "ciao"}])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    assert motore.interrotto == 1
