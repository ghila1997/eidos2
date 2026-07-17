"""Conferme vocali: stesso elenco chiuso e deterministico del CLI (unica
fonte: cli.py), con la sola normalizzazione della punteggiatura che
smart_format aggiunge al transcript ("Sì." "Confermo!"). Parole extra =
non riconosciuta: si richiede, mai default a sì, mai interpretazione
del modello (principio del gate, CLAUDE.md)."""
from __future__ import annotations

from cli import _interpreta_risposta


def interpreta_transcript(testo: str) -> bool | None:
    normalizzato = testo.strip().strip(".,!?;:").strip()
    return _interpreta_risposta(normalizzato)
