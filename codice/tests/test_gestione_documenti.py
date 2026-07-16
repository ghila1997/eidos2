"""Ciclo di vita dei documenti importati (Tappa 5.1): elencare, rivedere
(con link all'originale archiviato), dimenticare. Trappole centrali:
- dimenticare deve rimuovere TUTTO (riga, chunk via cascade, file su
  Storage, voce nell'array 'documenti' del fatto collegato) - una voce
  orfana nel fatto mostrerebbe per sempre campi di un documento che
  l'utente ha chiesto di eliminare
- solo i documenti importati (gmail_attachment/drive_file/locale) si
  dimenticano da qui - mai mail/eventi/fatti indicizzati (hanno altri
  cicli di vita)
"""
import pytest

from memoria import gestione_documenti

TENANT = "11111111-1111-1111-1111-111111111111"


class _SpyDb:
    def __init__(self):
        self.documenti: list[dict] = []
        self.fatti: dict[str, dict] = {}
        self.eliminati: list[str] = []

    async def list_documenti_importati(self, tenant_id):
        return list(self.documenti)

    async def get_documento(self, tenant_id, documento_id):
        return next((d for d in self.documenti if d["id"] == documento_id), None)

    async def delete_documento(self, tenant_id, documento_id):
        self.eliminati.append(documento_id)
        self.documenti = [d for d in self.documenti if d["id"] != documento_id]

    async def find_fatti_con_documento(self, tenant_id, documento_id):
        return [
            {"entity_key": k, "entity_type": f["entity_type"], "data": f["data"]}
            for k, f in self.fatti.items()
            if any(d["documento_id"] == documento_id for d in f["data"].get("documenti", []))
        ]

    async def upsert_fatto(self, tenant_id, entity_key, entity_type, data):
        self.fatti[entity_key] = {"entity_type": entity_type, "data": data}


@pytest.fixture
def spy_db(monkeypatch):
    spy = _SpyDb()
    monkeypatch.setattr(gestione_documenti, "memoria_db", spy)
    return spy


@pytest.fixture
def spy_storage(monkeypatch):
    chiamate = {"eliminati": [], "url_richiesti": []}

    async def fake_elimina(storage_path):
        chiamate["eliminati"].append(storage_path)

    async def fake_url_firmato(storage_path, scadenza_secondi=3600):
        chiamate["url_richiesti"].append(storage_path)
        return f"https://firmato.example/{storage_path}"

    monkeypatch.setattr(gestione_documenti.storage, "elimina_file", fake_elimina)
    monkeypatch.setattr(gestione_documenti.storage, "crea_url_firmato", fake_url_firmato)
    return chiamate


@pytest.fixture
def spy_reindicizza(monkeypatch):
    chiamate = []

    async def fake_reindicizza(tenant_id, entity_key, entity_tipo, data):
        chiamate.append((entity_key, data))

    monkeypatch.setattr(gestione_documenti.fatti_indicizzazione, "reindicizza_fatto", fake_reindicizza)
    return chiamate


_DOC_FATTURA = {
    "id": "doc-1", "source_type": "drive_file", "source_id": "file-1",
    "categoria": "fattura", "storage_path": f"{TENANT}/doc-1/fattura_rossi.pdf",
    "created_at": "2026-07-16T10:00:00+00:00", "stato": "completo",
}


@pytest.mark.asyncio
async def test_elenca_vuoto(spy_db, spy_storage):
    risultato = await gestione_documenti.elenca_documenti(TENANT)
    assert "essun documento" in risultato


@pytest.mark.asyncio
async def test_elenca_mostra_nome_file_id_e_tipo(spy_db, spy_storage):
    spy_db.documenti.append(dict(_DOC_FATTURA))

    risultato = await gestione_documenti.elenca_documenti(TENANT)

    assert "fattura_rossi.pdf" in risultato
    assert "doc-1" in risultato
    assert "fattura" in risultato


