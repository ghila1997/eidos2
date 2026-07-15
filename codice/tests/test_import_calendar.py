"""Trappole della pipeline di import calendario: solo eventi CONCLUSI
finiscono in Memoria (i futuri restano live, vedi search_events), eventi
cancellati non si importano, dedup prima di spendere un embedding."""
import pytest

from memoria import db as memoria_db
from orchestratore import calendar_client, embeddings, import_calendar

TENANT = "11111111-1111-1111-1111-111111111111"

EVENTO_CONCLUSO = {
    "id": "evt-passato", "summary": "Call con Rossi", "status": "confirmed",
    "start": {"dateTime": "2020-01-01T10:00:00Z"}, "end": {"dateTime": "2020-01-01T11:00:00Z"},
    "description": "Discusso il preventivo", "attendees": [{"email": "rossi@example.com"}],
}
EVENTO_FUTURO = {
    "id": "evt-futuro", "summary": "Call futura", "status": "confirmed",
    "start": {"dateTime": "2099-01-01T10:00:00Z"}, "end": {"dateTime": "2099-01-01T11:00:00Z"},
}
EVENTO_CANCELLATO = {"id": "evt-cancellato", "status": "cancelled"}


def _mock_base(monkeypatch, eventi_grezzi: list[dict]):
    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_lista_calendari(access_token):
        return [{"id": "primary", "nome": "Primario", "primario": True}]

    async def fake_sincronizza(access_token, calendar_id, sync_token):
        return eventi_grezzi, "nuovo-sync-token"

    async def fake_get_cursore(tenant_id, source_type):
        return None

    cursori_salvati = {}

    async def fake_set_cursore(tenant_id, source_type, cursore):
        cursori_salvati[source_type] = cursore

    monkeypatch.setattr(calendar_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(calendar_client, "lista_calendari", fake_lista_calendari)
    monkeypatch.setattr(calendar_client, "sincronizza_eventi", fake_sincronizza)
    monkeypatch.setattr(memoria_db, "get_import_cursore", fake_get_cursore)
    monkeypatch.setattr(memoria_db, "set_import_cursore", fake_set_cursore)
    return cursori_salvati


@pytest.mark.asyncio
async def test_evento_futuro_non_viene_importato(monkeypatch):
    """Trappola centrale: eventi futuri restano live (search_events), MAI
    importati in Memoria - staleness inaccettabile per decisioni di
    scheduling (vedi DECISIONS.md 2026-07-15)."""
    _mock_base(monkeypatch, [EVENTO_FUTURO])

    insert_chiamato = False

    async def fake_insert_documento(*args, **kwargs):
        nonlocal insert_chiamato
        insert_chiamato = True
        return "doc-1"

    monkeypatch.setattr(memoria_db, "insert_documento", fake_insert_documento)

    risultato = await import_calendar.esegui_import(TENANT)

    assert insert_chiamato is False
    assert risultato == {"importati": 0, "scartati_futuri": 1, "duplicati": 0, "cancellati": 0}


@pytest.mark.asyncio
async def test_evento_concluso_viene_importato_con_embedding(monkeypatch):
    _mock_base(monkeypatch, [EVENTO_CONCLUSO])

    async def fake_find_hash(tenant_id, content_hash):
        return None

    async def fake_find_source(tenant_id, source_type, source_id):
        return None

    async def fake_insert_documento(tenant_id, source_type, source_id, content_hash, categoria, priorita):
        assert source_type == "calendar_event"
        assert source_id == "evt-passato"
        return "doc-1"

    chunk_salvati = []

    async def fake_insert_chunk(tenant_id, documento_id, chunk_index, chunk_text, embedding):
        chunk_salvati.append(chunk_text)

    async def fake_embed_documenti(chunk_texts):
        return [[0.1, 0.2] for _ in chunk_texts]

    monkeypatch.setattr(memoria_db, "find_documento_by_hash", fake_find_hash)
    monkeypatch.setattr(memoria_db, "find_documento_by_source", fake_find_source)
    monkeypatch.setattr(memoria_db, "insert_documento", fake_insert_documento)
    monkeypatch.setattr(memoria_db, "insert_chunk", fake_insert_chunk)
    monkeypatch.setattr(embeddings, "embed_documenti", fake_embed_documenti)

    risultato = await import_calendar.esegui_import(TENANT)

    assert risultato == {"importati": 1, "scartati_futuri": 0, "duplicati": 0, "cancellati": 0}
    assert "Call con Rossi" in chunk_salvati[0]
    assert "rossi@example.com" in chunk_salvati[0]


@pytest.mark.asyncio
async def test_evento_cancellato_non_viene_importato(monkeypatch):
    _mock_base(monkeypatch, [EVENTO_CANCELLATO])

    insert_chiamato = False

    async def fake_insert_documento(*args, **kwargs):
        nonlocal insert_chiamato
        insert_chiamato = True
        return "doc-1"

    monkeypatch.setattr(memoria_db, "insert_documento", fake_insert_documento)

    risultato = await import_calendar.esegui_import(TENANT)

    assert insert_chiamato is False
    assert risultato == {"importati": 0, "scartati_futuri": 0, "duplicati": 0, "cancellati": 1}


@pytest.mark.asyncio
async def test_evento_concluso_duplicato_non_reimportato(monkeypatch):
    _mock_base(monkeypatch, [EVENTO_CONCLUSO])

    async def fake_find_hash(tenant_id, content_hash):
        return {"id": "doc-esistente"}

    embed_chiamato = False

    async def fake_embed_documenti(chunk_texts):
        nonlocal embed_chiamato
        embed_chiamato = True
        return [[0.1, 0.2] for _ in chunk_texts]

    monkeypatch.setattr(memoria_db, "find_documento_by_hash", fake_find_hash)
    monkeypatch.setattr(embeddings, "embed_documenti", fake_embed_documenti)

    risultato = await import_calendar.esegui_import(TENANT)

    assert embed_chiamato is False
    assert risultato == {"importati": 0, "scartati_futuri": 0, "duplicati": 1, "cancellati": 0}
