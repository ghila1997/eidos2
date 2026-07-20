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
