"""Spezzatura a frasi dei delta di testo per il TTS in streaming.

La prima frase va in sintesi mentre il modello genera le successive
(spec Tappa 6, §5): qui si decide dove finisce una frase. Regole:
- confine = . ! ? seguito da spazio (o dalla chiusura dello stream);
- un punto tra cifre (3.14) o dopo un'abbreviazione nota (art., dott.)
  non è un confine;
- frasi sotto la lunghezza minima si accorpano alla successiva per non
  fare chiamate TTS da una parola ("Ok." "Fatto.").
"""
from __future__ import annotations

import re

_CONFINE = re.compile(r"[.!?]")

_ABBREVIAZIONI = {
    "art", "artt", "avv", "dott", "dr", "ecc", "es", "ing", "n", "pag",
    "prof", "sig", "sigg", "tel", "vs",
}


class SpezzaFrasi:
    def __init__(self, lunghezza_minima: int = 10):
        self.lunghezza_minima = lunghezza_minima
        self._buffer = ""
        self._in_attesa = ""  # frasi troppo corte, accorpate alla prossima

    def aggiungi(self, testo: str) -> list[str]:
        """Aggiunge un delta e restituisce le frasi complete pronte per il TTS."""
        self._buffer += testo
        pronte: list[str] = []
        while (confine := self._trova_confine()) is not None:
            frase = self._buffer[:confine].strip()
            self._buffer = self._buffer[confine:].lstrip()
            candidata = f"{self._in_attesa} {frase}".strip()
            if len(candidata) >= self.lunghezza_minima:
                pronte.append(candidata)
                self._in_attesa = ""
            else:
                self._in_attesa = candidata
        return pronte

    def chiudi(self) -> list[str]:
        """Fine dello stream: svuota quello che resta, anche senza punteggiatura."""
        resto = f"{self._in_attesa} {self._buffer}".strip()
        self._buffer = ""
        self._in_attesa = ""
        return [resto] if resto else []

    def _trova_confine(self) -> int | None:
        for match in _CONFINE.finditer(self._buffer):
            fine = match.end()
            # confine certo solo se seguito da spazio: a fine buffer il testo
            # potrebbe continuare col prossimo delta (es. "15." poi "5 euro")
            if fine >= len(self._buffer) or not self._buffer[fine].isspace():
                continue
            if match.group() == ".":
                parola_prima = re.search(r"(\w+)\.$", self._buffer[:fine])
                if parola_prima and parola_prima.group(1).lower() in _ABBREVIAZIONI:
                    continue
            return fine
        return None
