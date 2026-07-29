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

import logging
from typing import Awaitable, Callable

from orchestratore import agente, azioni, conversazione, streaming
from orchestratore.descrizioni_azioni import descrivi_azione

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
    un evento errore). Ritorna quando il client chiude la connessione."""
    motore = await agente.motore_per(tenant_id)

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

        # Se c'è già un'azione da confermare, non si avvia un nuovo turno: si
        # rimanda al client la **scheda** di quell'azione (Tappa 7.2), non un
        # errore rosso. `azione_bloccante` scarta da sola una pendente scaduta
        # (TTL pigra), così una scheda dimenticata non blocca la chat.
        azione_pendente = await azioni.azione_bloccante(tenant_id)
        if azione_pendente is not None:
            azione_pendente["descrizione"] = descrivi_azione(azione_pendente)
            await invia({"evento": "azione_in_attesa", "azione": azione_pendente})
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
                    passo = {"etichetta": evento.get("etichetta") or evento.get("tool") or "", "esito": "ok"}
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
