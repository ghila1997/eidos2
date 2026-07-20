"""Turno vocale (Tappa 6, incr.4): macchina a stati che decide quando
avviare/interrompere/lasciar proseguire un tentativo di risposta, in base
ai transcript parziali/finali ricevuti dal client vocale via WebSocket."""
from __future__ import annotations

from orchestratore.turno_vocale import _normalizza


def test_normalizza_ignora_maiuscole_e_punteggiatura_finale():
    """Deepgram ripulisce il transcript finale (maiuscole/punteggiatura)
    anche senza parole nuove - un confronto a stringa esatta butterebbe via
    quasi ogni tentativo speculativo per differenze cosmetiche."""
    assert _normalizza("Che impegni ho domani?") == _normalizza("che impegni ho domani")


def test_normalizza_collassa_spazi_multipli():
    assert _normalizza("che   impegni  ho domani") == _normalizza("che impegni ho domani")


def test_normalizza_testi_diversi_restano_diversi():
    assert _normalizza("che impegni ho domani") != _normalizza("che impegni ho dopodomani")
