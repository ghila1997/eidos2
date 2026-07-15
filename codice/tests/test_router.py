"""Trappola reale trovata testando a mano (2026-07-15): il system prompt
non passava mai la data corrente al modello, che la indovinava sbagliando."""
from datetime import datetime, timezone

from orchestratore.router import _costruisci_system_prompt


def test_system_prompt_include_data_corrente():
    anno_corrente = str(datetime.now(timezone.utc).year)
    prompt = _costruisci_system_prompt({})
    assert anno_corrente in prompt
    assert "Data e ora attuali" in prompt


def test_system_prompt_vieta_doppia_conferma_ridondante():
    """Trappola reale trovata testando a mano (2026-07-15/16): il modello
    chiedeva 'confermi?' in linguaggio naturale prima di chiamare il tool,
    oltre al gate strutturale vero - due conferme per un'unica azione."""
    prompt = _costruisci_system_prompt({})
    assert "non chiedere prima 'confermi?'" in prompt


def test_system_prompt_include_preferenze_se_presenti():
    prompt = _costruisci_system_prompt({"tono": "diretto"})
    assert "tono: diretto" in prompt
