"""Spezzatura a frasi dei delta di testo (Tappa 6, incremento 2).

Il TTS riceve frasi complete, mai pezzi a metà: la prima frase parte in
sintesi mentre il modello genera le successive. Trappole da design (STOP 1):
abbreviazioni e numeri con punto non devono troncare la frase.
"""
from __future__ import annotations

from voce.frasi import SpezzaFrasi


def _tutte(spezza: SpezzaFrasi, testo: str, a_pezzi: int = 3) -> list[str]:
    """Alimenta il testo a chunk piccoli (come i delta reali) e chiude."""
    frasi = []
    for i in range(0, len(testo), a_pezzi):
        frasi.extend(spezza.aggiungi(testo[i : i + a_pezzi]))
    frasi.extend(spezza.chiudi())
    return frasi


def test_frase_completa_esce_appena_finita():
    spezza = SpezzaFrasi()
    uscite = spezza.aggiungi("Ciao, ci sono. Dimmi ")
    assert uscite == ["Ciao, ci sono."]
    assert spezza.chiudi() == ["Dimmi"]


def test_niente_pezzi_a_meta():
    spezza = SpezzaFrasi()
    assert spezza.aggiungi("Il meeting è alle") == []
    assert spezza.aggiungi(" 15.") == []  # troppo corta da sola? no: frase intera
    # la frase esce solo quando il confine è certo (punto + spazio o chiusura)
    assert spezza.chiudi() == ["Il meeting è alle 15."]


def test_abbreviazioni_e_numeri_non_troncano():
    spezza = SpezzaFrasi()
    frasi = _tutte(spezza, "Vedi l'art. 5 del contratto. Il totale è 3.14 euro. Fine.")
    assert frasi == ["Vedi l'art. 5 del contratto.", "Il totale è 3.14 euro.", "Fine."]


def test_punto_esclamativo_interrogativo_e_due_punti():
    spezza = SpezzaFrasi()
    frasi = _tutte(spezza, "Perfettamente chiaro! Vuoi che proceda? Ecco il piano: prima la mail.")
    # ! e ? sono confini; i due punti NO (pausa breve, spezzare lì suona male)
    assert frasi == ["Perfettamente chiaro!", "Vuoi che proceda?", "Ecco il piano: prima la mail."]


def test_frasi_troppo_corte_si_accorpano():
    """'Ok. Fatto. Ecco cosa ho trovato.' non deve produrre tre chiamate TTS
    da una parola: sotto la lunghezza minima si accorpa alla successiva."""
    spezza = SpezzaFrasi(lunghezza_minima=10)
    frasi = _tutte(spezza, "Ok. Fatto. Ecco cosa ho trovato nelle mail.")
    assert frasi[0].startswith("Ok. Fatto.")
    assert "".join(f + " " for f in frasi).strip() == "Ok. Fatto. Ecco cosa ho trovato nelle mail."


def test_chiudi_svuota_anche_senza_punteggiatura_finale():
    spezza = SpezzaFrasi()
    spezza.aggiungi("Risposta senza punto finale")
    assert spezza.chiudi() == ["Risposta senza punto finale"]
    assert spezza.chiudi() == []
