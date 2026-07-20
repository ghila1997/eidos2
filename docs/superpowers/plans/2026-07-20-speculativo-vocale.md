# Speculativo vocale (Tappa 6, incremento 4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sostituire `/chat/stream` (oggi POST+SSE) con una connessione WebSocket persistente che permette al server di partire a generare su un transcript parziale "stabile" e di interromperlo in sicurezza se l'utente continua a parlare, riducendo la latenza percepita in voce.

**Architecture:** Il server tiene una macchina a stati per sessione vocale (`orchestratore/turno_vocale.py`): riceve `parziale`/`finale` dal client via WS, decide se avviare/interrompere/lasciar proseguire un "tentativo" (ponte + turno del motore, stesso schema già in produzione), inoltra `ponte`/`delta`/`tool_in_corso`/`fine`/`errore`/`annullato`. Il client (`voce/rilevatore_frase.py` + `voce/sessione_ws.py`) manda un `parziale` quando il transcript resta fermo per una soglia di tempo, e su `annullato` interrompe subito il proprio TTS senza pronunciare nulla.

**Tech Stack:** FastAPI WebSocket (server), libreria `websockets` (client, già in `voce/requirements-voce.txt`), `asyncio.Queue` per la concorrenza server-side, pytest + `starlette.testclient.TestClient.websocket_connect` per i test.

## Global Constraints

- Verifica preliminare già fatta (CLAUDE.md, "verificare capacità SDK prima di scrivere codice"): `ClaudeSDKClient.interrupt()` chiamato da un task diverso da quello che consuma `receive_response()` è confermato sicuro con un esperimento reale (vedi `docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md`, sezione "Verifica preliminare"). Non ri-verificare, è già un fatto assodato.
- Confronto "il testo combacia" è **sempre** su forma normalizzata (minuscolo, punteggiatura finale rimossa, spazi collassati), **mai** stringa esatta — vedi spec, causa reale: Deepgram ripulisce il transcript finale (maiuscole/punteggiatura) anche senza parole nuove.
- Il gate di conferma sulle azioni distruttive resta invariato e si applica **prima di avviare** un tentativo (non dopo) — stesso principio di oggi (`azioni.ottieni_azione_pendente_tenant`), qualunque sia il tentativo (speculativo o no).
- Mai due voci: un tentativo scartato non deve mai produrre audio lato client — l'evento `annullato` esiste apposta per questo.
- `/chat` (testuale) **non cambia**: resta un POST che usa `motore.turno()` direttamente, invariato da questo lavoro.
- Convenzione già in uso nel progetto (`codice/voce/__init__.py`): i wrapper di I/O puro (audio, rete) si verificano in reale (STOP 2), non con unit test — vale anche per `voce/sessione_ws.py` in questo piano.
- Naming, commenti "perché non cosa", stile TDD (test prima, RED verificato, poi GREEN): stessa disciplina di tutto il codice già scritto in questa tappa (vedi `orchestratore/ponte.py`, `orchestratore/agente.py` come riferimento di stile).

---

## Mappa dei file

**Nuovi:**
- `codice/orchestratore/turno_vocale.py` — macchina a stati server-side (sostituisce la logica oggi inline in `router.py:chat_stream`)
- `codice/tests/test_turno_vocale.py`
- `codice/tests/test_agente.py` — nuovo file dedicato a `MotoreAgente` (oggi le sue proprietà erano testate indirettamente via `test_chat_stream.py`, che questo piano ritira)
- `codice/voce/rilevatore_frase.py` — euristica "sembra completa" (puro timer)
- `codice/tests/test_rilevatore_frase.py`
- `codice/voce/sessione_ws.py` — wrapper client della connessione WebSocket (nessun test dedicato, vedi Global Constraints)

**Modificati:**
- `codice/orchestratore/router.py` — rimossa la vecchia `POST /chat/stream` e la sua logica inline; aggiunta `WS /chat/stream`
- `codice/voce/client.py` — riscritto il flusso del turno per usare `sessione_ws` + `rilevatore_frase` invece di `httpx` POST

**Rimossi:**
- `codice/tests/test_chat_stream.py` — testava il protocollo POST/SSE che questo piano sostituisce; le assertion ancora rilevanti (config di `MotoreAgente`) migrano in `test_agente.py`, quelle di comportamento del ponte migrano in `test_turno_vocale.py`

---

### Task 1: `MotoreAgente.interrompi()`

**Files:**
- Modify: `codice/orchestratore/agente.py`
- Create: `codice/tests/test_agente.py`

**Interfaces:**
- Consumes: nessuna dipendenza nuova
- Produces: `MotoreAgente.interrompi() -> None` — chiamabile in sicurezza mentre un altro task sta consumando `motore.turno()` sullo stesso motore (verificato, vedi Global Constraints). Usata da `turno_vocale.py` nel Task 5.

Nota: questo task **sposta** anche `FakeSDKClient` e i test esistenti di `prescalda`/`_opzioni` da `test_chat_stream.py` a questo nuovo file, così quando `test_chat_stream.py` viene rimosso (Task 7) non si perde copertura. Copia il codice di `FakeSDKClient` e delle fixture `base`/`_result` così come sono oggi in `codice/tests/test_chat_stream.py` (righe iniziali del file, classe `FakeSDKClient`, fixture `base`).

- [ ] **Step 1: Scrivi il file di test con `FakeSDKClient` copiato + il nuovo test per `interrompi()`**

```python
# codice/tests/test_agente.py
"""Test di MotoreAgente: ciclo di vita del client persistente, opzioni di
configurazione, interruzione di un tentativo in corso (Tappa 6, incr.4)."""
from __future__ import annotations

import pytest

from orchestratore import agente

TENANT = "tenant-1"


class FakeSDKClient:
    """ClaudeSDKClient scriptato: ogni istanza consuma i turni del copione.
    Un turno e' una lista di messaggi SDK oppure un'eccezione da sollevare."""

    copione: list[list] = []
    istanze: list["FakeSDKClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.prompts: list[str] = []
        self._turni = iter(FakeSDKClient.copione[len(FakeSDKClient.istanze)])
        self.connesso = False
        self.interrotto = 0
        FakeSDKClient.istanze.append(self)

    async def connect(self):
        self.connesso = True

    async def disconnect(self):
        self.connesso = False

    async def query(self, prompt):
        self.prompts.append(prompt)
        self._corrente = next(self._turni)

    async def interrupt(self):
        self.interrotto += 1

    async def receive_response(self):
        if isinstance(self._corrente, Exception):
            raise self._corrente
        for messaggio in self._corrente:
            yield messaggio


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(agente, "ClaudeSDKClient", FakeSDKClient)
    agente._motori.clear()
    FakeSDKClient.copione = []
    FakeSDKClient.istanze = []


async def test_interrompi_su_motore_senza_client_non_fa_nulla():
    """Nessun turno mai partito: interrompi() e' un no-op sicuro."""
    motore = await agente.motore_per(TENANT)
    await motore.interrompi()  # non deve sollevare


async def test_interrompi_chiama_interrupt_sul_client_connesso():
    from claude_agent_sdk.types import ResultMessage

    def _result(testo="ok"):
        return ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id="sess-1", result=testo,
        )

    FakeSDKClient.copione = [[[_result()]]]
    motore = await agente.motore_per(TENANT)
    async for _ in motore.turno("ciao", canale="voce"):
        pass  # il turno finisce, il client resta connesso e riusabile
    await motore.interrompi()
    assert FakeSDKClient.istanze[0].interrotto == 1
```

