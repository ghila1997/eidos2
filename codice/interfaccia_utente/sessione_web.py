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

from orchestratore import agente, azioni, streaming
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
            async for evento in streaming.traduci_turno(
                motore, testo, canale="testo", tenant_id=tenant_id
            ):
                await invia(evento)
        except Exception:
            logger.exception("errore durante un turno web")
            await invia({"evento": "errore", "messaggio": streaming.MESSAGGIO_ERRORE})
