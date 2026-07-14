"""Trappole della pipeline di ingest: filtro classificazione, dedup per
hash/source_id prima di spendere una chiamata di classificazione."""
import pytest

from memoria import db as memoria_db
from orchestratore import classification, embeddings, gmail_client, import_mail

TENANT = "11111111-1111-1111-1111-111111111111"


def _mock_base(monkeypatch, messaggi: dict[str, dict]):
    async def fake_token(tenant_id):
        return "fake-token"

    async def fake_lista(access_token, cursore):
        return list(messaggi.keys()), "9999999999"

    async def fake_ottieni(access_token, message_id):
        return messaggi[message_id]

    async def fake_get_cursore(tenant_id, source_type):
        return None

    async def fake_set_cursore(tenant_id, source_type, cursore):
        return None

    monkeypatch.setattr(gmail_client, "ottieni_access_token", fake_token)
    monkeypatch.setattr(gmail_client, "lista_messaggi_nuovi", fake_lista)
    monkeypatch.setattr(gmail_client, "ottieni_messaggio", fake_ottieni)
    monkeypatch.setattr(memoria_db, "get_import_cursore", fake_get_cursore)
    monkeypatch.setattr(memoria_db, "set_import_cursore", fake_set_cursore)


@pytest.mark.asyncio
async def test_mail_scartata_non_finisce_in_memoria(monkeypatch):
    messaggi = {
        "msg-newsletter": {
            "message_id": "msg-newsletter",
            "mittente": "newsletter@example.com",
            "oggetto": "La nostra newsletter settimanale",
            "corpo": "Contenuto promozionale",
        }
    }
    _mock_base(monkeypatch, messaggi)

    async def fake_find_hash(tenant_id, content_hash):
        return None

    async def fake_find_source(tenant_id, source_type, source_id):
        return None

    async def fake_classifica(mittente, oggetto, corpo):
        return {"ingest": False, "categoria": "altro", "priorita": "bassa"}

    insert_documento_chiamato = False

    async def fake_insert_documento(*args, **kwargs):
        nonlocal insert_documento_chiamato
        insert_documento_chiamato = True
        return "doc-1"

    monkeypatch.setattr(memoria_db, "find_documento_by_hash", fake_find_hash)
    monkeypatch.setattr(memoria_db, "find_documento_by_source", fake_find_source)
    monkeypatch.setattr(classification, "classifica_mail", fake_classifica)
    monkeypatch.setattr(memoria_db, "insert_documento", fake_insert_documento)

    risultato = await import_mail.esegui_import(TENANT)

    assert insert_documento_chiamato is False
    assert risultato == {"totale": 1, "importati": 0, "scartati": 1, "duplicati": 0}


@pytest.mark.asyncio
async def test_mail_utile_viene_salvata_con_embedding(monkeypatch):
    messaggi = {
        "msg-cliente": {
            "message_id": "msg-cliente",
            "mittente": "cliente@example.com",
            "oggetto": "Richiesta preventivo",
            "corpo": "Vorrei un preventivo per il progetto X",
        }
    }
    _mock_base(monkeypatch, messaggi)

    async def fake_find_hash(tenant_id, content_hash):
        return None

    async def fake_find_source(tenant_id, source_type, source_id):
        return None

    async def fake_classifica(mittente, oggetto, corpo):
        return {"ingest": True, "categoria": "cliente", "priorita": "alta"}

    async def fake_insert_documento(tenant_id, source_type, source_id, content_hash, categoria, priorita):
        assert categoria == "cliente"
        return "doc-1"

    chunk_salvati = []

    async def fake_insert_chunk(tenant_id, documento_id, chunk_index, chunk_text, embedding):
        chunk_salvati.append((chunk_index, chunk_text, embedding))

    async def fake_embed_documenti(chunk_texts):
        return [[0.1, 0.2] for _ in chunk_texts]

    monkeypatch.setattr(memoria_db, "find_documento_by_hash", fake_find_hash)
    monkeypatch.setattr(memoria_db, "find_documento_by_source", fake_find_source)
    monkeypatch.setattr(classification, "classifica_mail", fake_classifica)
    monkeypatch.setattr(memoria_db, "insert_documento", fake_insert_documento)
    monkeypatch.setattr(memoria_db, "insert_chunk", fake_insert_chunk)
    monkeypatch.setattr(embeddings, "embed_documenti", fake_embed_documenti)

    risultato = await import_mail.esegui_import(TENANT)

    assert risultato == {"totale": 1, "importati": 1, "scartati": 0, "duplicati": 0}
    assert len(chunk_salvati) == 1


@pytest.mark.asyncio
async def test_mail_duplicata_non_richiama_classificazione(monkeypatch):
    """Dedup avviene PRIMA della classificazione: non si spende una chiamata
    Haiku per contenuto già visto (stesso hash)."""
    messaggi = {
        "msg-duplicato": {
            "message_id": "msg-duplicato",
            "mittente": "x@example.com",
            "oggetto": "Già visto",
            "corpo": "Stesso contenuto di prima",
        }
    }
    _mock_base(monkeypatch, messaggi)

    async def fake_find_hash(tenant_id, content_hash):
        return {"id": "doc-esistente"}

    classifica_chiamata = False

    async def fake_classifica(mittente, oggetto, corpo):
        nonlocal classifica_chiamata
        classifica_chiamata = True
        return {"ingest": True, "categoria": "altro", "priorita": "bassa"}

    monkeypatch.setattr(memoria_db, "find_documento_by_hash", fake_find_hash)
    monkeypatch.setattr(classification, "classifica_mail", fake_classifica)

    risultato = await import_mail.esegui_import(TENANT)

    assert classifica_chiamata is False
    assert risultato == {"totale": 1, "importati": 0, "scartati": 0, "duplicati": 1}
