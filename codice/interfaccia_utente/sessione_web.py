"""Sessione web (Tappa 7.1): ciclo di vita di una connessione WebSocket
`/ws/session` che esegue un turno di **solo testo** alla volta.

Piu' semplice del turno vocale (`orchestratore/turno_vocale.py`): niente
ponte, niente speculativo, niente transcript parziali - quella e' semantica
vocale che DECISIONS.md 2026-07-28 (pt.3) dice esplicitamente di non
trascinare nella UI testuale. Ogni messaggio del client e' un turno intero,
servito fino in fondo prima di leggere il successivo; il canale resta poi
vivo per il turno dopo. La traduzione turno->eventi e' condivisa con la voce
(`orchestratore/streaming.py`).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from orchestratore import agente, azioni, canali, conversazione, streaming
from orchestratore.descrizioni_azioni import descrivi_gruppo

logger = logging.getLogger(__name__)


class ConnessioneChiusa(Exception):
    """Il client ha chiuso la connessione WebSocket. Vocabolario di questo
    modulo (non di FastAPI): il router converte WebSocketDisconnect in
    questa, cosi' il ciclo resta testabile senza un vero WebSocket."""




async def gestisci_sessione(
    tenant_id: str,
    ricevi: Callable[[], Awaitable[dict]],
    invia: Callable[[dict], Awaitable[None]],
) -> None:
    """Legge messaggi `{"tipo": "messaggio", "testo": ...}` dal client e per
    ognuno esegue un turno di testo, inoltrando delta/tool_in_corso/fine (o
    un evento errore). Ritorna quando il client chiude la connessione.

    Il canale resta registrato per tutta la durata (vedi `annuncia`): serve a
    ricevere anche gli eventi che non nascono da un messaggio del client,
    come l'avanzamento di un gruppo di azioni confermate."""
    motore = await agente.motore_per(tenant_id)
    # Un lock per canale: durante l'esecuzione di un gruppo due scrittori
    # (questo ciclo e `annuncia`) possono voler scrivere insieme sullo stesso
    # WebSocket, e due send_json interlacciati corrompono il frame.
    #
    # `invia_grezzo` tiene la funzione originale sotto un nome DIVERSO: la
    # closure cattura la variabile, non il valore - riassegnando `invia` a
    # questo wrapper, dentro si richiamerebbe da solo e resterebbe fermo sul
    # proprio lock, che non e' rientrante. Ogni sessione web bloccata per
    # sempre; preso dai test, mai arrivato al browser.
    lock_invio = asyncio.Lock()
    invia_grezzo = invia

    async def invia_serializzato(evento: dict) -> None:
        async with lock_invio:
            await invia_grezzo(evento)

    canali.registra(tenant_id, invia_serializzato)
    try:
        await _cicla_sessione(tenant_id, motore, ricevi, invia_serializzato)
        logger.info("sessione web chiusa dal client (tenant %s)", tenant_id)
    except Exception:
        # Perche' una sessione muore non era visibile da nessuna parte, e una
        # sessione morta significa niente esiti, niente risposte: sembra tutto
        # vivo e non arriva piu' niente.
        logger.exception("sessione web terminata da un errore (tenant %s)", tenant_id)
        raise
    finally:
        canali.deregistra(tenant_id, invia_serializzato)


async def _cicla_sessione(
    tenant_id: str,
    motore,
    ricevi: Callable[[], Awaitable[dict]],
    invia: Callable[[dict], Awaitable[None]],
) -> None:

    # Cronologia all'apertura (Tappa 7.3): il record della conversazione
    # sopravvive al refresh. Primo evento del canale, prima di leggere qualunque
    # messaggio; il client lo usa per popolare la cronologia espandibile. Se la
    # lettura fallisce (DB giu', tabella non migrata) si degrada a cronologia
    # vuota: la chat e' piu' importante di uno storico, non deve morire.
    try:
        messaggi = await conversazione.get_messaggi(tenant_id)
    except Exception:
        logger.exception("lettura cronologia fallita, si procede senza storico")
        messaggi = []
    await invia({
        "evento": "storico",
        "messaggi": [
            {"ruolo": m["ruolo"], "contenuto": m["contenuto"], "passi": m.get("passi")}
            for m in messaggi
        ],
    })

    while True:
        try:
            messaggio = await ricevi()
        except ConnessioneChiusa:
            return

        testo = (messaggio or {}).get("testo", "").strip()
        if not testo:
            continue

        # Se c'è già qualcosa da confermare, non si avvia un nuovo turno: si
        # rimanda al client la **scheda** di quelle azioni (Tappa 7.2), non un
        # errore rosso. `azioni_bloccanti` scarta da sole le pendenti scadute
        # (TTL pigra), così una scheda dimenticata non blocca la chat.
        pendenti = await azioni.azioni_bloccanti(tenant_id)
        if pendenti:
            await invia({
                "evento": "azione_in_attesa",
                "azione": {"azioni": pendenti, "descrizione": descrivi_gruppo(pendenti)},
            })
            continue

        try:
            risposta = ""
            passi: list[dict] = []
            passo_per_id: dict[str, dict] = {}
            async for evento in streaming.traduci_turno(
                motore, testo, canale="testo", tenant_id=tenant_id
            ):
                tipo = evento.get("evento")
                if tipo == "tool_in_corso":
                    # Le "cose fatte in mezzo" al turno: si raccolgono in ordine
                    # e si salvano col messaggio assistente (mostrate a richiesta
                    # nella cronologia, viste dal vivo nella superficie ambient).
                    # Chiamate uguali di fila diventano UNA voce col contatore:
                    # 30 "Preparo il cestinamento" identici in cronologia sono
                    # una cascata, non un resoconto.
                    # `quante` compare solo da 2 in su: una chiamata singola -
                    # il caso normale - resta una voce identica a prima.
                    etichetta = evento.get("etichetta") or evento.get("tool") or ""
                    if passi and passi[-1]["etichetta"] == etichetta:
                        passi[-1]["quante"] = passi[-1].get("quante", 1) + 1
                        passo_per_id[evento.get("id")] = passi[-1]
                    else:
                        passo = {"etichetta": etichetta, "esito": "ok"}
                        passi.append(passo)
                        passo_per_id[evento.get("id")] = passo
                elif tipo == "tool_finito":
                    p = passo_per_id.get(evento.get("id"))
                    if p is not None:
                        p["esito"] = evento.get("esito", "ok")
                elif tipo == "fine":
                    risposta = evento.get("risposta", "")
                await invia(evento)
        except Exception:
            logger.exception("errore durante un turno web")
            await invia({"evento": "errore", "messaggio": streaming.MESSAGGIO_ERRORE})
            continue

        # Turno riuscito: si persiste in cronologia (Tappa 7.3). Fallire qui
        # non deve rompere il canale ne' far comparire un errore su un turno
        # gia' andato a buon fine: si logga e si prosegue.
        try:
            await conversazione.salva_turno(tenant_id, testo, risposta, passi)
        except Exception:
            logger.exception("salvataggio turno in cronologia fallito")
