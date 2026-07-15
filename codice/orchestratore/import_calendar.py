"""Pipeline di import eventi calendario **conclusi** in Memoria (comando
on-demand, vedi ROADMAP.md Tappa 4 - il polling continuo è Tappa 10, riuserà
questa stessa funzione). Solo eventi già conclusi (fine < adesso): quelli
futuri/in corso restano query live (calendar_client.cerca_eventi, usato dal
tool search_events) - vedi DECISIONS.md 2026-07-15, "Tappa 4: Memoria —
lettura unificata, scrittura esplicita, calendario vivo vs concluso".

Fetch (syncToken incrementale, tutti i calendari) -> filtra conclusi ->
dedup -> chunk+embedding+salva. Nessuna classificazione (a differenza di
import_mail.py): un evento sul calendario del founder non ha spam/newsletter
da filtrare, tutto è potenzialmente rilevante.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from memoria import db as memoria_db

from . import calendar_client, chunking, embeddings

SOURCE_TYPE_CALENDAR_EVENT = "calendar_event"


def _testo_evento(evento: dict) -> str:
    partecipanti = ", ".join(evento.get("partecipanti", []))
    return (
        f"{evento['titolo']}\n"
        f"Quando: {evento['inizio']} - {evento['fine']}\n"
        f"Luogo: {evento.get('luogo', '')}\n"
        f"Partecipanti: {partecipanti}\n\n"
        f"{evento.get('descrizione', '')}"
    ).strip()


def _e_concluso(evento: dict) -> bool:
    fine = evento["fine"]
    try:
        if len(fine) == 10:  # solo data (evento giornata intera): "YYYY-MM-DD"
            fine_dt = datetime.fromisoformat(fine).replace(tzinfo=timezone.utc)
        else:
            fine_dt = datetime.fromisoformat(fine.replace("Z", "+00:00"))
    except ValueError:
        return False
    return fine_dt < datetime.now(timezone.utc)


async def esegui_import(tenant_id: str) -> dict[str, int]:
    access_token = await calendar_client.ottieni_access_token(tenant_id)
    calendari = await calendar_client.lista_calendari(access_token)

    importati = 0
    scartati_futuri = 0
    duplicati = 0
    cancellati = 0

    for calendario in calendari:
        source_type_cursore = f"{SOURCE_TYPE_CALENDAR_EVENT}:{calendario['id']}"
        cursore = await memoria_db.get_import_cursore(tenant_id, source_type_cursore)
        eventi_grezzi, nuovo_cursore = await calendar_client.sincronizza_eventi(
            access_token, calendario["id"], cursore
        )

        for item in eventi_grezzi:
            if item.get("status") == "cancelled":
                cancellati += 1
                continue
            evento = calendar_client.estrai_evento(item, calendario["nome"])
            if not _e_concluso(evento):
                scartati_futuri += 1
                continue

            testo = _testo_evento(evento)
            content_hash = hashlib.sha256(testo.encode("utf-8")).hexdigest()
            gia_visto = await memoria_db.find_documento_by_hash(
                tenant_id, content_hash
            ) or await memoria_db.find_documento_by_source(
                tenant_id, SOURCE_TYPE_CALENDAR_EVENT, evento["event_id"]
            )
            if gia_visto is not None:
                duplicati += 1
                continue

            documento_id = await memoria_db.insert_documento(
                tenant_id, SOURCE_TYPE_CALENDAR_EVENT, evento["event_id"], content_hash,
                None, None,
            )
            chunk_testi = chunking.spezza_in_chunk(testo)
            if chunk_testi:
                vettori = await embeddings.embed_documenti(chunk_testi)
                for indice, (chunk_testo, embedding) in enumerate(zip(chunk_testi, vettori)):
                    await memoria_db.insert_chunk(tenant_id, documento_id, indice, chunk_testo, embedding)
            importati += 1

        if nuovo_cursore:
            await memoria_db.set_import_cursore(tenant_id, source_type_cursore, nuovo_cursore)

    return {
        "importati": importati,
        "scartati_futuri": scartati_futuri,
        "duplicati": duplicati,
        "cancellati": cancellati,
    }
