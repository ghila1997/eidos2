"""Fonte unica della descrizione leggibile di un'azione pending (Tappa 7.2).
La logica prima viveva nel CLI (`cli._descrivi_azione`); qui e' spostata sul
server perche' CLI e web mostrino la stessa cosa. Copre le trappole storiche
(payload Calendar/Memoria che non deve andare in KeyError sul ramo Gmail) e la
struttura generica {icona, titolo, riepilogo, dettagli, corpo}."""
from orchestratore.descrizioni_azioni import descrivi_azione


def _valori(descrizione) -> str:
    """Tutto il testo mostrabile, concatenato - per asserire 'contiene'."""
    parti = [descrizione["titolo"], descrizione["riepilogo"], descrizione.get("corpo") or ""]
    for r in descrizione["dettagli"]:
        parti.append(f"{r['etichetta']}: {r['valore']}")
    return "\n".join(parti)


def test_send_email_ha_a_oggetto_e_corpo():
    d = descrivi_azione({"tipo": "send_email", "payload": {
        "destinatario": "x@example.com", "oggetto": "Ciao", "corpo": "Testo del messaggio"}})
    assert d["titolo"] == "Invio email"
    assert {"etichetta": "A", "valore": "x@example.com"} in d["dettagli"]
    assert {"etichetta": "Oggetto", "valore": "Ciao"} in d["dettagli"]
    assert d["corpo"] == "Testo del messaggio"


def test_send_email_cc_e_bcc_assenti_non_lasciano_righe_vuote():
    d = descrivi_azione({"tipo": "send_email", "payload": {
        "destinatario": "x@example.com", "oggetto": "Ciao", "corpo": "T", "cc": None, "bcc": None}})
    etichette = [r["etichetta"] for r in d["dettagli"]]
    assert "Cc" not in etichette and "Ccn" not in etichette


def test_create_event_con_partecipanti_li_elenca():
    d = descrivi_azione({"tipo": "create_event", "payload": {
        "titolo": "Riunione", "inizio": "2026-07-20T10:00:00Z",
        "fine": "2026-07-20T11:00:00Z", "partecipanti": ["cliente@example.com", "a@b.it"]}})
    testo = _valori(d)
    assert "Riunione" in testo
    assert "cliente@example.com" in testo and "a@b.it" in testo


def test_delete_event_payload_calendar_non_solleva_keyerror():
    """Trappola storica (Tappa 4): un payload senza 'oggetto'/'corpo' non
    deve piu' far esplodere la descrizione pensata per Gmail."""
    d = descrivi_azione({"tipo": "delete_event", "payload": {
        "event_id": "evt-1", "notifica": True, "calendario": None}})
    assert "evt-1" in _valori(d)
    assert d["corpo"] is None


def test_share_file_pubblico_dice_chiunque_col_link():
    d = descrivi_azione({"tipo": "share_file", "payload": {
        "file_id": "f-1", "email": None, "ruolo": "reader", "pubblico": True}})
    assert "chiunque" in _valori(d).lower()


def test_propose_commitment_frase_naturale_senza_dict_grezzo():
    d = descrivi_azione({"tipo": "propose_commitment", "payload": {
        "entity_nome": "Isagro", "descrizione": "Restituire pagamento doppio fattura 725FE",
        "direzione": "nostro"}})
    testo = _valori(d)
    assert "Isagro" in testo
    assert "Restituire pagamento doppio fattura 725FE" in testo
    assert "{" not in testo and "azione di tipo" not in testo.lower()


def test_close_commitment_ha_motivo():
    d = descrivi_azione({"tipo": "close_commitment", "payload": {
        "impegno_id": "impegno-1", "motivo": "bonifico restituito il 22/07"}})
    testo = _valori(d)
    assert "impegno-1" in testo and "bonifico restituito il 22/07" in testo
    assert "{" not in testo


def test_tipo_sconosciuto_non_esplode():
    d = descrivi_azione({"tipo": "qualcosa_di_nuovo", "payload": {"x": 1}})
    assert "qualcosa_di_nuovo" in _valori(d)
    assert d["dettagli"] == []


def test_struttura_sempre_completa():
    """Ogni descrizione ha le chiavi attese: la UI ci si appoggia sempre."""
    d = descrivi_azione({"tipo": "send_email", "payload": {
        "destinatario": "x@y.it", "oggetto": "O", "corpo": "C"}})
    assert set(d) == {"icona", "titolo", "riepilogo", "dettagli", "corpo"}
    assert isinstance(d["dettagli"], list)