@pytest.mark.asyncio
async def test_descrivi_documento_con_link_firmato(spy_db, spy_storage):
    spy_db.documenti.append(dict(_DOC_FATTURA))

    risultato = await gestione_documenti.descrivi_documento(TENANT, "doc-1")

    assert "fattura_rossi.pdf" in risultato
    assert f"https://firmato.example/{TENANT}/doc-1/fattura_rossi.pdf" in risultato


@pytest.mark.asyncio
async def test_descrivi_documento_inesistente(spy_db, spy_storage):
    with pytest.raises(gestione_documenti.ErroreGestioneDocumento, match="rovat"):
        await gestione_documenti.descrivi_documento(TENANT, "doc-fantasma")


@pytest.mark.asyncio
async def test_dimentica_documento_inesistente(spy_db, spy_storage):
    with pytest.raises(gestione_documenti.ErroreGestioneDocumento, match="rovat"):
        await gestione_documenti.dimentica_documento(TENANT, "doc-fantasma")


@pytest.mark.asyncio
async def test_dimentica_rifiuta_documenti_non_importati(spy_db, spy_storage):
    """Le righe memoria_documenti di mail/eventi/fatti indicizzati non sono
    documenti importati: dimenticarle da qui romperebbe gli altri flussi."""
    spy_db.documenti.append({
        "id": "doc-fatto", "source_type": "fatto", "source_id": "rossi_srl",
        "categoria": "fornitore", "storage_path": None,
        "created_at": "2026-07-16T10:00:00+00:00", "stato": "completo",
    })

    with pytest.raises(gestione_documenti.ErroreGestioneDocumento, match="importat"):
        await gestione_documenti.dimentica_documento(TENANT, "doc-fatto")
    assert spy_db.eliminati == []


@pytest.mark.asyncio
async def test_dimentica_rimuove_riga_storage_e_voce_nel_fatto(spy_db, spy_storage, spy_reindicizza):
    spy_db.documenti.append(dict(_DOC_FATTURA))
    spy_db.fatti["rossi_srl"] = {
        "entity_type": "fornitore",
        "data": {
            "nome": "Rossi Srl",
            "note": [{"testo": "nota manuale", "salvato_il": "2026-07-01"}],
            "documenti": [
                {"documento_id": "doc-1", "tipo_documento": "fattura", "campi": {"importo": "500"}},
                {"documento_id": "doc-altro", "tipo_documento": "contratto", "campi": {}},
            ],
        },
    }

    risultato = await gestione_documenti.dimentica_documento(TENANT, "doc-1")

    assert "fattura_rossi.pdf" in risultato
    assert spy_db.eliminati == ["doc-1"]
    assert spy_storage["eliminati"] == [f"{TENANT}/doc-1/fattura_rossi.pdf"]
    # la voce del documento sparisce dal fatto, il resto resta
    documenti_fatto = spy_db.fatti["rossi_srl"]["data"]["documenti"]
    assert [d["documento_id"] for d in documenti_fatto] == ["doc-altro"]
    assert spy_db.fatti["rossi_srl"]["data"]["note"]  # note manuali intatte
    # e il fatto viene re-indicizzato senza la voce rimossa
    assert spy_reindicizza and spy_reindicizza[0][0] == "rossi_srl"


@pytest.mark.asyncio
async def test_dimentica_documento_senza_fatto_ne_storage(spy_db, spy_storage, spy_reindicizza):
    spy_db.documenti.append({
        "id": "doc-2", "source_type": "locale", "source_id": "/tmp/appunti.txt",
        "categoria": "altro", "storage_path": None,
        "created_at": "2026-07-16T10:00:00+00:00", "stato": "completo",
    })

    await gestione_documenti.dimentica_documento(TENANT, "doc-2")

    assert spy_db.eliminati == ["doc-2"]
    assert spy_storage["eliminati"] == []
    assert spy_reindicizza == []
