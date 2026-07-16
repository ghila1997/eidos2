"""Trappole centrali di Tappa 5 (Memoria: estensione documenti):
- dedup cross-origine per hash, prima di qualunque estrazione/upload
- PDF scansionato oltre il limite pagine -> rifiuto esplicito, non un
  tentativo silenzioso che esplode in costo
- entità non riconosciuta -> solo ricerca semantica, niente scrittura in
  memoria_fatti a rischio
- entità riconosciuta -> upsert in memoria_fatti (array 'documenti',
  separato da 'note' di remember_fact) più re-indicizzazione del fatto
"""
import hashlib

import pytest

from memoria import ingest_documento

TENANT = "11111111-1111-1111-1111-111111111111"


class _SpyDb:
    def __init__(self):
        self.documenti: dict = {}
        self.fatti: dict = {}
        self.chunk_inseriti: list = []
        self.insert_documento_chiamato = False
        self.stato_insert: str | None = None

    def _record_per_id(self, documento_id):
        for record in self.documenti.values():
            if record["id"] == documento_id:
                return record
        return None

    async def find_documento_by_hash(self, tenant_id, content_hash):
        return self.documenti.get(("hash", content_hash))

    async def find_documento_by_source(self, tenant_id, source_type, source_id):
        return self.documenti.get(("source", source_type, source_id))

    async def insert_documento(self, tenant_id, source_type, source_id, content_hash, categoria, priorita, storage_path=None, stato="completo"):
        self.insert_documento_chiamato = True
        self.stato_insert = stato
        doc_id = f"doc-{len(self.documenti)}"
        record = {"id": doc_id, "stato": stato, "content_hash": content_hash}
        self.documenti[("hash", content_hash)] = record
        self.documenti[("source", source_type, source_id)] = record
        return doc_id

    async def set_storage_path(self, tenant_id, documento_id, storage_path):
        pass

    async def update_documento(self, tenant_id, documento_id, content_hash, categoria, priorita):
        record = self._record_per_id(documento_id)
        vecchio_hash = record.get("content_hash")
        if vecchio_hash and ("hash", vecchio_hash) in self.documenti:
            del self.documenti[("hash", vecchio_hash)]
        record["content_hash"] = content_hash
        record["stato"] = "in_corso"
        self.documenti[("hash", content_hash)] = record

    async def segna_documento_completo(self, tenant_id, documento_id):
        self._record_per_id(documento_id)["stato"] = "completo"

    async def insert_chunk(self, tenant_id, documento_id, indice, testo, embedding):
        self.chunk_inseriti.append((documento_id, indice, testo))

    async def get_fatto(self, tenant_id, entity_key):
        return self.fatti.get(entity_key)

    async def upsert_fatto(self, tenant_id, entity_key, entity_type, data):
        self.fatti[entity_key] = {"entity_type": entity_type, "data": data}

    async def elimina_chunk_documento(self, tenant_id, documento_id):
        pass


@pytest.fixture
def spy_db(monkeypatch):
    spy = _SpyDb()
    monkeypatch.setattr(ingest_documento, "memoria_db", spy)
    # la re-indicizzazione dei fatti vive nel modulo condiviso
    # fatti_indicizzazione (usato anche da gestione_documenti)
    monkeypatch.setattr(ingest_documento.fatti_indicizzazione, "memoria_db", spy)
    return spy


@pytest.fixture(autouse=True)
def _no_storage_upload(monkeypatch):
    async def fake_carica(storage_path, contenuto, mime_type):
        pass

    monkeypatch.setattr(ingest_documento.storage, "carica_file", fake_carica)


@pytest.fixture(autouse=True)
def _chunking_ed_embedding_finti(monkeypatch):
    monkeypatch.setattr(ingest_documento.chunking, "spezza_in_chunk", lambda testo: [testo] if testo else [])

    async def fake_embed(chunk_testi):
        return [[0.1, 0.2] for _ in chunk_testi]

    monkeypatch.setattr(ingest_documento.embeddings, "embed_documenti", fake_embed)
    monkeypatch.setattr(ingest_documento.fatti_indicizzazione.embeddings, "embed_documenti", fake_embed)


