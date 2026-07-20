"""Euristica 'sembra completa' (Tappa 6, incr.4): puro timer, nessuna
dipendenza da comportamenti non verificati di Deepgram (punteggiatura sugli
interim non garantita) - vedi design doc, sezione omonima."""
from __future__ import annotations

from voce.rilevatore_frase import RilevatoreFrase


def test_testo_stabile_oltre_la_soglia_viene_segnalato():
    r = RilevatoreFrase(soglia_secondi=0.35)
    assert r.aggiorna("che impegni ho domani", adesso=0.0) is None  # primo avvistamento
    assert r.aggiorna("che impegni ho domani", adesso=0.30) is None  # non ancora stabile
    assert r.aggiorna("che impegni ho domani", adesso=0.36) == "che impegni ho domani"


def test_testo_che_cambia_resetta_il_timer():
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("che impegni ho", adesso=0.0)
    assert r.aggiorna("che impegni ho", adesso=0.30) is None
    # arriva una parola nuova prima della soglia: il timer riparte da qui
    assert r.aggiorna("che impegni ho domani", adesso=0.31) is None
    assert r.aggiorna("che impegni ho domani", adesso=0.50) is None  # solo 0.19s dal cambio
    assert r.aggiorna("che impegni ho domani", adesso=0.67) == "che impegni ho domani"


def test_stesso_testo_non_viene_segnalato_due_volte():
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("ciao", adesso=0.0)
    assert r.aggiorna("ciao", adesso=0.36) == "ciao"
    assert r.aggiorna("ciao", adesso=0.50) is None  # gia' segnalato, non si ripete


def test_testo_vuoto_non_segnala_mai():
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("", adesso=0.0)
    assert r.aggiorna("", adesso=1.0) is None


def test_reset_permette_di_ri_segnalare_lo_stesso_testo():
    """Un nuovo turno vocale: lo stesso testo di un turno precedente deve
    poter scattare di nuovo."""
    r = RilevatoreFrase(soglia_secondi=0.35)
    r.aggiorna("ciao", adesso=0.0)
    assert r.aggiorna("ciao", adesso=0.36) == "ciao"
    r.reset()
    r.aggiorna("ciao", adesso=10.0)
    assert r.aggiorna("ciao", adesso=10.36) == "ciao"
