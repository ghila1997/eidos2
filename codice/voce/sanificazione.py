"""Sanificazione del testo per il TTS: quello che si pronuncia non è quello
che si mostra (spec Tappa 6, §5). Markdown, emoji e struttura visiva via;
tra intestazioni e voci di lista si inserisce un punto (pausa), senza
aggiungere punteggiatura in coda al testo."""
from __future__ import annotations

import re

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_INLINE = re.compile(r"[*_`#]+")
_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001fbff"  # emoji, simboli, pittogrammi
    "☀-➿"          # simboli vari e dingbat
    "️‍"           # variation selector, zero-width joiner
    "]+"
)


def per_tts(testo: str) -> str:
    testo = _LINK.sub(r"\1", testo)
    testo = _EMOJI.sub("", testo)
    righe = []
    for riga in testo.splitlines():
        riga = re.sub(r"^[-*•]\s+", "", riga.strip())  # voce di lista
        riga = _INLINE.sub("", riga)
        riga = re.sub(r"\s{2,}", " ", riga).strip()
        if riga:
            righe.append(riga)
    if not righe:
        return ""
    # pausa tra le righe: punto solo dove manca già una punteggiatura
    unite = []
    for riga in righe[:-1]:
        unite.append(riga if riga[-1] in ".!?:,;" else riga + ".")
    unite.append(righe[-1])
    return " ".join(unite)