@pytest.mark.asyncio
async def test_dedup_per_hash_non_reimporta(spy_db):
    contenuto = b"contenuto identico"
    content_hash = hashlib.sha256(contenuto).hexdigest()
    spy_db.documenti[("hash", content_hash)] = {"id": "doc-esistente", "stato": "completo"}

    risultato = await ingest_documento.importa_documento(
        TENANT, "gmail_attachment", "msg:att", "file.txt", contenuto, "text/plain"
    )

    assert "già presente" in risultato
    assert spy_db.insert_documento_chiamato is False


@pytest.mark.asyncio
async def test_dedup_cross_origine_stesso_contenuto_fonti_diverse(spy_db, monkeypatch):
    """Lo stesso documento (stesso hash) arrivato da mail e poi da Drive
    non deve produrre un secondo memoria_documenti."""
    contenuto = b"stessa fattura, due fonti"

    async def fake_estrai_testo(testo):
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    primo = await ingest_documento.importa_documento(
        TENANT, "gmail_attachment", "msg:att", "fattura.txt", contenuto, "text/plain"
    )
    secondo = await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-drive-1", "fattura.txt", contenuto, "text/plain"
    )

    assert "importato" in primo
    assert "già presente" in secondo
    assert sum(1 for k in spy_db.documenti if k[0] == "hash") == 1


@pytest.mark.asyncio
async def test_stesso_source_contenuto_cambiato_aggiorna_non_duplica(monkeypatch, spy_db):
    """Trappola reale: un file re-importato con lo stesso source_id (es. lo
    stesso file Drive modificato) ma contenuto diverso non deve essere
    ignorato come "già presente" (dati vecchi mostrati come aggiornati) né
    creare un secondo documento (violerebbe il vincolo unico su source_id) -
    deve aggiornare lo stesso record."""
    chiamate_estrazione = []

    async def fake_estrai_testo(testo):
        chiamate_estrazione.append(testo)
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    primo = await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-drive-1", "listino.txt", b"versione 1 del listino", "text/plain"
    )
    secondo = await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-drive-1", "listino.txt", b"versione 2, prezzi aggiornati", "text/plain"
    )

    assert "importato" in primo
    assert "aggiornato" in secondo
    assert "già presente" not in secondo
    # un solo documento (stesso id), non due
    assert sum(1 for k in spy_db.documenti if k[0] == "source") == 1
    assert len(chiamate_estrazione) == 2  # ri-estratto sul nuovo contenuto


@pytest.mark.asyncio
async def test_pdf_scansionato_oltre_limite_pagine_rifiuta(monkeypatch, spy_db):
    monkeypatch.setattr(ingest_documento.file_extraction, "pdf_ha_testo_digitale", lambda contenuto: False)
    monkeypatch.setattr(ingest_documento.file_extraction, "numero_pagine_pdf", lambda contenuto: 25)

    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="limite"):
        await ingest_documento.importa_documento(
            TENANT, "locale", "/tmp/scansione.pdf", "scansione.pdf", b"%PDF-finto", "application/pdf"
        )


@pytest.mark.asyncio
async def test_entity_non_riconosciuta_non_scrive_fatti(monkeypatch, spy_db):
    async def fake_estrai_testo(testo):
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    risultato = await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/appunti.txt", "appunti.txt", b"appunti generici", "text/plain"
    )

    assert "importato" in risultato
    assert spy_db.fatti == {}


