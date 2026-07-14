import pytest

from orchestratore import azioni, gmail_client, tools

TENANT = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_send_email_non_invia_subito_crea_solo_azione_pending(monkeypatch):
    """La trappola centrale: chiamare il tool send_email non deve MAI
    invocare l'invio reale su Gmail, solo creare un'azione in attesa."""
    invio_chiamato = False

    async def fake_invia(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tenant_id == TENANT
        assert tipo == azioni.TIPO_SEND_EMAIL
        return "azione-123"

    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._send_email(TENANT, "x@example.com", "Oggetto", "Corpo")

    assert invio_chiamato is False
    assert "azione-123" in risultato
    assert "attesa di conferma" in risultato


@pytest.mark.asyncio
async def test_draft_email_crea_bozza_non_invia(monkeypatch):
    async def fake_token(tenant_id):
        return "fake-token"

    invio_chiamato = False

    async def fake_invia(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    async def fake_bozza(access_token, destinatario, oggetto, corpo, cc=None, bcc=None):
        return {"id": "draft-1"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)
    monkeypatch.setattr(gmail_client, "crea_bozza", fake_bozza)

    risultato = await tools._draft_email(TENANT, "x@example.com", "Oggetto", "Corpo")

    assert invio_chiamato is False
    assert "draft-1" in risultato


@pytest.mark.asyncio
async def test_reply_email_non_invia_subito_crea_solo_azione_pending(monkeypatch):
    invio_chiamato = False

    async def fake_rispondi(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tipo == azioni.TIPO_REPLY_EMAIL
        assert payload["message_id"] == "msg-1"
        return "azione-reply-1"

    monkeypatch.setattr(gmail_client, "rispondi_messaggio", fake_rispondi)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._reply_email(TENANT, "msg-1", "grazie mille")

    assert invio_chiamato is False
    assert "azione-reply-1" in risultato


@pytest.mark.asyncio
async def test_forward_email_non_invia_subito_crea_solo_azione_pending(monkeypatch):
    invio_chiamato = False

    async def fake_inoltra(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tipo == azioni.TIPO_FORWARD_EMAIL
        return "azione-forward-1"

    monkeypatch.setattr(gmail_client, "inoltra_messaggio", fake_inoltra)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._forward_email(TENANT, "msg-1", "collega@example.com")

    assert invio_chiamato is False
    assert "azione-forward-1" in risultato


@pytest.mark.asyncio
async def test_send_draft_non_invia_subito_crea_solo_azione_pending(monkeypatch):
    invio_chiamato = False

    async def fake_invia_bozza(*args, **kwargs):
        nonlocal invio_chiamato
        invio_chiamato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tipo == azioni.TIPO_SEND_DRAFT
        assert payload["draft_id"] == "draft-1"
        return "azione-draft-1"

    monkeypatch.setattr(gmail_client, "invia_bozza", fake_invia_bozza)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._send_draft(TENANT, "draft-1")

    assert invio_chiamato is False
    assert "azione-draft-1" in risultato


@pytest.mark.asyncio
async def test_trash_email_non_avviene_subito_crea_solo_azione_pending(monkeypatch):
    cestinato = False

    async def fake_cestina(*args, **kwargs):
        nonlocal cestinato
        cestinato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tipo == azioni.TIPO_TRASH_EMAIL
        return "azione-trash-1"

    monkeypatch.setattr(gmail_client, "cestina_messaggio", fake_cestina)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._trash_email(TENANT, "msg-1")

    assert cestinato is False
    assert "azione-trash-1" in risultato


@pytest.mark.asyncio
async def test_mark_email_esegue_subito_senza_conferma(monkeypatch):
    """Reversibile e a basso rischio: nessuna azione pending, esegue subito."""
    chiamate_modifica = []

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_modifica(access_token, message_id, aggiungi_label=None, rimuovi_label=None):
        chiamate_modifica.append((aggiungi_label, rimuovi_label))

    azione_creata = False

    async def fake_crea_azione(*args, **kwargs):
        nonlocal azione_creata
        azione_creata = True
        return "non-dovrebbe-succedere"

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "modifica_messaggio", fake_modifica)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._mark_email(TENANT, "msg-1", letta=True, archiviata=True)

    assert azione_creata is False
    assert len(chiamate_modifica) == 2
    assert "letta" in risultato and "archiviata" in risultato


@pytest.mark.asyncio
async def test_organize_email_trova_o_crea_etichetta_e_applica(monkeypatch):
    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_trova_o_crea(access_token, nome):
        assert nome == "Clienti VIP"
        return "label-id-123"

    applicazioni = []

    async def fake_modifica(access_token, message_id, aggiungi_label=None, rimuovi_label=None):
        applicazioni.append(aggiungi_label)

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "trova_o_crea_etichetta", fake_trova_o_crea)
    monkeypatch.setattr(gmail_client, "modifica_messaggio", fake_modifica)

    risultato = await tools._organize_email(TENANT, "msg-1", "Clienti VIP")

    assert applicazioni == [["label-id-123"]]
    assert "Clienti VIP" in risultato


@pytest.mark.asyncio
async def test_get_attachment_testo_mostra_contenuto_decodificato(monkeypatch):
    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_ottieni_messaggio(access_token, message_id):
        return {"allegati": [{"attachment_id": "att-1", "filename": "note.txt", "mime_type": "text/plain", "size": 5}]}

    async def fake_scarica(access_token, message_id, attachment_id):
        return b"ciao!"

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "ottieni_messaggio", fake_ottieni_messaggio)
    monkeypatch.setattr(gmail_client, "scarica_allegato", fake_scarica)

    risultato = await tools._get_attachment(TENANT, "msg-1", "att-1")
    assert "ciao!" in risultato


@pytest.mark.asyncio
async def test_get_attachment_binario_non_finge_di_leggerlo(monkeypatch):
    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_ottieni_messaggio(access_token, message_id):
        return {"allegati": [{"attachment_id": "att-1", "filename": "fattura.pdf", "mime_type": "application/pdf", "size": 12345}]}

    async def fake_scarica(access_token, message_id, attachment_id):
        return b"%PDF-fake-bytes"

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "ottieni_messaggio", fake_ottieni_messaggio)
    monkeypatch.setattr(gmail_client, "scarica_allegato", fake_scarica)

    risultato = await tools._get_attachment(TENANT, "msg-1", "att-1")
    assert "fattura.pdf" in risultato
    assert "Tappa 5" in risultato  # onestà sul limite attuale, non finge di aver estratto il PDF


@pytest.mark.asyncio
async def test_search_emails_nessun_risultato(monkeypatch):
    from orchestratore import embeddings
    from memoria import db as memoria_db

    async def fake_embed_query(testo):
        return [0.1, 0.2]

    async def fake_match_chunks(tenant_id, embedding, match_count=5):
        assert tenant_id == TENANT
        return []

    monkeypatch.setattr(embeddings, "embed_query", fake_embed_query)
    monkeypatch.setattr(memoria_db, "match_chunks", fake_match_chunks)

    risultato = await tools._search_emails(TENANT, "fattura")
    assert "Nessun risultato" in risultato
