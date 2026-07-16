"""Archiviazione del file originale di un documento su Supabase Storage
(bucket privato `documenti`, vedi migration 20260716120000). Solo
service role key, stesso pattern di common/supabase_rest.py - nessun
accesso client-side.
"""
from __future__ import annotations

import httpx

from common.supabase_rest import supabase_settings

BUCKET = "documenti"


def path_storage(tenant_id: str, documento_id: str, nome_file: str) -> str:
    return f"{tenant_id}/{documento_id}/{nome_file}"


async def carica_file(storage_path: str, contenuto: bytes, mime_type: str) -> None:
    """`x-upsert` sempre attivo: un documento aggiornato (stesso source_id,
    contenuto cambiato — vedi ingest_documento.py) riusa lo stesso
    documento_id e quindi lo stesso storage_path. Senza upsert la seconda
    chiamata fallirebbe con 400 (l'oggetto esiste già) - trovato testando
    davvero il percorso di aggiornamento, non solo con mock."""
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/storage/v1/object/{BUCKET}/{storage_path}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": mime_type,
                "x-upsert": "true",
            },
            content=contenuto,
        )
    resp.raise_for_status()
