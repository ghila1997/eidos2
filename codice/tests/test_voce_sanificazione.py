"""Sanificazione del testo per il TTS (Tappa 6): il testo pronunciato può
divergere da quello mostrato — markdown, emoji e formattazione non si leggono
ad alta voce (spec §5)."""
from __future__ import annotations

from voce.sanificazione import per_tts


def test_rimuove_markdown_inline():
    assert per_tts("Il **totale** è `42` euro, *molto* bene") == "Il totale è 42 euro, molto bene"


def test_link_markdown_resta_solo_il_testo():
    assert per_tts("Vedi [la fattura](https://drive.google.com/abc) allegata") == "Vedi la fattura allegata"


def test_rimuove_emoji():
    assert per_tts("Fatto! ✅ Tutto ok 🎉") == "Fatto! Tutto ok"


def test_intestazioni_e_liste_diventano_frasi():
    testo = "## Riepilogo\n- prima cosa\n- seconda cosa"
    assert per_tts(testo) == "Riepilogo. prima cosa. seconda cosa"


def test_testo_semplice_resta_intatto():
    assert per_tts("Domani alle 15 hai il meeting con Marco.") == "Domani alle 15 hai il meeting con Marco."