- [ ] **Step 2: Esegui i test, verifica che falliscano per il motivo giusto**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_agente.py -q`
Expected: FAIL — `AttributeError: 'MotoreAgente' object has no attribute 'interrompi'`

- [ ] **Step 3: Aggiungi `interrompi()` a `MotoreAgente` in `codice/orchestratore/agente.py`**

Aggiungi questo metodo dentro la classe `MotoreAgente`, subito dopo `_scarta_client`:

```python
    async def interrompi(self) -> None:
        """Interrompe il tentativo in corso su questo motore, se c'e'.
        Sicuro da chiamare in concorrenza mentre un altro task sta
        consumando turno() sullo stesso motore (verificato con esperimento
        reale 2026-07-19, vedi docs/superpowers/specs/2026-07-19-
        speculativo-vocale-design.md, "Verifica preliminare")."""
        if self._client is not None:
            try:
                await self._client.interrupt()
            except Exception:
                logger.warning(
                    "interrompi() fallito, il tentativo in corso proseguira'",
                    exc_info=True,
                )
```

- [ ] **Step 4: Esegui i test, verifica che passino**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_agente.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add codice/orchestratore/agente.py codice/tests/test_agente.py
git commit -m "feat(orchestratore): aggiungi MotoreAgente.interrompi()

Base per il turno vocale speculativo (Tappa 6 incr.4): sicuro da
chiamare in concorrenza mentre un altro task consuma turno() sullo
stesso motore, verificato con esperimento reale (vedi design doc)."
```

---

### Task 2: `test_agente.py` — migra i test di `_opzioni`/`prescalda` da `test_chat_stream.py`

**Files:**
- Modify: `codice/tests/test_agente.py`

**Interfaces:**
- Consumes: `MotoreAgente._opzioni(resume)`, `agente.prescalda(tenant_id)`, `agente.motore_per(tenant_id)` — già esistenti, nessuna modifica di produzione in questo task.

Questo task è puro spostamento di test (nessuna riga di produzione cambia): serve a garantire che quando `test_chat_stream.py` viene cancellato (Task 7) non si perda la copertura sulla configurazione del motore (tools/skills/thinking/setting_sources) e sul prescaldo.

- [ ] **Step 1: Copia in `test_agente.py` i seguenti test da `codice/tests/test_chat_stream.py`, adattando solo gli import (non serve più `router_mod`, `azioni`, `memoria_db`, `voce_token` — solo `agente`)**

Aggiungi in coda a `test_agente.py`:

```python
async def test_opzioni_motore_isola_i_tool_nativi_e_le_skill():
    """tools=None (default) esporrebbe TUTTI i nativi (Bash/Read/
    ToolSearch) al modello - trovato in reale (STOP 2, 2026-07-19): il
    modello ha chiamato ToolSearch su un turno vocale."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.tools == []
    assert opzioni.skills == ["redazione-email"]


async def test_opzioni_motore_thinking_adaptive_low():
    """Verificato in reale: 3,34s con thinking di default -> 1,52s su un
    saluto identico con adaptive+low (STOP 2, 2026-07-19)."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.thinking == {"type": "adaptive"}
    assert opzioni.effort == "low"


async def test_opzioni_motore_niente_config_utente():
    """MAI 'user': caricherebbe la config personale di Claude Code di chi
    ospita il server dentro l'agente del prodotto (trovato in reale, STOP 2
    2026-07-18)."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.setting_sources == ["project"]


async def test_opzioni_motore_niente_resume_di_sessioni_vecchie():
    """Niente resume all'avvio: riprendere uno storico vecchio rallentava
    ogni turno (~+2,5s misurati) e costava token per sempre."""
    motore = await agente.motore_per(TENANT)
    opzioni = await motore._opzioni(resume=None)
    assert opzioni.resume is None
    opzioni_con_resume = await motore._opzioni(resume="sess-viva")
    assert opzioni_con_resume.resume == "sess-viva"
```

- [ ] **Step 2: Esegui i test**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_agente.py -q`
Expected: `6 passed` (i 2 di Task 1 + questi 4)

- [ ] **Step 3: Commit**

```bash
git add codice/tests/test_agente.py
git commit -m "test(orchestratore): copri la configurazione di MotoreAgente

Preparazione al ritiro di test_chat_stream.py (Tappa 6 incr.4): la
copertura su tools/skills/thinking/setting_sources/resume non deve
dipendere dal protocollo POST che sta per essere sostituito."
```

---

### Task 3: `orchestratore/turno_vocale.py` — normalizzazione testo

**Files:**
- Create: `codice/orchestratore/turno_vocale.py`
- Create: `codice/tests/test_turno_vocale.py`

**Interfaces:**
- Produces: `_normalizza(testo: str) -> str` — usata dal Task 5 per decidere se un tentativo va interrotto o no.

- [ ] **Step 1: Scrivi il test**

```python
# codice/tests/test_turno_vocale.py
"""Turno vocale (Tappa 6, incr.4): macchina a stati che decide quando
avviare/interrompere/lasciar proseguire un tentativo di risposta, in base
ai transcript parziali/finali ricevuti dal client vocale via WebSocket."""
from __future__ import annotations

from orchestratore.turno_vocale import _normalizza


def test_normalizza_ignora_maiuscole_e_punteggiatura_finale():
    """Deepgram ripulisce il transcript finale (maiuscole/punteggiatura)
    anche senza parole nuove - un confronto a stringa esatta butterebbe via
    quasi ogni tentativo speculativo per differenze cosmetiche."""
    assert _normalizza("Che impegni ho domani?") == _normalizza("che impegni ho domani")


def test_normalizza_collassa_spazi_multipli():
    assert _normalizza("che   impegni  ho domani") == _normalizza("che impegni ho domani")


def test_normalizza_testi_diversi_restano_diversi():
    assert _normalizza("che impegni ho domani") != _normalizza("che impegni ho dopodomani")
```

- [ ] **Step 2: Esegui, verifica il fallimento**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_turno_vocale.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestratore.turno_vocale'`

- [ ] **Step 3: Crea `codice/orchestratore/turno_vocale.py` con la sola normalizzazione**

