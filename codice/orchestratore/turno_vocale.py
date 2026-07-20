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

from claude_agent_sdk.types import ResultMessage, StreamEvent

from . import azioni, ponte

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

        # Dopo che il motore finisce, controlla se il ponte è pronto e non è stato ancora inviato.
        # Se il ponte non è ancora finito (es. il modello ha risposto velocemente),
        # attendiamo un attimo per dargli una chance di completare.
        if not ponte_risolto and not task_ponte.done():
            try:
                await asyncio.wait_for(task_ponte, timeout=0.1)
            except asyncio.TimeoutError:
                pass

        if not ponte_risolto and task_ponte.done():
            ponte_risolto = True
            if not testo_visto and task_ponte.exception() is None and task_ponte.result():
                await _emetti({"evento": "ponte", "testo": task_ponte.result()})

        azione_appena_creata = await azioni.ottieni_azione_pendente_tenant(tenant_id)
        await _emetti(
            {"evento": "fine", "risposta": "\n".join(pezzi), "azione_in_attesa": azione_appena_creata}
        )
    except Exception:
        logger.exception("errore durante un tentativo di turno vocale")
        await _emetti({"evento": "errore", "messaggio": "Non sono riuscito a elaborare la richiesta, riprova."})
    finally:
        task_ponte.cancel()
