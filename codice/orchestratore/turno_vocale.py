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

import asyncio
import logging
import re
from typing import Awaitable, Callable

from . import agente, azioni, ponte, streaming

logger = logging.getLogger(__name__)

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


async def _esegui_tentativo(
    motore, testo: str, tentativo_id: int, coda: asyncio.Queue, tenant_id: str
) -> None:
    """Gira il ponte (Haiku) e il turno del motore in parallelo, mette ogni
    evento tradotto in coda taggato con `tentativo_id` - il consumer
    (gestisci_sessione_vocale, Task 5) scarta gli eventi con id diverso da
    quello corrente (tentativo scartato per un ripensamento dell'utente).

    La traduzione turno->eventi vive in `streaming.traduci_turno` (condivisa
    con la sessione web); qui sopra restano solo il ponte vocale e la sua
    cancellazione al primo testo reale del modello."""
    task_ponte = asyncio.create_task(ponte.genera_ponte(testo))
    testo_visto = False
    ponte_risolto = False

    async def _emetti(evento: dict) -> None:
        await coda.put(("tentativo", tentativo_id, evento))

    try:
        async for evento in streaming.traduci_turno(motore, testo, canale="voce", tenant_id=tenant_id):
            if not ponte_risolto and task_ponte.done():
                ponte_risolto = True
                if not testo_visto and task_ponte.exception() is None and task_ponte.result():
                    await _emetti({"evento": "ponte", "testo": task_ponte.result()})
            if evento["evento"] == "delta" and not testo_visto:
                testo_visto = True
                if not ponte_risolto:
                    ponte_risolto = True
                    task_ponte.cancel()
            await _emetti(evento)
    except Exception:
        logger.exception("errore durante un tentativo di turno vocale")
        await _emetti({"evento": "errore", "messaggio": streaming.MESSAGGIO_ERRORE})
    finally:
        task_ponte.cancel()


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
                    pendenti = await azioni.ottieni_azioni_pendenti_tenant(tenant_id)
                    if pendenti:
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
                    # Stesso gate del ramo di primo avvio (vedi sopra), non
                    # un'eccezione per il riavvio: un tool del tentativo in
                    # corso puo' aver gia' creato un'azione pending (via
                    # Safety Supervisor -> ask_user) prima che l'utente
                    # ripensasse le parole - se e' cosi', il tentativo in
                    # corso resta intatto (mai interrotto/riavviato) finche'
                    # quell'azione non e' risolta, altrimenti un secondo
                    # tentativo partirebbe libero con un'azione non
                    # confermata gia' nel DB (CLAUDE.md, gate unico, nessuna
                    # eccezione per casi che "sembrano" a basso rischio).
                    pendenti = await azioni.ottieni_azioni_pendenti_tenant(tenant_id)
                    if pendenti:
                        await invia({
                            "evento": "errore",
                            "messaggio": "C'e' un'azione in attesa di conferma, risolvila prima di continuare.",
                        })
                        continue
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