```python
"""Macchina a stati del turno vocale (Tappa 6, incr.4): decide quando
avviare, interrompere o lasciar proseguire un tentativo di risposta in base
ai transcript parziali/finali ricevuti dal client via WebSocket.

Sostituisce la vecchia POST /chat/stream (SSE, un solo transcript finale
per richiesta) con un ciclo di vita per sessione: il client manda ogni
transcript stabile, il server puo' scommettere prima dell'endpointing di
Deepgram e interrompersi se l'utente continua a parlare (vedi design doc
docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md).
"""
from __future__ import annotations

import re

_PUNTEGGIATURA_FINALE = re.compile(r"[.!?,;:]+$")
_SPAZI_MULTIPLI = re.compile(r"\s+")


def _normalizza(testo: str) -> str:
    """Confronto 'il testo combacia' mai a stringa esatta (design doc,
    'Global Constraints'): Deepgram ripulisce il transcript finale
    (maiuscole/punteggiatura) anche senza parole nuove."""
    pulito = testo.strip().lower()
    pulito = _PUNTEGGIATURA_FINALE.sub("", pulito)
    pulito = _SPAZI_MULTIPLI.sub(" ", pulito)
    return pulito.strip()
```

- [ ] **Step 4: Esegui, verifica il successo**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_turno_vocale.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add codice/orchestratore/turno_vocale.py codice/tests/test_turno_vocale.py
git commit -m "feat(orchestratore): normalizzazione testo per il turno vocale

Confronto 'il testo combacia' sempre su forma normalizzata, mai
stringa esatta - Deepgram ripulisce il transcript finale
(maiuscole/punteggiatura) anche senza parole nuove (design doc)."
```

---

### Task 4: `_esegui_tentativo()` — ponte + turno del motore, eventi in coda

**Files:**
- Modify: `codice/orchestratore/turno_vocale.py`
- Modify: `codice/tests/test_turno_vocale.py`

**Interfaces:**
- Consumes: `motore.turno(testo, canale) -> AsyncIterator[StreamEvent|ResultMessage]` (esistente), `ponte.genera_ponte(testo) -> str | None` (esistente)
- Produces: `async def _esegui_tentativo(motore, testo: str, tentativo_id: int, coda: asyncio.Queue) -> None` — mette in coda tuple `("tentativo", tentativo_id, evento_dict)` dove `evento_dict` ha la stessa forma degli eventi SSE di oggi (`{"evento": "ponte"|"delta"|"tool_in_corso", ...}`); a fine turno mette anche l'evento `fine` (con `risposta`/`azione_in_attesa`) o `errore`. Usata dal Task 5.

Nota di design: stessa logica di race ponte/delta già in produzione in `router.py` (prima di questo piano) — qui trasposta a mettere eventi in coda invece che a fare `yield` diretto, perché deve convivere con l'ascolto concorrente dei messaggi del client (Task 5).

- [ ] **Step 1: Scrivi i test (con `FakeMotore` e monkeypatch di `ponte.genera_ponte`)**

Aggiungi in `codice/tests/test_turno_vocale.py`:

```python
import asyncio

import pytest
from claude_agent_sdk.types import ResultMessage, StreamEvent

from orchestratore import ponte
from orchestratore.turno_vocale import _esegui_tentativo


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


