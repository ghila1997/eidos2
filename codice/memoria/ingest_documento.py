"""Pipeline di ingest documenti (Tappa 5: Memoria - estensione documenti),
condivisa tra Orchestratore (fonti: allegato Gmail, file Drive) e Agente
Locale (fonte: file locale dentro il perimetro autorizzato) - stessa
logica, chiamata diretta da entrambi (vedi design Tappa 5, DECISIONS.md).

Routing per formato/qualità (minimizza il costo, vedi discussione di
design):
- PDF con strato di testo digitale, DOCX, XLSX, testo semplice -> estrazione
  locale gratuita (file_extraction.py) + Haiku economico
  (document_extraction.estrai_da_testo)
- PDF scansionato (nessun testo estraibile) o immagine (foto di un
  documento cartaceo) -> Sonnet 5, content block nativo, un'unica chiamata
  che trascrive ed estrae insieme (document_extraction.estrai_da_documento_visivo)

Sempre: dedup cross-origine per hash dei byte grezzi, archiviazione del
file originale su Supabase Storage, chunk+embedding per ricerca semantica,
e — solo se un'entità/controparte è riconosciuta con chiarezza — upsert in
memoria_fatti (altrimenti solo ricerca semantica, mai un entity_key
indovinato a rischio, vedi discussione di design).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from memoria import db as memoria_db
from orchestratore import chunking, embeddings

from . import document_extraction, file_extraction, storage

MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

FONTI = ("gmail_attachment", "drive_file", "locale")

# Cap sul path costoso (visione): un documento aziendale reale (fattura,
# contratto, DDT) non supera mai queste pagine - oltre, rifiuto esplicito
# invece di far esplodere il costo su un caso non realistico per "un
# documento da ricordare" (vedi discussione di design).
MAX_PAGINE_VISIONE = 20
MAX_DIMENSIONE_FILE = 20 * 1024 * 1024


class ErroreIngestDocumento(Exception):
    """Errore atteso (formato non supportato, file troppo grande) - non un bug."""


def _slug_entity(nome: str) -> str:
    return "_".join(nome.strip().lower().split())


def _sanitizza_testo(testo: str) -> str:
    """Postgres rifiuta il byte NUL (\\x00) in una colonna text - trovato
    testando davvero una fattura PDF reale (Anthropic/Stripe): `pypdf` lo
    produce a volte come sostituto di un trattino/glyph mancante nel font.
    Un mock non l'avrebbe mai mostrato, serviva testo estratto da un PDF
    vero (vedi discussione di design Tappa 5, "testare sempre con dati
    reali")."""
    return testo.replace("\x00", "")


async def _estrai_testo_e_campi(contenuto: bytes, mime_type: str) -> tuple[str, document_extraction.Estrazione]:
    """Decide il percorso (locale+Haiku economico vs Sonnet visione) e
    ritorna (testo_per_ricerca_semantica, campi_estratti)."""
    if mime_type == MIME_PDF:
        if file_extraction.pdf_ha_testo_digitale(contenuto):
            testo = file_extraction.estrai_testo_pdf(contenuto)
            return testo, await document_extraction.estrai_da_testo(testo)
        try:
            pagine = file_extraction.numero_pagine_pdf(contenuto)
        except Exception:
            pagine = None
        if pagine is not None and pagine > MAX_PAGINE_VISIONE:
            raise ErroreIngestDocumento(
                f"PDF scansionato di {pagine} pagine, oltre il limite di "
                f"{MAX_PAGINE_VISIONE} per l'estrazione visiva - troppo costoso "
                "da processare in questo modo."
            )
        estrazione = await document_extraction.estrai_da_documento_visivo(contenuto, mime_type)
        return estrazione.get("testo_completo", ""), estrazione
    if mime_type.startswith("image/"):
        estrazione = await document_extraction.estrai_da_documento_visivo(contenuto, mime_type)
        return estrazione.get("testo_completo", ""), estrazione
    if mime_type == MIME_DOCX:
        testo = file_extraction.estrai_testo_docx(contenuto)
        return testo, await document_extraction.estrai_da_testo(testo)
    if mime_type == MIME_XLSX:
        testo = file_extraction.estrai_testo_xlsx(contenuto)
        return testo, await document_extraction.estrai_da_testo(testo)
    if mime_type.startswith("text/"):
        testo = contenuto.decode("utf-8", errors="replace")
        return testo, await document_extraction.estrai_da_testo(testo)
    raise ErroreIngestDocumento(f"Formato non supportato per l'importazione in memoria: {mime_type}")


async def _aggiorna_fatto_documento(
    tenant_id: str, entity_nome: str, entity_tipo: str, documento_id: str,
    tipo_documento: str, campi: dict[str, str],
) -> None:
    """Upsert in memoria_fatti (array 'documenti', separato da 'note' di
    remember_fact) + rigenera il chunk embedded del fatto, stesso pattern
    di orchestratore/tools.py _remember_fact ma per documenti invece di
    note manuali - non refactorizzato in comune per non toccare codice
    Tappa 2/4 già validato senza necessità funzionale (vedi CLAUDE.md)."""
    entity_key = _slug_entity(entity_nome)
    esistente = await memoria_db.get_fatto(tenant_id, entity_key)
    note = list(esistente["data"].get("note", [])) if esistente else []
    documenti = list(esistente["data"].get("documenti", [])) if esistente else []
    documenti.append({
        "documento_id": documento_id,
        "tipo_documento": tipo_documento,
        "campi": campi,
        "salvato_il": datetime.now(timezone.utc).isoformat(),
    })
    await memoria_db.upsert_fatto(
        tenant_id, entity_key, entity_tipo,
        {"nome": entity_nome, "note": note, "documenti": documenti},
    )

    testo_fatto = f"{entity_nome}: " + " | ".join(n["testo"] for n in note)
    testo_fatto += " | " + " | ".join(
        f"{d['tipo_documento']} ({d['documento_id']}): {d['campi']}" for d in documenti
    )
    documento_fatto = await memoria_db.find_documento_by_source(tenant_id, "fatto", entity_key)
    if documento_fatto is None:
        content_hash = hashlib.sha256(testo_fatto.encode("utf-8")).hexdigest()
        documento_fatto_id = await memoria_db.insert_documento(
            tenant_id, "fatto", entity_key, content_hash, entity_tipo, None
        )
    else:
        documento_fatto_id = documento_fatto["id"]
        await memoria_db.elimina_chunk_documento(tenant_id, documento_fatto_id)
    embedding = (await embeddings.embed_documenti([testo_fatto]))[0]
    await memoria_db.insert_chunk(tenant_id, documento_fatto_id, 0, testo_fatto, embedding)


async def importa_documento(
    tenant_id: str, fonte: str, source_id: str, nome_file: str,
    contenuto: bytes, mime_type: str,
) -> str:
    """Ingest esplicito di un documento in Memoria (chunk+embed per
    ricerca semantica, più estrazione strutturata se un'entità/
    controparte è riconosciuta). Azione immediata come remember_fact
    (additiva, reversibile) ma sempre esplicita - mai automatica durante
    una lettura normale (vincolo nella description del tool chiamante)."""
    if fonte not in FONTI:
        raise ErroreIngestDocumento(f"Fonte non valida: {fonte}")
    if len(contenuto) > MAX_DIMENSIONE_FILE:
        raise ErroreIngestDocumento(
            f"File troppo grande ({len(contenuto) / 1_000_000:.1f}MB, limite {MAX_DIMENSIONE_FILE // 1_000_000}MB)."
        )

    content_hash = hashlib.sha256(contenuto).hexdigest()
    per_hash = await memoria_db.find_documento_by_hash(tenant_id, content_hash)
    if per_hash is not None:
        # Vero duplicato: stesso contenuto, anche da una fonte diversa
        # (dedup cross-origine, es. stesso PDF via mail e via Drive).
        return f"Documento già presente in memoria (id {per_hash['id']}), non re-importato."

    per_source = await memoria_db.find_documento_by_source(tenant_id, fonte, source_id)
    testo, estrazione = await _estrai_testo_e_campi(contenuto, mime_type)
    testo = _sanitizza_testo(testo)
    tipo_documento = estrazione.get("tipo_documento", "altro")

    if per_source is not None:
        # Stesso source_id (es. stesso file Drive) ma hash diverso: il file è
        # stato modificato e re-importato. Non un duplicato da ignorare (dati
        # ormai vecchi) né un nuovo documento (violerebbe il vincolo unico su
        # source_id) - si aggiorna lo stesso record: nuovo hash/contenuto,
        # chunk rigenerati, file su Storage sovrascritto.
        documento_id = per_source["id"]
        await memoria_db.update_documento(tenant_id, documento_id, content_hash, tipo_documento, None)
        await memoria_db.elimina_chunk_documento(tenant_id, documento_id)
    else:
        documento_id = await memoria_db.insert_documento(
            tenant_id, fonte, source_id, content_hash, tipo_documento, None
        )

    storage_path = storage.path_storage(tenant_id, documento_id, nome_file)
    await storage.carica_file(storage_path, contenuto, mime_type)
    await memoria_db.set_storage_path(tenant_id, documento_id, storage_path)

    chunk_testi = chunking.spezza_in_chunk(testo)
    if chunk_testi:
        vettori = await embeddings.embed_documenti(chunk_testi)
        for indice, (testo_chunk, embedding) in enumerate(zip(chunk_testi, vettori)):
            await memoria_db.insert_chunk(tenant_id, documento_id, indice, testo_chunk, embedding)

    verbo = "aggiornato (contenuto cambiato dall'ultimo import)" if per_source is not None else "importato"
    entity_nome = estrazione.get("entity_nome")
    if entity_nome:
        await _aggiorna_fatto_documento(
            tenant_id, entity_nome, estrazione.get("entity_tipo", "fornitore"),
            documento_id, tipo_documento, estrazione.get("campi", {}),
        )
        return (
            f"Documento {verbo} (id {documento_id}, tipo {tipo_documento}): "
            f"ricercabile in memoria e collegato all'entità '{entity_nome}'."
        )
    return f"Documento {verbo} (id {documento_id}, tipo {tipo_documento}): ricercabile in memoria."
