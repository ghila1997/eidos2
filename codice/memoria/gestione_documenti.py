"""Ciclo di vita dei documenti importati (Tappa 5.1): elencare, rivedere
(metadati + link firmato temporaneo all'originale su Storage), dimenticare.
Prima di questo modulo l'archivio era in sola scrittura: si importava ma
non si poteva né consultare l'elenco, né riavere l'originale, né eliminare
un documento (requisito anche di privacy per un prodotto vendibile).

"Dimenticare" rimuove TUTTO: riga in memoria_documenti (i chunk seguono
via FK cascade), file originale su Storage, e la voce nell'array
'documenti' dei fatti collegati (una voce orfana mostrerebbe per sempre
campi di un documento eliminato) con re-indicizzazione del fatto.
Riguarda SOLO i documenti importati via import_document - mail/eventi/
fatti indicizzati hanno altri cicli di vita.
"""
from __future__ import annotations

from memoria import db as memoria_db
from memoria import fatti_indicizzazione

from . import storage
from .ingest_documento import FONTI


class ErroreGestioneDocumento(Exception):
    """Errore atteso (documento inesistente, non importato) - non un bug."""


def _nome_file(documento: dict) -> str:
    if documento.get("storage_path"):
        return documento["storage_path"].rsplit("/", 1)[-1]
    return documento["source_id"]


async def elenca_documenti(tenant_id: str) -> str:
    documenti = await memoria_db.list_documenti_importati(tenant_id)
    if not documenti:
        return "Nessun documento importato in memoria."
    righe = []
    for d in documenti:
        riga = (
            f"- [{d['id']}] {_nome_file(d)} — tipo {d.get('categoria') or 'altro'}, "
            f"fonte {d['source_type']}, importato il {d['created_at'][:10]}"
        )
        if d.get("stato") != "completo":
            riga += " (import incompleto: re-importalo per renderlo ricercabile)"
        righe.append(riga)
    return "Documenti importati in memoria:\n" + "\n".join(righe)


async def _documento_importato(tenant_id: str, documento_id: str) -> dict:
    documento = await memoria_db.get_documento(tenant_id, documento_id)
    if documento is None or documento["source_type"] not in FONTI:
        raise ErroreGestioneDocumento(
            f"Documento {documento_id} non trovato tra i documenti importati "
            "(usa list_documents per vedere quelli disponibili)."
        )
    return documento


async def descrivi_documento(tenant_id: str, documento_id: str) -> str:
    documento = await _documento_importato(tenant_id, documento_id)
    righe = [
        f"Documento {documento['id']}:",
        f"- nome file: {_nome_file(documento)}",
        f"- tipo: {documento.get('categoria') or 'altro'}",
        f"- fonte: {documento['source_type']} ({documento['source_id']})",
        f"- importato il: {documento['created_at'][:10]}",
    ]
    if documento.get("storage_path"):
        url_firmato = await storage.crea_url_firmato(documento["storage_path"])
        righe.append(f"- originale scaricabile (link valido 1 ora): {url_firmato}")
    return "\n".join(righe)


async def dimentica_documento(tenant_id: str, documento_id: str) -> str:
    documento = await _documento_importato(tenant_id, documento_id)

    if documento.get("storage_path"):
        await storage.elimina_file(documento["storage_path"])

    fatti = await memoria_db.find_fatti_con_documento(tenant_id, documento_id)
    for fatto in fatti:
        data = dict(fatto["data"])
        data["documenti"] = [
            d for d in data.get("documenti", []) if d.get("documento_id") != documento_id
        ]
        await memoria_db.upsert_fatto(tenant_id, fatto["entity_key"], fatto["entity_type"], data)
        await fatti_indicizzazione.reindicizza_fatto(
            tenant_id, fatto["entity_key"], fatto["entity_type"], data
        )

    await memoria_db.delete_documento(tenant_id, documento_id)
    return (
        f"Documento '{_nome_file(documento)}' (id {documento_id}) dimenticato: "
        "rimosso dalla ricerca, dall'archivio e dai fatti collegati."
    )
