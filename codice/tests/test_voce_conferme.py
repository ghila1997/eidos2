"""Conferme vocali (Tappa 6): il transcript passa per lo stesso elenco chiuso
e deterministico del CLI — mai un'interpretazione del modello, mai default a
sì. smart_format produce maiuscole e punteggiatura ("Sì." "Confermo!")."""
from __future__ import annotations

from voce.conferme import interpreta_transcript


def test_si_con_punteggiatura_smart_format():
    assert interpreta_transcript("Sì.") is True
    assert interpreta_transcript("Confermo!") is True
    assert interpreta_transcript("VAI") is True


def test_no_con_punteggiatura():
    assert interpreta_transcript("No.") is False
    assert interpreta_transcript("Annulla, grazie") is None  # parole extra: non riconosciuta
    assert interpreta_transcript("Fermati") is False


def test_frase_ambigua_non_riconosciuta():
    assert interpreta_transcript("mah, forse sì, non so") is None
    assert interpreta_transcript("") is None
    assert interpreta_transcript("manda pure la mail") is None  # mai interpretare
