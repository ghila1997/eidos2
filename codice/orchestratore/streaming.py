"""Traduzione condivisa: messaggi SDK di un turno del motore -> eventi UI.

Un solo posto per la mappa `StreamEvent`/`ResultMessage` -> eventi
(`delta`/`tool_in_corso`/`fine`), riusata da chi consuma un turno in
streaming: il turno vocale (`turno_vocale.py`, che ci monta sopra
ponte + speculativo) e la sessione web (`interfaccia_utente/sessione_web.py`,
che la usa nuda). Regola CLAUDE.md "ogni informazione vive in un punto solo":
la forma degli eventi non va duplicata tra i due canali.

Questa funzione NON cattura le eccezioni del motore né decide il testo di un
evento `errore`: il ciclo di vita (loggare, tradurre in `errore`, chiudere)
resta del chiamante, che ha il proprio contesto. Il testo dell'errore è però
qui (`MESSAGGIO_ERRORE`), così i due canali mostrano lo stesso messaggio.
"""
from __future__ import annotations

from typing import AsyncIterator

from claude_agent_sdk.types import ResultMessage, StreamEvent

from . import azioni

MESSAGGIO_ERRORE = "Non sono riuscito a elaborare la richiesta, riprova."


def nome_tool_pulito(nome: str) -> str:
    """`mcp__<server>__<tool>` -> `<tool>`; i tool nativi restano invariati."""
    if nome.startswith("mcp__"):
        return nome.split("__", 2)[2]
    return nome


async def traduci_turno(
    motore, testo: str, canale: str, tenant_id: str
) -> AsyncIterator[dict]:
    """Consuma `motore.turno(testo, canale)` e produce eventi UI man mano:

    - `{"evento": "delta", "testo": ...}` per ogni frammento di testo;
    - `{"evento": "tool_in_corso", "tool": ...}` quando parte un tool;
    - un solo `{"evento": "fine", "risposta": ..., "azione_in_attesa": ...}`
      alla fine, con l'eventuale azione pending appena creata da un tool.

    Un'eccezione del motore si propaga al chiamante (non tradotta qui)."""
    pezzi: list[str] = []
    async for messaggio in motore.turno(testo, canale=canale):
        if isinstance(messaggio, StreamEvent):
            evento = messaggio.event
            tipo_evento = evento.get("type")
            if tipo_evento == "content_block_delta":
                delta = evento.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"evento": "delta", "testo": delta["text"]}
            elif tipo_evento == "content_block_start":
                blocco = evento.get("content_block") or {}
                if blocco.get("type") == "tool_use":
                    yield {"evento": "tool_in_corso", "tool": nome_tool_pulito(blocco.get("name", ""))}
        elif isinstance(messaggio, ResultMessage):
            if messaggio.subtype == "success" and messaggio.result:
                pezzi.append(messaggio.result)

    azione_appena_creata = await azioni.ottieni_azione_pendente_tenant(tenant_id)
    yield {"evento": "fine", "risposta": "\n".join(pezzi), "azione_in_attesa": azione_appena_creata}
