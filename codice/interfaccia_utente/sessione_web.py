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

logger = logging.getLogger(__name__)

# In 7.1 il gate di conferma visivo (scheda Si'/No) e' ancora Tappa 7.2:
# qui un'azione gia' in attesa blocca il turno con un messaggio leggibile,
# senza crash e senza confermare nulla di implicito (stesso gate del turno
# vocale, stesso principio CLAUDE.md - un solo punto di autorizzazione).
MESSAGGIO_AZIONE_PENDENTE = (
    "C'e' un'azione in attesa di conferma, risolvila prima di continuare."
)


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

        azione_pendente = await azioni.ottieni_azione_pendente_tenant(tenant_id)
        if azione_pendente is not None:
            await invia({"evento": "errore", "messaggio": MESSAGGIO_AZIONE_PENDENTE})
            continue

        try:
            async for evento in streaming.traduci_turno(
                motore, testo, canale="testo", tenant_id=tenant_id
            ):
                await invia(evento)
        except Exception:
            logger.exception("errore durante un turno web")
            await invia({"evento": "errore", "messaggio": streaming.MESSAGGIO_ERRORE})
