"""Riempitivi vocali (Tappa 6, deciso a STOP 1): mai silenzio non segnalato
durante un tool lungo, ma anche mai un riempitivo per ogni tool di una catena,
e mai sopra l'audio della risposta."""
from __future__ import annotations

from voce.riempitivi import GestoreRiempitivi


def test_primo_tool_produce_riempitivo_pertinente():
    g = GestoreRiempitivi()
    frase = g.su_tool("search_memoria")
    assert frase is not None
    assert "controllo" in frase.lower() or "cerc" in frase.lower()


def test_un_solo_riempitivo_per_finestra_di_silenzio():
    g = GestoreRiempitivi()
    assert g.su_tool("search_memoria") is not None
    assert g.su_tool("search_events") is None  # catena di tool, niente spam


def test_dopo_audio_di_risposta_i_tool_non_parlano():
    g = GestoreRiempitivi()
    g.su_audio_risposta()  # la risposta sta già suonando
    assert g.su_tool("search_memoria") is None


def test_nuovo_turno_riarma_il_riempitivo():
    g = GestoreRiempitivi()
    g.su_tool("search_memoria")
    g.nuovo_turno()
    assert g.su_tool("draft_email") is not None


def test_attesa_lunga_produce_secondo_riempitivo_una_volta_sola():
    g = GestoreRiempitivi()
    g.su_tool("search_memoria")
    assert g.su_attesa_lunga() is not None  # "ancora un momento..."
    assert g.su_attesa_lunga() is None


def test_categoria_mail_ha_frase_dedicata():
    g = GestoreRiempitivi()
    frase = g.su_tool("draft_email")
    assert "mail" in frase.lower() or "scrivo" in frase.lower() or "preparo" in frase.lower()