@pytest.mark.asyncio
async def test_entity_riconosciuta_scrive_fatti_con_documenti_array(monkeypatch, spy_db):
    async def fake_estrai_testo(testo):
        return {
            "tipo_documento": "fattura", "entity_nome": "Rossi Srl",
            "entity_tipo": "fornitore", "campi": {"importo": "500.00", "scadenza": "2026-08-30"},
        }

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    risultato = await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/fattura.txt", "fattura.txt", b"fattura di rossi srl", "text/plain"
    )

    assert "Rossi Srl" in risultato
    fatto = spy_db.fatti["rossi_srl"]
    assert fatto["data"]["nome"] == "Rossi Srl"
    assert len(fatto["data"]["documenti"]) == 1
    assert fatto["data"]["documenti"][0]["campi"]["importo"] == "500.00"
    # il fatto viene anche re-indicizzato per la ricerca semantica (source_type "fatto")
    assert ("source", "fatto", "rossi_srl") in spy_db.documenti


@pytest.mark.asyncio
async def test_testo_con_nul_byte_sanitizzato_prima_del_chunk(monkeypatch, spy_db):
    """Trappola reale trovata testando una fattura PDF vera (Anthropic/
    Stripe): `pypdf` produce a volte un byte NUL (\\x00) nel testo estratto
    (sostituto di un trattino/glyph mancante nel font) - Postgres rifiuta
    NUL in una colonna text, l'insert del chunk falliva con 400. Un mock
    non l'avrebbe mai mostrato."""
    async def fake_estrai_testo(testo):
        return {"tipo_documento": "fattura", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/fattura.txt", "fattura.txt",
        "numero\x009BF0758D".encode("utf-8"), "text/plain",
    )

    assert spy_db.chunk_inseriti
    for _documento_id, _indice, testo_chunk in spy_db.chunk_inseriti:
        assert "\x00" not in testo_chunk


@pytest.mark.asyncio
async def test_file_troppo_grande_rifiuta(spy_db):
    contenuto = b"x" * (ingest_documento.MAX_DIMENSIONE_FILE + 1)

    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="grande"):
        await ingest_documento.importa_documento(
            TENANT, "locale", "/tmp/enorme.txt", "enorme.txt", contenuto, "text/plain"
        )


@pytest.mark.asyncio
async def test_fonte_non_valida_rifiuta(spy_db):
    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="Fonte"):
        await ingest_documento.importa_documento(
            TENANT, "fonte_a_caso", "id", "file.txt", b"contenuto", "text/plain"
        )


@pytest.mark.asyncio
async def test_formato_non_supportato_rifiuta(spy_db):
    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="non supportato"):
        await ingest_documento.importa_documento(
            TENANT, "locale", "/tmp/audio.mp3", "audio.mp3", b"contenuto", "audio/mpeg"
        )


@pytest.mark.asyncio
async def test_update_entita_sostituisce_voce_documento_nel_fatto(monkeypatch, spy_db):
    """Trappola: aggiornare un documento (stesso source, contenuto cambiato)
    NON deve accumulare una seconda voce nell'array 'documenti' del fatto -
    la voce vecchia con i campi ormai sbagliati (es. importo della versione
    precedente) resterebbe per sempre come se fosse attuale."""
    versione = {"n": 0}

    async def fake_estrai_testo(testo):
        versione["n"] += 1
        return {
            "tipo_documento": "fattura", "entity_nome": "Rossi Srl",
            "entity_tipo": "fornitore", "campi": {"importo": f"{versione['n']}00.00"},
        }

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-1", "fattura.txt", b"versione 1", "text/plain"
    )
    await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-1", "fattura.txt", b"versione 2", "text/plain"
    )

    documenti_fatto = spy_db.fatti["rossi_srl"]["data"]["documenti"]
    assert len(documenti_fatto) == 1
    assert documenti_fatto[0]["campi"]["importo"] == "200.00"


@pytest.mark.asyncio
async def test_stato_in_corso_durante_ingest_completo_alla_fine(monkeypatch, spy_db):
    async def fake_estrai_testo(testo):
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/nota.txt", "nota.txt", b"nota qualunque", "text/plain"
    )

    assert spy_db.stato_insert == "in_corso"
    record = spy_db.documenti[("source", "locale", "/tmp/nota.txt")]
    assert record["stato"] == "completo"


