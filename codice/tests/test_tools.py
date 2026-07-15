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
async def test_search_memoria_nessun_risultato(monkeypatch):
    from orchestratore import embeddings
    from memoria import db as memoria_db

    async def fake_embed_query(testo):
        return [0.1, 0.2]

    async def fake_match_chunks(tenant_id, embedding, match_count=5):
        assert tenant_id == TENANT
        return []

    async def fake_find_fatti(tenant_id, query):
        return []

    monkeypatch.setattr(embeddings, "embed_query", fake_embed_query)
    monkeypatch.setattr(memoria_db, "match_chunks", fake_match_chunks)
    monkeypatch.setattr(memoria_db, "find_fatti_ilike", fake_find_fatti)

    risultato = await tools._search_memoria(TENANT, "fattura")
    assert "Nessun risultato" in risultato


@pytest.mark.asyncio
async def test_search_memoria_fatto_sempre_incluso_anche_se_sepolto_dai_chunk(monkeypatch):
    """Trappola centrale del design: un fatto salvato deve comparire sempre
    se il nome combacia, non solo se rientra nel ranking di similarità dei
    chunk (che qui restituisce 5 risultati di mail più 'simili' per testo,
    nessuno dei quali è il fatto)."""
    from orchestratore import embeddings
    from memoria import db as memoria_db

    async def fake_embed_query(testo):
        return [0.1, 0.2]

    async def fake_match_chunks(tenant_id, embedding, match_count=5):
        return [
            {"source_type": "gmail", "source_id": f"msg-{i}", "chunk_text": "testo mail", "similarity": 0.9}
            for i in range(5)
        ]

    async def fake_find_fatti(tenant_id, query):
        assert query == "Rossi"
        return [{"entity_key": "rossi", "data": {"nome": "Rossi", "note": [{"testo": "cliente VIP"}]}}]

    monkeypatch.setattr(embeddings, "embed_query", fake_embed_query)
    monkeypatch.setattr(memoria_db, "match_chunks", fake_match_chunks)
    monkeypatch.setattr(memoria_db, "find_fatti_ilike", fake_find_fatti)

    risultato = await tools._search_memoria(TENANT, "Rossi")
    assert "rossi" in risultato.lower()
    assert "cliente VIP" in risultato


@pytest.mark.asyncio
async def test_remember_fact_prima_volta_crea_fatto_e_chunk(monkeypatch):
    from memoria import db as memoria_db
    from orchestratore import embeddings

    async def fake_get_fatto(tenant_id, entity_key):
        return None

    fatti_salvati = []

    async def fake_upsert_fatto(tenant_id, entity_key, entity_type, data):
        assert entity_key == "rossi"
        fatti_salvati.append(data)

    async def fake_find_documento(tenant_id, source_type, source_id):
        assert source_type == "fatto"
        return None

    async def fake_insert_documento(tenant_id, source_type, source_id, content_hash, categoria, priorita):
        return "doc-1"

    async def fake_embed_documenti(testi):
        return [[0.1, 0.2]]

    chunk_inseriti = []

    async def fake_insert_chunk(tenant_id, documento_id, indice, testo, embedding):
        chunk_inseriti.append(testo)

    monkeypatch.setattr(memoria_db, "get_fatto", fake_get_fatto)
    monkeypatch.setattr(memoria_db, "upsert_fatto", fake_upsert_fatto)
    monkeypatch.setattr(memoria_db, "find_documento_by_source", fake_find_documento)
    monkeypatch.setattr(memoria_db, "insert_documento", fake_insert_documento)
    monkeypatch.setattr(embeddings, "embed_documenti", fake_embed_documenti)
    monkeypatch.setattr(memoria_db, "insert_chunk", fake_insert_chunk)

    risultato = await tools._remember_fact(TENANT, "Rossi", "si è impegnato a mandare il report")

    assert fatti_salvati[0]["note"][0]["testo"] == "si è impegnato a mandare il report"
    assert "si è impegnato a mandare il report" in chunk_inseriti[0]
    assert "Rossi" in risultato


@pytest.mark.asyncio
async def test_remember_fact_seconda_volta_accumula_non_sovrascrive(monkeypatch):
    """Trappola: una seconda chiamata non deve perdere la nota precedente -
    memoria_fatti è upsert (un record per entità), la lista note deve
    accumularsi, non sovrascriversi (vedi DECISIONS.md 2026-07-15)."""
    from memoria import db as memoria_db
    from orchestratore import embeddings

    async def fake_get_fatto(tenant_id, entity_key):
        return {"data": {"nome": "Rossi", "note": [{"testo": "nota vecchia", "salvato_il": "x"}]}}

    fatti_salvati = []

    async def fake_upsert_fatto(tenant_id, entity_key, entity_type, data):
        fatti_salvati.append(data)

    async def fake_find_documento(tenant_id, source_type, source_id):
        return {"id": "doc-1"}

    eliminati = []

    async def fake_elimina_chunk(tenant_id, documento_id):
        eliminati.append(documento_id)

    async def fake_embed_documenti(testi):
        return [[0.1, 0.2]]

    async def fake_insert_chunk(tenant_id, documento_id, indice, testo, embedding):
        pass

    monkeypatch.setattr(memoria_db, "get_fatto", fake_get_fatto)
    monkeypatch.setattr(memoria_db, "upsert_fatto", fake_upsert_fatto)
    monkeypatch.setattr(memoria_db, "find_documento_by_source", fake_find_documento)
    monkeypatch.setattr(memoria_db, "elimina_chunk_documento", fake_elimina_chunk)
    monkeypatch.setattr(embeddings, "embed_documenti", fake_embed_documenti)
    monkeypatch.setattr(memoria_db, "insert_chunk", fake_insert_chunk)

    await tools._remember_fact(TENANT, "Rossi", "nota nuova")

    note = fatti_salvati[0]["note"]
    assert len(note) == 2
    assert note[0]["testo"] == "nota vecchia"
    assert note[1]["testo"] == "nota nuova"
    assert eliminati == ["doc-1"]


