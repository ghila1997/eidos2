"""Trappola trovata testando Tappa 4 a mano: _mostra_conferma assumeva
payload sempre di forma Gmail (destinatario/oggetto/corpo) e andava in
KeyError su un'azione pending di tipo Calendar (titolo/event_id/...)."""
from cli import _descrivi_azione


def test_descrivi_azione_send_email():
    azione = {"tipo": "send_email", "payload": {"destinatario": "x@example.com", "oggetto": "Ciao", "corpo": "Testo"}}
    assert "x@example.com" in _descrivi_azione(azione)
    assert "Ciao" in _descrivi_azione(azione)


def test_descrivi_azione_create_event_con_partecipanti():
    azione = {
        "tipo": "create_event",
        "payload": {
            "titolo": "Riunione", "inizio": "2026-07-20T10:00:00Z", "fine": "2026-07-20T11:00:00Z",
            "partecipanti": ["cliente@example.com"],
        },
    }
    descrizione = _descrivi_azione(azione)
    assert "Riunione" in descrizione
    assert "cliente@example.com" in descrizione


def test_descrivi_azione_delete_event_non_solleva_keyerror():
    """Trappola esatta trovata a mano: payload senza 'oggetto'/'corpo' non
    deve più far esplodere la funzione."""
    azione = {"tipo": "delete_event", "payload": {"event_id": "evt-1", "notifica": True, "calendario": None}}
    assert "evt-1" in _descrivi_azione(azione)


def test_descrivi_azione_tipo_sconosciuto_non_esplode():
    azione = {"tipo": "qualcosa_di_nuovo", "payload": {"x": 1}}
    assert "qualcosa_di_nuovo" in _descrivi_azione(azione)