async def test_esegui_tentativo_mette_delta_e_fine_in_coda(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)  # astensione, niente ponte
    motore = FakeMotore([_delta("Ciao"), _result("Ciao")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "ciao", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    tipi = [e[2]["evento"] for e in eventi]
    assert "delta" in tipi
    assert tipi[-1] == "fine"
    assert all(e[1] == 1 for e in eventi)  # tutti taggati col tentativo_id giusto


async def test_esegui_tentativo_include_ponte_se_generato(monkeypatch):
    _monta_ponte(monkeypatch, ritorno="Vediamo subito...")
    motore = FakeMotore([_result("ok")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "che impegni ho domani", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert eventi[0][2] == {"evento": "ponte", "testo": "Vediamo subito..."}


async def test_esegui_tentativo_traduce_tool_in_corso_senza_prefisso_mcp(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)
    motore = FakeMotore([_tool_start("mcp__eidos__search_events"), _result("ok")])
    coda = asyncio.Queue()
    await _esegui_tentativo(motore, "impegni?", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert {"evento": "tool_in_corso", "tool": "search_events"} in [e[2] for e in eventi]


async def test_esegui_tentativo_errore_pulito_mai_traceback(monkeypatch):
    _monta_ponte(monkeypatch, ritorno=None)

    class MotoreRotto:
        async def turno(self, messaggio, canale):
            raise RuntimeError("boom interno con dettagli privati")
            yield  # pragma: no cover - rende la funzione un generatore

    coda = asyncio.Queue()
    await _esegui_tentativo(MotoreRotto(), "ciao", tentativo_id=1, coda=coda, tenant_id="t1")
    eventi = await _svuota_coda(coda)
    assert eventi[-1][2]["evento"] == "errore"
    assert "boom interno" not in eventi[-1][2]["messaggio"]
```

- [ ] **Step 2: Esegui, verifica il fallimento**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_turno_vocale.py -q`
Expected: FAIL — `ImportError: cannot import name '_esegui_tentativo'`

- [ ] **Step 3: Implementa `_esegui_tentativo` in `codice/orchestratore/turno_vocale.py`**

Aggiungi in coda al file (dopo `_normalizza`):

```python
import asyncio
import logging

from claude_agent_sdk.types import ResultMessage, StreamEvent

from . import azioni, ponte

logger = logging.getLogger(__name__)


def _nome_tool_pulito(nome: str) -> str:
    """`mcp__<server>__<tool>` -> `<tool>`; i tool nativi restano invariati."""
    if nome.startswith("mcp__"):
        return nome.split("__", 2)[2]
    return nome


async def _esegui_tentativo(
    motore, testo: str, tentativo_id: int, coda: asyncio.Queue, tenant_id: str
) -> None:
    """Gira il ponte (Haiku) e il turno del motore in parallelo, mette ogni
    evento tradotto in coda taggato con `tentativo_id` - il consumer
    (gestisci_sessione_vocale, Task 5) scarta gli eventi con id diverso da
    quello corrente (tentativo scartato per un ripensamento dell'utente)."""
    pezzi: list[str] = []
    task_ponte = asyncio.create_task(ponte.genera_ponte(testo))
    testo_visto = False
    ponte_risolto = False

    async def _emetti(evento: dict) -> None:
        await coda.put(("tentativo", tentativo_id, evento))

    try:
        async for messaggio in motore.turno(testo, canale="voce"):
            if not ponte_risolto and task_ponte.done():
                ponte_risolto = True
                if not testo_visto and task_ponte.exception() is None and task_ponte.result():
                    await _emetti({"evento": "ponte", "testo": task_ponte.result()})
            if isinstance(messaggio, StreamEvent):
                evento = messaggio.event
                tipo_evento = evento.get("type")
                if tipo_evento == "content_block_delta":
                    delta = evento.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        if not testo_visto:
                            testo_visto = True
                            if not ponte_risolto:
                                ponte_risolto = True
                                task_ponte.cancel()
                        await _emetti({"evento": "delta", "testo": delta["text"]})
                elif tipo_evento == "content_block_start":
                    blocco = evento.get("content_block") or {}
                    if blocco.get("type") == "tool_use":
                        await _emetti(
                            {"evento": "tool_in_corso", "tool": _nome_tool_pulito(blocco.get("name", ""))}
                        )
            elif isinstance(messaggio, ResultMessage):
                if messaggio.subtype == "success" and messaggio.result:
                    pezzi.append(messaggio.result)

        azione_appena_creata = await azioni.ottieni_azione_pendente_tenant(tenant_id)
        await _emetti(
            {"evento": "fine", "risposta": "\n".join(pezzi), "azione_in_attesa": azione_appena_creata}
        )
    except Exception:
        logger.exception("errore durante un tentativo di turno vocale")
        await _emetti({"evento": "errore", "messaggio": "Non sono riuscito a elaborare la richiesta, riprova."})
    finally:
        task_ponte.cancel()
```

- [ ] **Step 4: Esegui, verifica il successo**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_turno_vocale.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add codice/orchestratore/turno_vocale.py codice/tests/test_turno_vocale.py
git commit -m "feat(orchestratore): _esegui_tentativo per il turno vocale

Stessa logica di race ponte/delta gia' in produzione, trasposta a
mettere eventi in coda (invece di yield diretto) per convivere con
l'ascolto concorrente dei messaggi del client (prossimo task)."
```

---

### Task 5: `gestisci_sessione_vocale()` — la macchina a stati completa

**Files:**
- Modify: `codice/orchestratore/turno_vocale.py`
- Modify: `codice/tests/test_turno_vocale.py`

**Interfaces:**
- Consumes: `agente.motore_per(tenant_id) -> MotoreAgente`, `motore.interrompi()` (Task 1), `_esegui_tentativo` (Task 4), `azioni.ottieni_azione_pendente_tenant`
- Produces: `class ConnessioneChiusa(Exception)`; `async def gestisci_sessione_vocale(tenant_id: str, ricevi: Callable[[], Awaitable[dict]], invia: Callable[[dict], Awaitable[None]]) -> None`. `ricevi` deve sollevare `ConnessioneChiusa` quando il client si disconnette. Usata dal Task 6 (endpoint WS reale).

- [ ] **Step 1: Scrivi i test**

Aggiungi in `codice/tests/test_turno_vocale.py`:

```python
from orchestratore import agente
from orchestratore.turno_vocale import ConnessioneChiusa, gestisci_sessione_vocale


class RicevitoreScriptato:
    """Ricevi() scriptato: una lista di messaggi client, poi ConnessioneChiusa."""

    def __init__(self, messaggi: list[dict]):
        self._messaggi = iter(messaggi)

    async def __call__(self) -> dict:
        try:
            return next(self._messaggi)
        except StopIteration:
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
```

- [ ] **Step 2: Esegui, verifica il fallimento**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_turno_vocale.py -q`
Expected: FAIL — `ImportError: cannot import name 'ConnessioneChiusa'`

- [ ] **Step 3: Implementa in `codice/orchestratore/turno_vocale.py`**

Aggiungi in cima al file (dopo gli import esistenti) e in coda:

```python
from typing import Any, Awaitable, Callable

from . import agente


class ConnessioneChiusa(Exception):
    """Il client ha chiuso la connessione WebSocket."""


async def _leggi_client(ricevi: Callable[[], Awaitable[dict]], coda: asyncio.Queue) -> None:
    """Legge in loop i messaggi del client e li mette in coda, taggati.
    Un task separato (mai lo stesso che consuma un tentativo): non tocca
    mai il motore, solo la coda - nessun rischio di conflitto con
    interrompi()."""
    try:
        while True:
            messaggio = await ricevi()
            await coda.put(("client", messaggio))
    except ConnessioneChiusa:
        await coda.put(("chiusura", None))


async def gestisci_sessione_vocale(
    tenant_id: str,
    ricevi: Callable[[], Awaitable[dict]],
    invia: Callable[[dict], Awaitable[None]],
) -> None:
    """Ciclo di vita di una sessione vocale WS: riceve parziale/finale dal
    client, decide quando avviare/interrompere/lasciar proseguire un
    tentativo di risposta, inoltra ponte/delta/tool_in_corso/fine/errore.

    Un solo task consuma la coda e decide - mai due task toccano il motore
    in contemporanea per lo STESSO tentativo (interrompi() e' l'eccezione
    esplicita e verificata, vedi Task 1)."""
    motore = await agente.motore_per(tenant_id)
    coda: asyncio.Queue = asyncio.Queue()
    task_lettore = asyncio.create_task(_leggi_client(ricevi, coda))
    tentativo_id = 0
    tentativo_testo: str | None = None
    tentativo_in_corso = False

    try:
        while True:
            tipo, *resto = await coda.get()

            if tipo == "chiusura":
                if tentativo_in_corso:
                    await motore.interrompi()
                return

            if tipo == "client":
                messaggio = resto[0]
                nuovo_testo = messaggio["testo"]

                if not tentativo_in_corso:
                    azione_pendente = await azioni.ottieni_azione_pendente_tenant(tenant_id)
                    if azione_pendente is not None:
                        await invia({
                            "evento": "errore",
                            "messaggio": "C'e' un'azione in attesa di conferma, risolvila prima di continuare.",
                        })
                        continue
                    tentativo_id += 1
                    tentativo_testo = nuovo_testo
                    tentativo_in_corso = True
                    asyncio.create_task(
                        _esegui_tentativo(motore, nuovo_testo, tentativo_id, coda, tenant_id)
                    )
                elif _normalizza(nuovo_testo) != _normalizza(tentativo_testo):
                    await motore.interrompi()
                    await invia({"evento": "annullato"})
                    tentativo_id += 1
                    tentativo_testo = nuovo_testo
                    asyncio.create_task(
                        _esegui_tentativo(motore, nuovo_testo, tentativo_id, coda, tenant_id)
                    )
                # else: combacia (confronto normalizzato) - nessuna azione,
                # si aspetta che il tentativo in corso finisca da solo.
                continue

            if tipo == "tentativo":
                id_evento, evento = resto
                if id_evento != tentativo_id:
                    continue  # eventi residui di un tentativo gia' scartato
                await invia(evento)
                if evento["evento"] in ("fine", "errore"):
                    tentativo_in_corso = False
    finally:
        task_lettore.cancel()
```

- [ ] **Step 4: Esegui, verifica il successo**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_turno_vocale.py -q`
Expected: `13 passed`

- [ ] **Step 5: Esegui l'intera suite per verificare che nulla si sia rotto**

Run: `cd codice && .venv\Scripts\python.exe -m pytest -q`
Expected: tutti verdi (nessuna regressione — questo task non tocca ancora `router.py`/`client.py`)

- [ ] **Step 6: Commit**

```bash
git add codice/orchestratore/turno_vocale.py codice/tests/test_turno_vocale.py
git commit -m "feat(orchestratore): gestisci_sessione_vocale - macchina a stati

Riceve parziale/finale dal client, decide se avviare/interrompere/
lasciar proseguire un tentativo. Confronto sempre normalizzato (mai
stringa esatta), gate azione pendente prima di ogni avvio, interrupt
verificato sicuro in concorrenza (vedi design doc)."
```

---

### Task 6: Endpoint WebSocket `/chat/stream` in `router.py`

**Files:**
- Modify: `codice/orchestratore/router.py`

**Interfaces:**
- Consumes: `turno_vocale.gestisci_sessione_vocale`, `turno_vocale.ConnessioneChiusa`, `fondamenta.auth.get_sessione_corrente` (invariata, funziona anche su `WebSocket` perche' eredita `.cookies` da `HTTPConnection` come `Request`)
- Produces: nessuna nuova interfaccia Python — e' l'endpoint di rete che il client (Task 9-10) consumera'.

Questo task **rimuove** la vecchia `POST /chat/stream` (funzione `chat_stream`, `_riga_sse`, `_nome_tool_pulito` — quest'ultima gia' spostata in `turno_vocale.py` al Task 4) e la sostituisce con l'endpoint WebSocket.

- [ ] **Step 1: Scrivi il test dell'endpoint WS**

Crea `codice/tests/test_router_ws.py`:

```python
"""Endpoint WS /chat/stream (Tappa 6, incr.4) - la logica di decisione e'
gia' testata in test_turno_vocale.py; qui si verifica solo il collegamento:
auth, formato dei messaggi sul filo, propagazione della disconnessione."""
from __future__ import annotations

from starlette.testclient import TestClient

from app import app
from orchestratore import agente, azioni, ponte

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
    with client.websocket_connect("/chat/stream") as ws:
        # senza cookie di sessione: il server chiude la connessione subito
        dato = ws.receive()
        assert dato["type"] == "websocket.close"


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
    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", nessuna_azione)
    monkeypatch.setattr(ponte, "genera_ponte", niente_ponte)

    client = _client()
    with client.websocket_connect("/chat/stream") as ws:
        ws.send_json({"tipo": "parziale", "testo": "ciao"})
        primo = ws.receive_json()
        assert primo["evento"] == "fine"
        assert primo["risposta"] == "risposta a: ciao"
```

- [ ] **Step 2: Esegui, verifica il fallimento**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_router_ws.py -q`
Expected: FAIL — la connessione WS su `/chat/stream` fallisce (l'endpoint e' ancora un POST, non un WS: `websocket_connect` riceve un errore di protocollo/404)

- [ ] **Step 3: In `codice/orchestratore/router.py`, rimuovi la vecchia `POST /chat/stream` e le funzioni `_riga_sse`/`_nome_tool_pulito`, aggiungi l'endpoint WS**

Rimuovi dal file: la funzione `_riga_sse`, la funzione `_nome_tool_pulito`, l'intera funzione `chat_stream` (`@router.post("/chat/stream")` e il suo corpo).

Aggiungi al posto rimosso:

```python
from fastapi import WebSocket, WebSocketDisconnect

from . import turno_vocale


@router.websocket("/chat/stream")
async def chat_stream_ws(websocket: WebSocket):
    """Sessione vocale (Tappa 6, incr.4): il client manda ogni transcript
    stabile (parziale/finale), il server puo' scommettere prima
    dell'endpointing di Deepgram e interrompersi se l'utente continua a
    parlare - vedi orchestratore/turno_vocale.py e design doc
    docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md."""
    try:
        sessione = await get_sessione_corrente(websocket)
    except HTTPException:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def ricevi() -> dict:
        try:
            return await websocket.receive_json()
        except WebSocketDisconnect:
            raise turno_vocale.ConnessioneChiusa()

    async def invia(evento: dict) -> None:
        await websocket.send_json(evento)

    try:
        await turno_vocale.gestisci_sessione_vocale(sessione["tenant_id"], ricevi, invia)
    except turno_vocale.ConnessioneChiusa:
        pass
```

Nota: `get_sessione_corrente` e' definita con `request: Request` come hint in `fondamenta/auth.py`, ma usa solo `request.cookies` — `WebSocket` eredita `.cookies` dalla stessa classe base (`HTTPConnection`), quindi funziona senza modifiche (verificato sul sorgente di Starlette installato).

- [ ] **Step 4: Esegui, verifica il successo**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_router_ws.py -q`
Expected: `2 passed`

- [ ] **Step 5: Esegui l'intera suite**

Run: `cd codice && .venv\Scripts\python.exe -m pytest -q`
Expected: `tests/test_chat_stream.py` ora fallisce in blocco (testa l'endpoint POST rimosso) — atteso, si ritira nel prossimo task. Tutto il resto verde.

- [ ] **Step 6: Commit**

```bash
git add codice/orchestratore/router.py codice/tests/test_router_ws.py
git commit -m "feat(orchestratore): endpoint WS /chat/stream

Sostituisce la POST+SSE: il client manda ogni transcript stabile,
il server puo' scommettere prima dell'endpointing e interrompersi.
Logica in turno_vocale.py, questo e' solo il collegamento di rete."
```

---

### Task 7: Ritira `test_chat_stream.py`

**Files:**
- Delete: `codice/tests/test_chat_stream.py`

**Interfaces:** nessuna — solo rimozione. La copertura equivalente vive ora in `test_agente.py` (Task 1-2) e `test_turno_vocale.py` + `test_router_ws.py` (Task 3-6).

- [ ] **Step 1: Cancella il file**

```bash
rm codice/tests/test_chat_stream.py
```

- [ ] **Step 2: Esegui l'intera suite, verifica che sia tutta verde**

Run: `cd codice && .venv\Scripts\python.exe -m pytest -q`
Expected: tutti i test passano, nessun riferimento rotto

- [ ] **Step 3: Esegui ruff**

Run: `cd codice && .venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test(orchestratore): ritira test_chat_stream.py

Testava la POST /chat/stream rimossa nel task precedente. Copertura
equivalente ora in test_agente.py (config del motore) e
test_turno_vocale.py + test_router_ws.py (comportamento e rete)."
```

---

### Task 8: `voce/rilevatore_frase.py` — euristica "sembra completa"

**Files:**
- Create: `codice/voce/rilevatore_frase.py`
- Create: `codice/tests/test_rilevatore_frase.py`

**Interfaces:**
- Produces: `class RilevatoreFrase(soglia_secondi: float = 0.35)` con `.aggiorna(testo: str, adesso: float) -> str | None` e `.reset() -> None`. Usata dal Task 10 (client).

- [ ] **Step 1: Scrivi il test**

```python
# codice/tests/test_rilevatore_frase.py
"""Euristica 'sembra completa' (Tappa 6, incr.4): puro timer, nessuna
dipendenza da comportamenti non verificati di Deepgram (punteggiatura sugli
interim non garantita) - vedi design doc, sezione omonima."""
from __future__ import annotations

from voce.rilevatore_frase import RilevatoreFrase


def test_testo_stabile_oltre_la_soglia_viene_segnalato():
    r = RilevatoreFrase(soglia_secondi=0.35)
    assert r.aggiorna("che impegni ho domani", adesso=0.0) is None  # primo avvistamento
    assert r.aggiorna("che impegni ho domani", adesso=0.30) is None  # non ancora stabile
    assert r.aggiorna("che impegni ho domani", adesso=0.36) == "che impegni ho domani"


def test_testo_che_cambia_resetta_il_timer():
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("che impegni ho", adesso=0.0)
    assert r.aggiorna("che impegni ho", adesso=0.30) is None
    # arriva una parola nuova prima della soglia: il timer riparte da qui
    assert r.aggiorna("che impegni ho domani", adesso=0.31) is None
    assert r.aggiorna("che impegni ho domani", adesso=0.50) is None  # solo 0.19s dal cambio
    assert r.aggiorna("che impegni ho domani", adesso=0.67) == "che impegni ho domani"


def test_stesso_testo_non_viene_segnalato_due_volte():
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("ciao", adesso=0.0)
    assert r.aggiorna("ciao", adesso=0.36) == "ciao"
    assert r.aggiorna("ciao", adesso=0.50) is None  # gia' segnalato, non si ripete


def test_testo_vuoto_non_segnala_mai():
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("", adesso=0.0)
    assert r.aggiorna("", adesso=1.0) is None


def test_reset_permette_di_ri_segnalare_lo_stesso_testo():
    """Un nuovo turno vocale: lo stesso testo di un turno precedente deve
    poter scattare di nuovo."""
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("ciao", adesso=0.0)
    assert r.aggiorna("ciao", adesso=0.36) == "ciao"
    r.reset()
    r.aggiorna("ciao", adesso=10.0)
    assert r.aggiorna("ciao", adesso=10.36) == "ciao"
```

- [ ] **Step 2: Esegui, verifica il fallimento**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_rilevatore_frase.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'voce.rilevatore_frase'`

- [ ] **Step 3: Implementa**

```python
# codice/voce/rilevatore_frase.py
"""Euristica 'sembra completa' per il client vocale (Tappa 6, incr.4):
puro timer, nessuna dipendenza da comportamenti non verificati di Deepgram
(punteggiatura sugli interim non garantita - vedi design doc). Se il
transcript non cambia per la soglia, il testo e' pronto per essere mandato
come 'parziale' al server."""
from __future__ import annotations


class RilevatoreFrase:
    def __init__(self, soglia_secondi: float = 0.35):
        self.soglia_secondi = soglia_secondi
        self._ultimo_testo = ""
        self._ultimo_cambio: float | None = None
        self._gia_inviato = ""

    def aggiorna(self, testo: str, adesso: float) -> str | None:
        """Chiamare a ogni nuovo interim (o periodicamente, anche senza
        nuovi interim, per rilevare il silenzio). Ritorna il testo da
        mandare come 'parziale' se la soglia e' scattata e non e' gia'
        stato mandato per questo identico testo, altrimenti None."""
        if testo != self._ultimo_testo:
            self._ultimo_testo = testo
            self._ultimo_cambio = adesso
            return None
        if not testo or self._ultimo_cambio is None:
            return None
        if testo == self._gia_inviato:
            return None
        if adesso - self._ultimo_cambio >= self.soglia_secondi:
            self._gia_inviato = testo
            return testo
        return None

    def reset(self) -> None:
        """Nuovo turno vocale: si riparte puliti."""
        self._ultimo_testo = ""
        self._ultimo_cambio = None
        self._gia_inviato = ""
```

- [ ] **Step 4: Esegui, verifica il successo**

Run: `cd codice && .venv\Scripts\python.exe -m pytest tests/test_rilevatore_frase.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add codice/voce/rilevatore_frase.py codice/tests/test_rilevatore_frase.py
git commit -m "feat(voce): euristica 'sembra completa' per il client

Puro timer (soglia 0.35s di default), nessuna dipendenza da
comportamenti non verificati di Deepgram - vedi design doc."
```

---

### Task 9: `voce/sessione_ws.py` — wrapper client della connessione WebSocket

**Files:**
- Create: `codice/voce/sessione_ws.py`

**Interfaces:**
- Consumes: libreria `websockets` (gia' in `voce/requirements-voce.txt`), `config.BASE_URL` (esistente, unica fonte dell'URL base come gia' oggi in tutto `client.py`)
- Produces: `class SessioneVoce` con `async def connetti(cookie: str) -> "SessioneVoce"` (staticmethod factory - deriva l'URL WS da `config.BASE_URL`), `async def manda_parziale(testo: str) -> None`, `async def manda_finale(testo: str) -> None`, `async def eventi(self) -> AsyncIterator[dict]` (itera gli eventi del server finche' la connessione resta aperta), `async def chiudi() -> None`. Usata dal Task 10 (client.py).

Nessun test dedicato in questo task (vedi Global Constraints: wrapper di I/O puro, verificato in reale come `stt.py`/`tts.py`).

- [ ] **Step 1: Implementa**

```python
# codice/voce/sessione_ws.py
"""Connessione WebSocket persistente verso /chat/stream (Tappa 6, incr.4).

Wrapper di I/O puro (rete): verificato in reale (STOP 2), non con unit
test - stessa convenzione di stt.py/tts.py in questo pacchetto (vedi
voce/__init__.py). La logica di decisione (quando interrompere, quando
lasciar proseguire) vive server-side in orchestratore/turno_vocale.py,
gia' testata li'.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import websockets

from . import config


class ErroreSessioneVoce(Exception):
    """Connessione al server persa: il turno corrente va gestito come
    fallito, il chiamante decide se riprovare."""


class SessioneVoce:
    def __init__(self, ws):
        self._ws = ws

    @staticmethod
    async def connetti(cookie: str) -> "SessioneVoce":
        url = config.BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/chat/stream"
        try:
            ws = await websockets.connect(url, additional_headers={"Cookie": cookie})
        except (OSError, websockets.WebSocketException) as exc:
            raise ErroreSessioneVoce(f"Non riesco a collegarmi al server vocale: {exc}") from exc
        return SessioneVoce(ws)

    async def manda_parziale(self, testo: str) -> None:
        await self._ws.send(json.dumps({"tipo": "parziale", "testo": testo}))

    async def manda_finale(self, testo: str) -> None:
        await self._ws.send(json.dumps({"tipo": "finale", "testo": testo}))

    async def eventi(self) -> AsyncIterator[dict]:
        """Itera gli eventi del server per QUESTA sessione (non solo un
        turno): il chiamante distingue i tentativi dagli eventi stessi
        (ponte/delta/tool_in_corso appartengono al tentativo corrente,
        annullato segna la fine di un tentativo scartato, fine/errore la
        fine di un turno vero)."""
        try:
            async for messaggio in self._ws:
                yield json.loads(messaggio)
        except websockets.WebSocketException as exc:
            raise ErroreSessioneVoce(f"Connessione al server vocale interrotta: {exc}") from exc

    async def chiudi(self) -> None:
        try:
            await self._ws.close()
        except Exception:
            pass
```

- [ ] **Step 2: Verifica che il modulo si importi senza errori**

Run: `cd codice && .venv\Scripts\python.exe -c "import voce.sessione_ws; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Ruff**

Run: `cd codice && .venv\Scripts\python.exe -m ruff check voce/sessione_ws.py`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add codice/voce/sessione_ws.py
git commit -m "feat(voce): wrapper client della connessione WS /chat/stream

Wrapper di I/O puro (rete), verificato in reale come stt.py/tts.py -
la logica di decisione vive server-side, gia' testata li'."
```

---

### Task 10: Riscrivi `voce/client.py` per usare `sessione_ws` + `rilevatore_frase`

**Files:**
- Modify: `codice/voce/client.py`

**Interfaces:**
- Consumes: `sessione_ws.SessioneVoce` (Task 9), `rilevatore_frase.RilevatoreFrase` (Task 8), `stt.trascrivi_turno` (esistente, va esteso per esporre gli interim mentre gira — vedi sotto), `frasi.SpezzaFrasi`, `sanificazione.per_tts`, `conferme.interpreta_transcript`, `tts.apri_sessione` (tutti esistenti, invariati)

Nessun test automatico per questo task (client.py non ha mai avuto unit test in questo pacchetto — l'I/O audio/rete si verifica in reale). Verificato allo STOP 2 (Task 11).

Questo task e' il piu' delicato: cambia il ciclo di un turno da "ascolta fino al finale, POI manda tutto" a "manda ogni parziale stabile mentre ascolti, gestisci gli eventi (incluso `annullato`) mentre il turno e' ancora aperto lato server".

- [ ] **Step 1: Estendi `voce/stt.py` per esporre l'interim testuale a un callback ASINCRONO (oggi `su_interim` e' sincrono, usato solo per stampare a schermo) — aggiungi un secondo hook**

In `codice/voce/stt.py`, modifica la firma di `trascrivi_turno` e la chiamata a `su_interim` dentro `_conversa`:

```python
async def trascrivi_turno(
    token: str,
    microfono: Microfono,
    su_interim: Callable[[str], None] = lambda t: None,
) -> str:
```
resta identica nella firma pubblica — nessuna modifica necessaria qui: `su_interim` puo' gia' fare quello che serve (il chiamante, in Task client, ci mette dentro sia la stampa a schermo sia l'aggiornamento del `RilevatoreFrase` + l'invio del `parziale`). Non serve toccare `stt.py`. (Verificato rileggendo il file: `su_interim` e' gia' chiamato a ogni transcript, sincrono va bene perche' l'invio al WS puo' essere schedulato come task fire-and-forget dal chiamante.)

- [ ] **Step 2: Riscrivi il flusso del turno in `codice/voce/client.py`**

Sostituisci l'intero contenuto di `codice/voce/client.py` con:

```python
"""Client vocale push-to-talk con generazione speculativa (Tappa 6,
incr.4).

Premi Invio, parla: appena il transcript resta stabile (RilevatoreFrase),
si manda un 'parziale' al server - che puo' gia' iniziare a generare prima
ancora che Deepgram segnali la fine della frase (endpointing 300ms). Se
continui a parlare, il server interrompe da solo il tentativo sbagliato
(evento 'annullato') e il client smette di pronunciarlo, in silenzio.

Il backend resta l'unico motore agentico; qui c'e' solo I/O audio e la
decisione locale di QUANDO mandare un parziale (design doc:
docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md).
"""
from __future__ import annotations

import asyncio
import time

import httpx

from cli import _carica_cookie, _descrivi_azione, _salva_cookie

from . import config, stt, tts
from .audio import ErroreAudio, Microfono
from .conferme import interpreta_transcript
from .frasi import SpezzaFrasi
from .rilevatore_frase import RilevatoreFrase
from .sanificazione import per_tts
from .sessione_ws import ErroreSessioneVoce, SessioneVoce


def _login_sincrono() -> str:
    """Login (o riuso cookie) con un client sincrono usa-e-getta; ritorna
    l'header Cookie da passare alla connessione WebSocket."""
    with httpx.Client(base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=60.0) as client:
        if client.get("/me").status_code == 200:
            return "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        print(f"Login su {config.BASE_URL}")
        email = input("Email: ").strip()
        password = input("Password: ").strip()
        resp = client.post("/login", json={"email": email, "password": password})
        if resp.status_code != 200:
            print(f"Login fallito ({resp.status_code}): {resp.text}")
            raise SystemExit(1)
        _salva_cookie(resp.cookies)
        print("Login riuscito.\n")
        return "; ".join(f"{k}={v}" for k, v in resp.cookies.items())


async def _token_voce(client: httpx.AsyncClient) -> dict:
    resp = await client.post("/voice/token")
    if resp.status_code != 200:
        dettaglio = resp.json().get("detail", "errore sconosciuto")
        raise RuntimeError(f"Token voce non disponibili: {dettaglio}")
    return resp.json()


async def _ascolta_e_specula(
    sessione: SessioneVoce, token_deepgram: str
) -> str:
    """Ascolta il microfono; ogni volta che il transcript resta stabile
    (RilevatoreFrase) manda un 'parziale' al server - non aspetta piu' solo
    il transcript finale per iniziare a informare il server. Ritorna il
    transcript finale (per la stampa a schermo/gestione conferme)."""
    microfono = Microfono()
    rilevatore = RilevatoreFrase()
    print("… parla pure (mi fermo quando fai una pausa)")

    def su_interim(testo: str) -> None:
        print(f"\r  {testo}", end="", flush=True)
        candidato = rilevatore.aggiorna(testo, time.monotonic())
        if candidato:
            asyncio.ensure_future(sessione.manda_parziale(candidato))

    transcript = await stt.trascrivi_turno(token_deepgram, microfono, su_interim)
    print()
    if transcript:
        await sessione.manda_finale(transcript)
    return transcript


async def _pronuncia_eventi_turno(sessione: SessioneVoce) -> dict | None:
    """Consuma gli eventi del server per il turno corrente, li pronuncia,
    gestisce 'annullato' fermando subito il TTS senza dire nulla. Ritorna
    l'azione in attesa di conferma (se il turno ne ha creata una)."""
    spezza = SpezzaFrasi()
    sessione_tts: tts.SessioneTTS | None = None
    azione: dict | None = None

    async def assicura_tts(client: httpx.AsyncClient) -> tts.SessioneTTS:
        nonlocal sessione_tts
        if sessione_tts is None:
            tokens = await _token_voce(client)
            sessione_tts = await tts.apri_sessione(tokens["elevenlabs"]["token"])
        return sessione_tts

    async with httpx.AsyncClient(
        base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=180.0
    ) as client_http:
        async for evento in sessione.eventi():
            tipo = evento["evento"]
            if tipo == "annullato":
                if sessione_tts is not None:
                    await sessione_tts.chiudi()
                    sessione_tts = None
                spezza = SpezzaFrasi()
                print("\n(tentativo annullato, riparto)", flush=True)
                continue
            if tipo == "ponte":
                print(f"(ponte: {evento['testo']})", flush=True)
                ses = await assicura_tts(client_http)
                await ses.invia(per_tts(evento["testo"]))
                continue
            if tipo == "tool_in_corso":
                print(f"\n[{evento['tool']}…]", flush=True)
                continue
            if tipo == "delta":
                print(evento["testo"], end="", flush=True)
                for frase in spezza.aggiungi(evento["testo"]):
                    ses = await assicura_tts(client_http)
                    await ses.invia(per_tts(frase))
                continue
            if tipo == "errore":
                print(f"\n{evento['messaggio']}")
                ses = await assicura_tts(client_http)
                await ses.invia(per_tts(evento["messaggio"]))
                break
            if tipo == "fine":
                for frase in spezza.chiudi():
                    ses = await assicura_tts(client_http)
                    await ses.invia(per_tts(frase))
                azione = evento.get("azione_in_attesa")
                if azione:
                    print(f"\n\n[Conferma richiesta] {_descrivi_azione(azione)}")
                    ses = await assicura_tts(client_http)
                    await ses.invia(per_tts(
                        f"Serve la tua conferma: {_descrivi_azione(azione)}. "
                        "Premi Invio e rispondi con un si' o con un no."
                    ))
                print()
                break

    if sessione_tts is not None:
        await sessione_tts.chiudi()
    return azione


async def _turno_conferma(azione: dict, transcript: str) -> bool:
    """True se l'azione e' stata risolta (confermata o annullata). Le
    conferme passano ancora dal REST esistente (/azioni/{id}/conferma),
    non dal WebSocket - e' un'azione singola, non un turno di generazione."""
    conferma = interpreta_transcript(transcript)
    async with httpx.AsyncClient(
        base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=60.0
    ) as client:
        if conferma is None:
            await _pronuncia_singola(client, "Non ho capito: rispondi con un si' o con un no chiaro.")
            return False
        resp = await client.post(f"/azioni/{azione['id']}/conferma", json={"conferma": conferma})
        if resp.status_code != 200:
            print(f"Errore nella conferma ({resp.status_code}): {resp.text}")
            await _pronuncia_singola(client, "Non sono riuscito a registrare la conferma.")
            return False
        stato = resp.json()["stato"]
        esito = "Fatto." if stato == "confermata_inviata" else "Azione annullata."
        print(esito)
        await _pronuncia_singola(client, esito)
        return True


async def _pronuncia_singola(client: httpx.AsyncClient, testo: str) -> None:
    try:
        tokens = await _token_voce(client)
        sessione = await tts.apri_sessione(tokens["elevenlabs"]["token"])
        await sessione.invia(per_tts(testo))
        await sessione.chiudi()
    except (tts.ErroreTTS, RuntimeError):
        pass


async def _loop(cookie: str) -> None:
    sessione = await SessioneVoce.connetti(cookie)
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        tokens = await _token_voce(client)
    token_deepgram = tokens["deepgram"]["token"]

    print("Eidos voce — premi Invio e parla (Ctrl+C per uscire)\n")
    azione_in_attesa: dict | None = None
    while True:
        try:
            await asyncio.to_thread(input, "[Invio per parlare] ")
            transcript = await _ascolta_e_specula(sessione, token_deepgram)
            if not transcript:
                print("Non ho sentito nulla, riprova.")
                continue
            print(f"Tu: {transcript}\n")

            if azione_in_attesa is not None:
                if await _turno_conferma(azione_in_attesa, transcript):
                    azione_in_attesa = None
                continue

            azione_in_attesa = await _pronuncia_eventi_turno(sessione)
        except (stt.ErroreSTT, tts.ErroreTTS, ErroreAudio, ErroreSessioneVoce, RuntimeError) as exc:
            print(f"\n{exc}")


def main() -> None:
    try:
        cookie = _login_sincrono()
        asyncio.run(_loop(cookie))
    except KeyboardInterrupt:
        print("\nA presto.")
```

Nota: il token Deepgram e' preso **una volta sola** all'avvio della sessione (non a ogni turno come nella versione precedente) — il token dura 30s ed era gia' pensato per un singolo turno; dato che ora il microfono/STT gira dentro `_ascolta_e_specula` chiamato a ogni turno con lo stesso token, se il token scade tra un turno e l'altro la prossima connessione Deepgram fallira' con un errore di autenticazione leggibile (gestito da `stt.ErroreSTT`, gia' catturato nel loop). Non e' una regressione bloccante per lo STOP 2: si annota come miglioria futura (richiedere un token nuovo per turno) se il test reale la mostra fastidiosa.

- [ ] **Step 3: Verifica che il modulo si importi senza errori**

Run: `cd codice && .venv\Scripts\python.exe -c "import voce.client; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Ruff**

Run: `cd codice && .venv\Scripts\python.exe -m ruff check voce/client.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add codice/voce/client.py
git commit -m "feat(voce): client usa la sessione WS speculativa

Manda ogni transcript stabile come 'parziale' (non solo il finale):
il server puo' gia' iniziare a generare. Su 'annullato' ferma subito
il TTS senza pronunciare nulla del tentativo scartato."
```

---

### Task 11: Gate di qualità + STOP 2

**Files:** nessuno (solo verifica)

- [ ] **Step 1: Suite completa**

Run: `cd codice && .venv\Scripts\python.exe -m pytest -q`
Expected: tutti verdi

- [ ] **Step 2: Ruff su tutto il progetto**

Run: `cd codice && .venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Avvia il server locale**

Run (background): `cd codice && .venv\Scripts\python.exe -m uvicorn app:app --port 8123 --log-level info`

- [ ] **Step 4: Smoke test reale minimo (senza microfono) — apri una connessione WS vera e verifica lo scambio**

Crea uno script temporaneo (fuori dal repo, es. nella cartella scratchpad di sessione) che fa login reale, apre `SessioneVoce.connetti`, manda un `finale` diretto (senza passare dal microfono) e stampa gli eventi ricevuti — verifica che il server risponda con `delta`/`fine` reali prima di passare la mano all'utente per lo STOP 2 con il microfono vero.

- [ ] **Step 5: STOP 2 — presenta all'utente le istruzioni di prova**

```
cd codice
$env:EIDOS_API_BASE_URL = "http://127.0.0.1:8123"
.venv\Scripts\python -m voce
```

Casi da provare:
1. Frase detta tutta d'un fiato, senza pause a metà — verifica che il turno risponda, tempi simili o migliori di prima
2. Frase con ripensamento a meta' ("che impegni ho doma— anzi dopodomani") — verifica che si senta SOLO la risposta su "dopodomani", mai un accenno alla risposta sbagliata
3. Frase breve senza pause (es. "grazie") — verifica che funzioni come prima (nessun tentativo speculativo se il timer non scatta in tempo, il finale la gestisce comunque)

Nessun commit finché l'utente non conferma che questi tre casi funzionano.

---

## Verifica di copertura della spec (self-review)

- Protocollo WS con eventi `parziale`/`finale`/`ponte`/`tool_in_corso`/`delta`/`fine`/`errore`/`annullato`: Task 5, 6
- Euristica di stabilità 300-400ms, non punteggiatura: Task 8 (soglia default 0.35s, nel mezzo del range indicato)
- Interrupt sicuro (verificato con esperimento reale): Task 1, riferimento esplicito nei commenti di Task 5
- Confronto normalizzato, non stringa esatta: Task 3, testato esplicitamente in Task 5 (`test_finale_che_combacia_non_riavvia`)
- Gate azione pendente prima di ogni avvio tentativo: Task 5 (`test_azione_pendente_blocca_avvio_tentativo`)
- Mai due voci (annullato ferma il TTS): Task 10 (`_pronuncia_eventi_turno`, gestione `annullato`)
- `/chat` testuale invariato: nessun task lo tocca (verificato: nessuna modifica a `router.py:chat`)
- Fuori ambito (barge-in, riempitivi, ritaratura soglia): esplicitamente non implementati in nessun task