@pytest.mark.asyncio
async def test_import_interrotto_non_maschera_il_retry(monkeypatch, spy_db):
    """Trappola reale (successa testando Tappa 5, ripulita a mano nel DB):
    un crash tra insert_documento e i chunk lasciava una riga con hash
    valorizzato ma zero chunk - da lì ogni re-import diceva "già presente"
    mentre NIENTE era ricercabile. Perdita silenziosa e permanente."""
    async def fake_estrai_testo(testo):
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    crash = {"attivo": True}
    insert_chunk_vero = spy_db.insert_chunk

    async def insert_chunk_che_crasha(*args):
        if crash["attivo"]:
            raise RuntimeError("connessione persa a metà ingest")
        await insert_chunk_vero(*args)

    monkeypatch.setattr(spy_db, "insert_chunk", insert_chunk_che_crasha)

    with pytest.raises(RuntimeError):
        await ingest_documento.importa_documento(
            TENANT, "drive_file", "file-x", "nota.txt", b"contenuto importante", "text/plain"
        )
    record = spy_db.documenti[("source", "drive_file", "file-x")]
    assert record["stato"] != "completo"

    crash["attivo"] = False
    risultato = await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-x", "nota.txt", b"contenuto importante", "text/plain"
    )

    assert "già presente" not in risultato
    assert spy_db.chunk_inseriti
    assert record["stato"] == "completo"


@pytest.mark.asyncio
async def test_hash_dedup_ignora_documenti_incompleti_di_altra_fonte(monkeypatch, spy_db):
    """Orfano in_corso da un'altra fonte con gli stessi byte: non deve né
    bloccare l'import (vincolo unico su hash) né essere trattato come "già
    presente" - si ripara quel record."""
    async def fake_estrai_testo(testo):
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    contenuto = b"stessi byte, fonte diversa"
    content_hash = hashlib.sha256(contenuto).hexdigest()
    orfano = {"id": "doc-orfano", "stato": "in_corso", "content_hash": content_hash}
    spy_db.documenti[("hash", content_hash)] = orfano
    spy_db.documenti[("source", "gmail_attachment", "msg:vecchio")] = orfano

    risultato = await ingest_documento.importa_documento(
        TENANT, "drive_file", "file-nuovo", "doc.txt", contenuto, "text/plain"
    )

    assert "già presente" not in risultato
    assert spy_db.insert_documento_chiamato is False  # riparato, non duplicato
    assert orfano["stato"] == "completo"
    assert spy_db.chunk_inseriti


@pytest.mark.asyncio
async def test_errore_api_estrazione_diventa_errore_gestito(monkeypatch, spy_db):
    """Un errore di rete/API Anthropic non deve arrivare al modello come
    traceback grezzo: diventa ErroreIngestDocumento (messaggio pulito)."""
    import anthropic
    import httpx

    async def fake_estrai_testo(testo):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="strazione"):
        await ingest_documento.importa_documento(
            TENANT, "locale", "/tmp/doc.txt", "doc.txt", b"contenuto", "text/plain"
        )
    # niente riga orfana: l'errore avviene prima dell'insert
    assert spy_db.insert_documento_chiamato is False


@pytest.mark.asyncio
async def test_testo_enorme_cap_su_estrazione_ma_ricerca_completa(monkeypatch, spy_db):
    """Un XLSX/testo enorme non deve sfondare il contesto del modello di
    estrazione campi - ma la ricerca semantica indicizza TUTTO il testo,
    nessuna informazione persa."""
    lunghezze_estrazione = []

    async def fake_estrai_testo(testo):
        lunghezze_estrazione.append(len(testo))
        return {"tipo_documento": "altro", "campi": {}}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_testo", fake_estrai_testo)

    testo_enorme = "riga di listino con prezzi\n" * 10_000  # ~270k caratteri
    await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/listino.txt", "listino.txt", testo_enorme.encode(), "text/plain"
    )

    assert lunghezze_estrazione[0] <= ingest_documento.MAX_CARATTERI_ESTRAZIONE
    testo_indicizzato = "".join(t for _d, _i, t in spy_db.chunk_inseriti)
    assert len(testo_indicizzato) == len(testo_enorme)