@pytest.mark.asyncio
async def test_create_event_senza_partecipanti_esegue_subito(monkeypatch):
    from orchestratore import calendar_client, azioni

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_crea_evento(access_token, **kwargs):
        assert kwargs["partecipanti"] is None
        return {"event_id": "evt-1", "titolo": kwargs["titolo"]}

    azione_creata = False

    async def fake_crea_azione(*args, **kwargs):
        nonlocal azione_creata
        azione_creata = True
        return "non-dovrebbe-succedere"

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "crea_evento", fake_crea_evento)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._create_event(TENANT, "Call interna", "2026-07-20T10:00:00Z", "2026-07-20T11:00:00Z")

    assert azione_creata is False
    assert "evt-1" in risultato


@pytest.mark.asyncio
async def test_create_event_con_partecipanti_crea_azione_pending(monkeypatch):
    """Trappola centrale (stessa di send_email): con partecipanti, la
    creazione NON deve mai chiamare l'API Calendar subito."""
    from orchestratore import calendar_client, azioni

    chiamato = False

    async def fake_crea_evento(access_token, **kwargs):
        nonlocal chiamato
        chiamato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tipo == azioni.TIPO_CREATE_EVENT
        assert payload["partecipanti"] == ["cliente@example.com"]
        return "azione-evt-1"

    monkeypatch.setattr(calendar_client, "crea_evento", fake_crea_evento)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._create_event(
        TENANT, "Riunione", "2026-07-20T10:00:00Z", "2026-07-20T11:00:00Z",
        partecipanti=["cliente@example.com"],
    )

    assert chiamato is False
    assert "azione-evt-1" in risultato
    assert "attesa di conferma" in risultato


@pytest.mark.asyncio
async def test_delete_event_senza_partecipanti_esegue_subito(monkeypatch):
    from orchestratore import calendar_client, azioni

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_ottieni_evento(access_token, event_id, calendario=None):
        return {"titolo": "Promemoria privato", "partecipanti": []}

    eliminato = False

    async def fake_elimina(access_token, event_id, *, notifica, calendario=None):
        nonlocal eliminato
        eliminato = True
        assert notifica is False

    azione_creata = False

    async def fake_crea_azione(*args, **kwargs):
        nonlocal azione_creata
        azione_creata = True
        return "non-dovrebbe-succedere"

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "ottieni_evento", fake_ottieni_evento)
    monkeypatch.setattr(calendar_client, "elimina_evento", fake_elimina)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._delete_event(TENANT, "evt-1")

    assert eliminato is True
    assert azione_creata is False
    assert "eliminato" in risultato


@pytest.mark.asyncio
async def test_delete_event_con_partecipanti_crea_azione_pending(monkeypatch):
    from orchestratore import calendar_client, azioni

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_ottieni_evento(access_token, event_id, calendario=None):
        return {"titolo": "Riunione cliente", "partecipanti": ["cliente@example.com"]}

    eliminato = False

    async def fake_elimina(*args, **kwargs):
        nonlocal eliminato
        eliminato = True

    async def fake_crea_azione(tenant_id, tipo, payload):
        assert tipo == azioni.TIPO_DELETE_EVENT
        assert payload["notifica"] is True
        return "azione-del-1"

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "ottieni_evento", fake_ottieni_evento)
    monkeypatch.setattr(calendar_client, "elimina_evento", fake_elimina)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._delete_event(TENANT, "evt-1")

    assert eliminato is False
    assert "azione-del-1" in risultato


@pytest.mark.asyncio
async def test_respond_to_invite_esegue_subito_senza_conferma(monkeypatch):
    from orchestratore import calendar_client, azioni

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_rispondi(access_token, event_id, risposta, calendario=None):
        assert risposta == "accepted"
        return {"titolo": "Call con Rossi"}

    azione_creata = False

    async def fake_crea_azione(*args, **kwargs):
        nonlocal azione_creata
        azione_creata = True
        return "non-dovrebbe-succedere"

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "rispondi_invito", fake_rispondi)
    monkeypatch.setattr(azioni, "crea_azione_pending", fake_crea_azione)

    risultato = await tools._respond_to_invite(TENANT, "evt-1", "accepted")

    assert azione_creata is False
    assert "accepted" in risultato


@pytest.mark.asyncio
async def test_check_availability_sola_lettura(monkeypatch):
    from orchestratore import calendar_client

    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_controlla(access_token, persone, date_from, date_to):
        return {"rossi@example.com": []}

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "controlla_disponibilita", fake_controlla)

    risultato = await tools._check_availability(TENANT, ["rossi@example.com"], "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z")

    assert "libero" in risultato
