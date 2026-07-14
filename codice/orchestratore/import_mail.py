"""Pipeline di ingest mail (comando on-demand, vedi ROADMAP.md Tappa 2 - il
polling continuo è Tappa 10/Automazioni e riuserà questa stessa funzione,
invocata dallo scheduler invece che a mano).

Fetch Gmail -> dedup -> classifica (Haiku) -> se ingest: chunk+embedding+
salva. Nessun agente/subagent coinvolto: pipeline lineare con una singola
chiamata LLM di classificazione per mail (vedi classification.py).
"""
from __future__ import annotations

import hashlib

from memoria import db as memoria_db

from . import chunking, classification, embeddings, gmail_client

SOURCE_TYPE_GMAIL = "gmail"


async def esegui_import(tenant_id: str) -> dict[str, int]:
    access_token = await gmail_client.ottieni_access_token(tenant_id)
    cursore = await memoria_db.get_import_cursore(tenant_id, SOURCE_TYPE_GMAIL)
    ids, nuovo_cursore = await gmail_client.lista_messaggi_nuovi(access_token, cursore)

    importati = 0
    scartati = 0
    duplicati = 0

    for message_id in ids:
        msg = await gmail_client.ottieni_messaggio(access_token, message_id)
        content_hash = hashlib.sha256(msg["corpo"].encode("utf-8")).hexdigest()

        gia_visto = await memoria_db.find_documento_by_hash(
            tenant_id, content_hash
        ) or await memoria_db.find_documento_by_source(
            tenant_id, SOURCE_TYPE_GMAIL, message_id
        )
        if gia_visto is not None:
            duplicati += 1
            continue

        classificazione = await classification.classifica_mail(
            msg["mittente"], msg["oggetto"], msg["corpo"]
        )
        if not classificazione["ingest"]:
            scartati += 1
            continue

        documento_id = await memoria_db.insert_documento(
            tenant_id,
            SOURCE_TYPE_GMAIL,
            message_id,
            content_hash,
            classificazione["categoria"],
            classificazione["priorita"],
        )
        chunk_testi = chunking.spezza_in_chunk(msg["corpo"])
        if chunk_testi:
            vettori = await embeddings.embed_documenti(chunk_testi)
            for indice, (testo, embedding) in enumerate(zip(chunk_testi, vettori)):
                await memoria_db.insert_chunk(tenant_id, documento_id, indice, testo, embedding)
        importati += 1

    await memoria_db.set_import_cursore(tenant_id, SOURCE_TYPE_GMAIL, nuovo_cursore)
    return {
        "totale": len(ids),
        "importati": importati,
        "scartati": scartati,
        "duplicati": duplicati,
    }
