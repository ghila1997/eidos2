"""System prompt e prefisso turno del motore agente (vedi anche
playbook/system-prompt-agenti.md)."""
from datetime import datetime, timezone

from orchestratore.agente import _costruisci_system_prompt, _prefisso_turno


def test_prefisso_turno_include_data_corrente():
    """Trappola reale (2026-07-15): senza la data corrente il modello
    indovina 'oggi' sbagliando. Col motore persistente il system prompt è
    fisso alla connessione: la data vive nel prefisso di OGNI turno."""
    anno_corrente = str(datetime.now(timezone.utc).year)
    prefisso = _prefisso_turno("testo")
    assert "[adesso:" in prefisso
    assert anno_corrente in prefisso
    assert "[canale: testo]" in prefisso


def test_system_prompt_spiega_i_canali():
    """Un solo motore serve voce e testo: il prompt spiega il prefisso
    [canale: ...] e lo stile da ascolto (apertura contestuale prima dei
    tool, niente elenchi — trovato a STOP 2 Tappa 6)."""
    prompt = _costruisci_system_prompt({})
    assert "<canali>" in prompt
    assert "[canale: voce]" in prompt
    assert "[adesso:" in prompt  # spiega che la data arriva nel prefisso


def test_system_prompt_vieta_presa_in_carico_doppia_in_voce():
    """Trappola reale (STOP 2, 2026-07-18): il ponte pronuncia la presa in
    carico E il modello apriva con la sua ('Controllo il calendario...') —
    doppione in cuffia. Il prompt ora vieta l'apertura di attesa in voce."""
    prompt = _costruisci_system_prompt({})
    assert "NON aprire con frasi di presa in carico" in prompt


def test_system_prompt_vieta_doppia_conferma_ridondante():
    """Trappola reale (2026-07-15/16): il modello chiedeva 'confermi?' in
    linguaggio naturale prima del tool, oltre al gate strutturale vero."""
    prompt = _costruisci_system_prompt({})
    assert "non chiedere prima 'confermi?'" in prompt


def test_system_prompt_include_preferenze_se_presenti():
    prompt = _costruisci_system_prompt({"tono": "diretto"})
    assert "tono: diretto" in prompt
