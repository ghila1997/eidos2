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

    async def fake_bozza(access_token, destinatario, oggetto, corpo):
        return {"id": "draft-1"}

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "invia_messaggio", fake_invia)
    monkeypatch.setattr(gmail_client, "crea_bozza", fake_bozza)

    risultato = await tools._draft_email(TENANT, "x@example.com", "Oggetto", "Corpo")

    assert invio_chiamato is False
    assert "draft-1" in risultato


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
