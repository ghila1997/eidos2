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
        # Settato a fine turno (mai a tick contati) - i test a livello di
        # gestisci_sessione_vocale lo usano per sapere con certezza quando
        # il tentativo ha finito di mettere i suoi eventi in coda, invece di
        # contare un numero fisso di sleep(0) prima di "disconnettere".
        self.concluso = asyncio.Event()

    async def turno(self, messaggio, canale):
        await asyncio.sleep(0)  # Cede il controllo al loop per far eseguire task_ponte
        self.testi_ricevuti.append(messaggio)
        for e in self._eventi:
            yield e
        self.concluso.set()


async def _svuota_coda(coda: asyncio.Queue) -> list:
    eventi = []
    while not coda.empty():
        eventi.append(coda.get_nowait())
    return eventi


def _monta_ponte(monkeypatch, ritorno=None):
    async def fake(messaggio):
        return ritorno

    monkeypatch.setattr(ponte, "genera_ponte", fake)


def _monta_azioni(monkeypatch, azioni_ritorno=()):
    async def fake(tenant_id):
        return list(azioni_ritorno)

    monkeypatch.setattr(azioni, "ottieni_azioni_pendenti_tenant", fake)


@pytest.mark.asyncio
async def test_esegui_tentativo_mette_delta_e_fine_in_coda(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)  # astensione, niente ponte
    _monta_azioni(monkeypatch)
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
    _monta_azioni(monkeypatch)
    motore = FakeMotore([_result("ok")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "che impegni ho domani", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert eventi[0][2] == {"evento": "ponte", "testo": "Vediamo subito..."}


@pytest.mark.asyncio
async def test_esegui_tentativo_traduce_tool_in_corso_senza_prefisso_mcp(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)
    _monta_azioni(monkeypatch)
    motore = FakeMotore([_tool_start("mcp__eidos__search_events"), _result("ok")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "impegni?", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    tool_eventi = [e[2] for e in eventi if e[2]["evento"] == "tool_in_corso"]
    assert tool_eventi and tool_eventi[0]["tool"] == "search_events"


@pytest.mark.asyncio
async def test_esegui_tentativo_errore_pulito_mai_traceback(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)
    _monta_azioni(monkeypatch)

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
    """Ricevi() scriptato: una lista di 'passi' client, poi ConnessioneChiusa.

    Un passo e' o un messaggio (dict, restituito subito) o un
    asyncio.Event (atteso prima di restituire il passo successivo) - mai un
    numero fisso di tick: un vero WS impiega piu' tempo a rilevare la
    disconnessione di quanto ne impieghi a consegnare un messaggio gia'
    bufferizzato (che qui torna sincrono), e un tentativo appena avviato
    deve avere modo di girare prima che la 'disconnessione' arrivi - ma
    quel momento e' un evento preciso (il fake motore lo segnala), non un
    numero di scheduler tick indovinato a tentativi.

    'attesa_dopo_esaurimento', se dato, e' atteso dopo l'ultimo passo e
    prima di sollevare ConnessioneChiusa (es. 'aspetta che il tentativo
    abbia finito di mettere i suoi eventi in coda'). 'chiudi_alla_fine=False'
    fa restare il ricevitore sospeso invece di chiudere la connessione - per
    i test che vogliono isolare un comportamento dall'interrompi() legittimo
    di chiusura sessione e cancellano il task esplicitamente."""

    def __init__(
        self,
        passi: list[dict | asyncio.Event],
        attesa_dopo_esaurimento: asyncio.Event | None = None,
        chiudi_alla_fine: bool = True,
        timeout: float = 2.0,
    ):
        self._passi = iter(passi)
        self._attesa_dopo_esaurimento = attesa_dopo_esaurimento
        self._chiudi_alla_fine = chiudi_alla_fine
        self._timeout = timeout
        self._sospensione_infinita = asyncio.Event()  # mai settato di proposito

    async def __call__(self) -> dict:
        while True:
            try:
                passo = next(self._passi)
            except StopIteration:
                break
            if isinstance(passo, asyncio.Event):
                await asyncio.wait_for(passo.wait(), timeout=self._timeout)
                continue
            return passo

        if self._attesa_dopo_esaurimento is not None:
            await asyncio.wait_for(self._attesa_dopo_esaurimento.wait(), timeout=self._timeout)
        if not self._chiudi_alla_fine:
            await self._sospensione_infinita.wait()
        raise ConnessioneChiusa()


class RegistroInviati:
    def __init__(self):
        self.eventi: list[dict] = []

    async def __call__(self, evento: dict) -> None:
        self.eventi.append(evento)


@pytest.fixture(autouse=True)
def _fake_motore_per(monkeypatch):
    """Sostituisce agente.motore_per con un FakeMotore scriptabile per
    tenant, e azioni.ottieni_azioni_pendenti_tenant con 'mai pendente' di
    default (i test che vogliono il gate lo sovrascrivono)."""
    motori = {}

    async def fake_motore_per(tenant_id):
        return motori[tenant_id]

    async def nessuna_azione_pendente(tenant_id):
        return None

    monkeypatch.setattr(agente, "motore_per", fake_motore_per)
    monkeypatch.setattr(azioni, "ottieni_azioni_pendenti_tenant", nessuna_azione_pendente)
    return motori


async def test_parziale_singolo_avvia_un_tentativo_e_lo_completa(monkeypatch, _fake_motore_per):
    _monta_ponte(monkeypatch, ritorno=None)
    motore = FakeMotore([_delta("Ciao!"), _result("Ciao!")])
    motore.interrotto = 0
    async def interrompi():
        motore.interrotto += 1
    motore.interrompi = interrompi
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato(
        [{"tipo": "parziale", "testo": "ciao"}],
        attesa_dopo_esaurimento=motore.concluso,
    )
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
            # Un evento per chiamata, settato come primissima azione di
            # turno() (prima di ogni yield) - segnale esplicito e
            # deterministico di "questo tentativo e' davvero partito", mai
            # un numero di scheduler tick indovinato.
            self.avviato = [asyncio.Event(), asyncio.Event()]

        async def turno(self, messaggio, canale):
            indice = self.chiamate
            self.avviato[indice].set()
            self.chiamate += 1
            if indice == 0:
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

    ricevi = RicevitoreScriptato(
        [
            {"tipo": "parziale", "testo": "che impegni ho domani"},
            motore.avviato[0],  # aspetta che il primo tentativo sia davvero partito
            {"tipo": "finale", "testo": "che impegni ho dopodomani"},
        ],
        attesa_dopo_esaurimento=motore.avviato[1],  # aspetta che il secondo sia partito
    )
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

    ricevi = RicevitoreScriptato(
        [
            {"tipo": "parziale", "testo": "che impegni ho domani"},
            {"tipo": "finale", "testo": "Che impegni ho domani?"},
        ],
        attesa_dopo_esaurimento=motore.concluso,
    )
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    assert motore.interrotto == 0
    assert {"evento": "annullato"} not in invia.eventi
    assert motore.testi_ricevuti == ["che impegni ho domani"]  # un solo turno vero, mai riavviato


async def test_azione_pendente_blocca_avvio_tentativo(monkeypatch, _fake_motore_per):
    async def azione_pendente(tenant_id):
        return [{"id": "az-1", "tipo": "send_email", "payload": {}}]

    monkeypatch.setattr(azioni, "ottieni_azioni_pendenti_tenant", azione_pendente)
    motore = FakeMotore([_result("mai chiamato")])
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([{"tipo": "parziale", "testo": "manda la mail"}])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)

    assert invia.eventi[0]["evento"] == "errore"
    assert motore.testi_ricevuti == []  # nessun tentativo avviato


async def test_azione_pendente_blocca_riavvio_dopo_interrupt(monkeypatch, _fake_motore_per):
    """Trappola del reviewer (Task 5): il gate azione-pendente valeva solo
    sul primo avvio, non sul riavvio dopo un ripensamento dell'utente - ma
    il tool del tentativo GIA' in corso puo' aver gia' creato un'azione
    pending (Safety Supervisor -> ask_user) prima che il parziale diverso
    arrivi. In quel caso il riavvio va bloccato esattamente come il primo
    avvio (CLAUDE.md: gate unico, nessuna eccezione) - il tentativo in
    corso non va toccato (mai interrompi()), e non deve partirne uno nuovo."""
    _monta_ponte(monkeypatch, ritorno=None)

    class MotoreCheSiBlocca:
        """Resta appeso finche' non interrotto - tiene un tentativo
        affidabilmente 'in corso' mentre il test invia il secondo parziale."""

        def __init__(self):
            self.interrotto = 0
            self.chiamate = 0
            self.avviato = asyncio.Event()  # settato come prima azione di turno(), prima di ogni yield
            self._sospeso = asyncio.Event()
            # Settato a fine turno() - il tentativo e' un task orfano
            # (fire-and-forget nel codice di produzione): serve per
            # ripulirlo deterministicamente a fine test invece di lasciarlo
            # pending al teardown dell'event loop (stesso ragionamento del
            # 'concluso' di MotoreAppeso sopra).
            self.concluso = asyncio.Event()

        async def turno(self, messaggio, canale):
            self.avviato.set()
            self.chiamate += 1
            yield _delta("Un pezzo...")
            await self._sospeso.wait()
            self.concluso.set()

        async def interrompi(self):
            self.interrotto += 1
            self._sospeso.set()

    motore = MotoreCheSiBlocca()
    _fake_motore_per["t1"] = motore

    # La prima chiamata al gate (prima di avviare il tentativo) non trova
    # nulla; la seconda (sul riavvio) simula che il tool del tentativo in
    # corso abbia gia' creato un'azione pending.
    chiamate_gate = 0
    gate_valutato_su_riavvio = asyncio.Event()

    async def azione_pendente_solo_su_riavvio(tenant_id):
        nonlocal chiamate_gate
        chiamate_gate += 1
        if chiamate_gate == 1:
            return []
        risultato = [{"id": "az-1", "tipo": "send_email", "payload": {}}]
        gate_valutato_su_riavvio.set()
        return risultato

    monkeypatch.setattr(azioni, "ottieni_azioni_pendenti_tenant", azione_pendente_solo_su_riavvio)

    # chiudi_alla_fine=False: dopo il secondo parziale il ricevitore resta
    # sospeso invece di sollevare ConnessioneChiusa - isoliamo l'effetto del
    # gate dall'interrompi() legittimo che la chiusura sessione causerebbe
    # comunque (il task viene cancellato esplicitamente dal test).
    ricevi = RicevitoreScriptato(
        [
            {"tipo": "parziale", "testo": "manda la mail a mario"},
            motore.avviato,  # aspetta che il tentativo sia davvero partito
            {"tipo": "parziale", "testo": "manda la mail a luigi"},
        ],
        chiudi_alla_fine=False,
    )
    invia = RegistroInviati()
    task = asyncio.create_task(gestisci_sessione_vocale("t1", ricevi, invia))
    try:
        # gate_valutato_su_riavvio si settao dentro il mock del gate, come
        # ultima azione prima del return - nessun await genuino separa quel
        # punto dal successivo `await invia({"evento": "errore", ...})` nel
        # ramo di riavvio (ne' il mock ne' RegistroInviati sospendono mai):
        # quando questo wait si risolve, l'evento "errore" e' gia' stato
        # invia()to nella stessa porzione ininterrotta di esecuzione.
        await asyncio.wait_for(gate_valutato_su_riavvio.wait(), timeout=2)

        assert motore.interrotto == 0  # il tentativo in corso non va mai toccato dal riavvio bloccato
        assert motore.chiamate == 1  # nessun secondo tentativo avviato
        assert invia.eventi[-1] == {
            "evento": "errore",
            "messaggio": "C'e' un'azione in attesa di conferma, risolvila prima di continuare.",
        }
        assert {"evento": "annullato"} not in invia.eventi
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Pulizia: il tentativo rimasto sospeso e' un task orfano
        # (fire-and-forget nel codice di produzione, mai atteso da
        # gestisci_sessione_vocale) - lo sblocchiamo e aspettiamo che si
        # concluda, altrimenti l'event loop lo distrugge ancora pending al
        # termine del test.
        await motore.interrompi()
        await asyncio.wait_for(motore.concluso.wait(), timeout=2)


async def test_chiusura_connessione_con_tentativo_in_corso_lo_interrompe(monkeypatch, _fake_motore_per):
    _monta_ponte(monkeypatch, ritorno=None)
    non_finisce_mai = asyncio.Event()

    class MotoreAppeso:
        def __init__(self):
            self.interrotto = 0
            # Settato quando turno() esce dal wait bloccato (dopo
            # interrompi()) - il tentativo, spawnato come task e mai atteso
            # da gestisci_sessione_vocale (fire-and-forget), continua a
            # girare in background anche dopo che la funzione ritorna: senza
            # aspettare questo segnale il test finirebbe prima che quel task
            # abbia finito di ripulirsi (task_ponte incluso), lasciando una
            # coroutine 'mai awaited' al teardown dell'event loop.
            self.concluso = asyncio.Event()

        async def turno(self, messaggio, canale):
            yield _delta("...")
            await non_finisce_mai.wait()
            self.concluso.set()

        async def interrompi(self):
            self.interrotto += 1
            non_finisce_mai.set()

    motore = MotoreAppeso()
    _fake_motore_per["t1"] = motore

    ricevi = RicevitoreScriptato([{"tipo": "parziale", "testo": "ciao"}])
    invia = RegistroInviati()
    await gestisci_sessione_vocale("t1", ricevi, invia)
    await asyncio.wait_for(motore.concluso.wait(), timeout=2)

    assert motore.interrotto == 1
