"""Il CLI non ricalcola più la descrizione dell'azione (Tappa 7.2): la
formatta a partire dalla `descrizione` che il server allega, fonte unica per
CLI e web. Qui si costruisce quella descrizione con la funzione vera del
server, così i due restano allineati per costruzione."""
import json

import httpx

import cli
from cli import _descrivi_azione, _interpreta_risposta
from orchestratore.descrizioni_azioni import descrivi_azione


def _azione(tipo: str, payload: dict) -> dict:
    """Un'azione come la manda il server: tipo/payload + descrizione allegata."""
    az = {"tipo": tipo, "payload": payload}
    az["descrizione"] = descrivi_azione(az)
    return az


def test_descrivi_azione_send_email():
    azione = _azione("send_email", {"destinatario": "x@example.com", "oggetto": "Ciao", "corpo": "Testo"})
    reso = _descrivi_azione(azione)
    assert "x@example.com" in reso
    assert "Ciao" in reso
    assert "Testo" in reso


def test_descrivi_azione_create_event_con_partecipanti():
    azione = _azione("create_event", {
        "titolo": "Riunione", "inizio": "2026-07-20T10:00:00Z", "fine": "2026-07-20T11:00:00Z",
        "partecipanti": ["cliente@example.com"]})
    reso = _descrivi_azione(azione)
    assert "Riunione" in reso
    assert "cliente@example.com" in reso


def test_descrivi_azione_delete_event_non_solleva_keyerror():
    """Trappola storica (Tappa 4): payload senza 'oggetto'/'corpo' non deve
    far esplodere la formattazione."""
    azione = _azione("delete_event", {"event_id": "evt-1", "notifica": True, "calendario": None})
    assert "evt-1" in _descrivi_azione(azione)


def test_descrivi_azione_propose_commitment():
    azione = _azione("propose_commitment", {
        "entity_nome": "Isagro", "descrizione": "Restituire pagamento doppio fattura 725FE",
        "direzione": "nostro"})
    reso = _descrivi_azione(azione)
    assert "Isagro" in reso
    assert "Restituire pagamento doppio fattura 725FE" in reso
    assert "{" not in reso
    assert "azione di tipo" not in reso


def test_descrivi_azione_close_commitment():
    azione = _azione("close_commitment", {"impegno_id": "impegno-1", "motivo": "bonifico restituito il 22/07"})
    reso = _descrivi_azione(azione)
    assert "impegno-1" in reso
    assert "bonifico restituito il 22/07" in reso
    assert "{" not in reso


def test_descrivi_azione_senza_descrizione_fallback_minimale():
    """Difesa: un server vecchio che non allega descrizione non deve rompere
    il CLI - fallback su una riga col tipo."""
    reso = _descrivi_azione({"tipo": "qualcosa_di_nuovo", "payload": {"x": 1}})
    assert "qualcosa_di_nuovo" in reso


def test_interpreta_risposta_affermative():
    for testo in ("y", "si", "Sì", "CONFERMO", "vai", " ok ", "Autorizzo"):
        assert _interpreta_risposta(testo) is True


def test_interpreta_risposta_negative():
    for testo in ("n", "No", "annulla", "FERMATI", "stop"):
        assert _interpreta_risposta(testo) is False


def test_interpreta_risposta_non_riconosciuta_ritorna_none():
    """Trappola: una frase ambigua non deve mai essere interpretata a caso
    come sì o no - il chiamante deve richiedere di nuovo, mai indovinare."""
    assert _interpreta_risposta("forse") is None
    assert _interpreta_risposta("") is None
    assert _interpreta_risposta("ciao Eidos") is None


def test_login_con_cookie_stale_precaricato_non_solleva_cookie_conflict(respx_mock, monkeypatch, tmp_path):
    """Trappola reale trovata testando a mano (2026-07-16): un cookies.json
    precedente (dominio "" per come lo salviamo) più il cookie appena
    impostato dalla risposta di login (dominio reale del server) hanno lo
    stesso nome sb_access_token su domini diversi - client.cookies (jar
    accumulato) va in CookieConflict a qualunque accesso ambiguo. _login
    deve salvare da resp.cookies (scoped alla sola risposta), mai da
    client.cookies."""
    cookie_file = tmp_path / "cookies.json"
    monkeypatch.setattr(cli, "COOKIE_FILE", cookie_file)
    risposte = iter(["founder@example.com", "password-vera"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(risposte))

    respx_mock.post(f"{cli.BASE_URL}/login").mock(
        return_value=httpx.Response(
            200,
            json={"status": "ok"},
            headers=[
                ("set-cookie", "sb_access_token=token-nuovo; Path=/; HttpOnly"),
                ("set-cookie", "sb_refresh_token=refresh-nuovo; Path=/; HttpOnly"),
            ],
        )
    )

    with httpx.Client(base_url=cli.BASE_URL, cookies={"sb_access_token": "token-vecchio-stale"}) as client:
        cli._login(client)  # non deve sollevare httpx.CookieConflict

    salvato = json.loads(cookie_file.read_text())
    assert salvato["sb_access_token"] == "token-nuovo"
    assert salvato["sb_refresh_token"] == "refresh-nuovo"
