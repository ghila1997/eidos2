"""Euristica 'sembra completa' per il client vocale (Tappa 6, incr.4):
puro timer, nessuna dipendenza da comportamenti non verificati di Deepgram
(punteggiatura sugli interim non garantita - vedi design doc). Se il
transcript non cambia per la soglia, il testo e' pronto per essere mandato
come 'parziale' al server."""
from __future__ import annotations


class RilevatoreFrase:
    def __init__(self, soglia_secondi: float = 0.35):
        self.soglia_secondi = soglia_secondi
        self._ultimo_testo = ""
        self._ultimo_cambio: float | None = None
        self._gia_inviato = ""

    def aggiorna(self, testo: str, adesso: float) -> str | None:
        """Chiamare a ogni nuovo interim (o periodicamente, anche senza
        nuovi interim, per rilevare il silenzio). Ritorna il testo da
        mandare come 'parziale' se la soglia e' scattata e non e' gia'
        stato mandato per questo identico testo, altrimenti None."""
        if testo != self._ultimo_testo:
            self._ultimo_testo = testo
            self._ultimo_cambio = adesso
            return None
        if not testo or self._ultimo_cambio is None:
            return None
        if testo == self._gia_inviato:
            return None
        if adesso - self._ultimo_cambio >= self.soglia_secondi:
            self._gia_inviato = testo
            return testo
        return None

    def reset(self) -> None:
        """Nuovo turno vocale: si riparte puliti."""
        self._ultimo_testo = ""
        self._ultimo_cambio = None
        self._gia_inviato = ""