@pytest.mark.asyncio
async def test_pdf_cifrato_rifiutato_con_messaggio_chiaro(monkeypatch, spy_db):
    monkeypatch.setattr(ingest_documento.file_extraction, "pdf_e_cifrato", lambda contenuto: True)

    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="password"):
        await ingest_documento.importa_documento(
            TENANT, "locale", "/tmp/protetto.pdf", "protetto.pdf", b"%PDF-finto", "application/pdf"
        )


@pytest.mark.asyncio
async def test_pdf_misto_va_al_percorso_visivo(monkeypatch, spy_db):
    """Copertina digitale + pagine scansionate: il testo totale supera la
    soglia, ma le pagine scansionate hanno contenuto che l'estrazione
    locale perderebbe in silenzio - deve passare dalla visione."""
    monkeypatch.setattr(ingest_documento.file_extraction, "pdf_e_cifrato", lambda contenuto: False)
    monkeypatch.setattr(ingest_documento.file_extraction, "pdf_ha_testo_digitale", lambda contenuto: True)
    monkeypatch.setattr(ingest_documento.file_extraction, "indici_pagine_scansione", lambda contenuto: [1, 2])
    monkeypatch.setattr(ingest_documento.file_extraction, "numero_pagine_pdf", lambda contenuto: 3)

    visione_chiamata = {"si": False}

    async def fake_visione(contenuto, mime_type):
        visione_chiamata["si"] = True
        return {"tipo_documento": "contratto", "campi": {}, "testo_completo": "testo trascritto"}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_documento_visivo", fake_visione)

    await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/contratto.pdf", "contratto.pdf", b"%PDF-finto", "application/pdf"
    )

    assert visione_chiamata["si"] is True


@pytest.mark.asyncio
async def test_immagine_normalizzata_per_visione_originale_archiviato(monkeypatch, spy_db):
    """La visione riceve l'immagine normalizzata (formato/dimensioni API),
    ma Storage archivia i byte ORIGINALI - l'originale dell'utente non si
    tocca mai."""
    originale = b"finto-tiff-originale"

    def fake_normalizza(contenuto, mime_type):
        assert contenuto == originale
        return b"finto-jpeg-normalizzato", "image/jpeg"

    monkeypatch.setattr(ingest_documento.image_normalization, "normalizza_per_visione", fake_normalizza)

    ricevuto_da_visione = {}

    async def fake_visione(contenuto, mime_type):
        ricevuto_da_visione["contenuto"] = contenuto
        ricevuto_da_visione["mime"] = mime_type
        return {"tipo_documento": "ricevuta", "campi": {}, "testo_completo": "scontrino"}

    monkeypatch.setattr(ingest_documento.document_extraction, "estrai_da_documento_visivo", fake_visione)

    archiviato = {}

    async def fake_carica(storage_path, contenuto, mime_type):
        archiviato["contenuto"] = contenuto

    monkeypatch.setattr(ingest_documento.storage, "carica_file", fake_carica)

    await ingest_documento.importa_documento(
        TENANT, "locale", "/tmp/scan.tiff", "scan.tiff", originale, "image/tiff"
    )

    assert ricevuto_da_visione["contenuto"] == b"finto-jpeg-normalizzato"
    assert ricevuto_da_visione["mime"] == "image/jpeg"
    assert archiviato["contenuto"] == originale


@pytest.mark.asyncio
async def test_immagine_illeggibile_errore_gestito(monkeypatch, spy_db):
    def fake_normalizza(contenuto, mime_type):
        raise ingest_documento.image_normalization.ErroreImmagineNonLeggibile("bytes corrotti")

    monkeypatch.setattr(ingest_documento.image_normalization, "normalizza_per_visione", fake_normalizza)

    with pytest.raises(ingest_documento.ErroreIngestDocumento, match="immagine"):
        await ingest_documento.importa_documento(
            TENANT, "locale", "/tmp/rotta.jpg", "rotta.jpg", b"corrotti", "image/jpeg"
        )
