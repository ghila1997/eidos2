import time

import pytest

from orchestratore import oauth

TENANT = "11111111-1111-1111-1111-111111111111"


def test_state_roundtrip_valido():
    state = oauth.genera_state(TENANT)
    assert oauth.verifica_state(state) == TENANT


def test_state_manomesso_viene_rifiutato():
    state = oauth.genera_state(TENANT)
    manomesso = state[:-4] + "xxxx"
    with pytest.raises(oauth.StatoNonValido):
        oauth.verifica_state(manomesso)


def test_state_scaduto_viene_rifiutato(monkeypatch):
    state = oauth.genera_state(TENANT)
    tempo_originale = time.time()
    # Sposta l'orologio oltre la finestra massima (10 minuti).
    monkeypatch.setattr(time, "time", lambda: tempo_originale + 700)
    with pytest.raises(oauth.StatoNonValido):
        oauth.verifica_state(state)


def test_cifratura_refresh_token_roundtrip():
    segreto = "refresh-token-vero-di-google"
    cifrato = oauth.cifra_refresh_token(segreto)
    assert cifrato != segreto
    assert oauth.decifra_refresh_token(cifrato) == segreto
