"""Re-indicizzazione del chunk embedded di un fatto (memoria_fatti), per
tenerlo allineato allo stato corrente dopo ogni modifica. Condivisa tra
ingest_documento.py (aggiunta/aggiornamento della voce di un documento) e
gestione_documenti.py (rimozione della voce quando un documento viene
dimenticato). Il flusso gemello di remember_fact resta in
orchestratore/tools.py, non toccato (codice Tappa 2/4 gia' validato, vedi
CLAUDE.md) - stesso formato di testo, cosi' la ricerca resta coerente.
"""
from __future__ import annotations

import hashlib

from memoria import db as memoria_db
from orchestratore import embeddings


def _testo_fatto(data: dict) -> str:
    note = data.get("note", [])
    documenti = data.get("documenti", [])
    testo = f"{data.get('nome', '')}: " + " | ".join(n["testo"] for n in note)
    if documenti:
        testo += " | " + " | ".join(
            f"{d['tipo_documento']} ({d['documento_id']}): {d['campi']}" for d in documenti
        )
    return testo


async def reindicizza_fatto(tenant_id: str, entity_key: str, entity_tipo: str, data: dict) -> None:
    """Rigenera il chunk embedded del fatto (source_type "fatto") - i fatti
    cambiano nel tempo, il loro embedding non deve accumulare versioni
    superate ne' conservare voci di documenti rimossi."""
    testo = _testo_fatto(data)
    documento = await memoria_db.find_documento_by_source(tenant_id, "fatto", entity_key)
    if documento is None:
        content_hash = hashlib.sha256(testo.encode("utf-8")).hexdigest()
        documento_id = await memoria_db.insert_documento(
            tenant_id, "fatto", entity_key, content_hash, entity_tipo, None
        )
    else:
        documento_id = documento["id"]
        await memoria_db.elimina_chunk_documento(tenant_id, documento_id)
    embedding = (await embeddings.embed_documenti([testo]))[0]
    await memoria_db.insert_chunk(tenant_id, documento_id, 0, testo, embedding)
