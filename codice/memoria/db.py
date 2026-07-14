"""Accesso PostgREST alle tabelle di Memoria (vedi migration
20260713180000_memoria_orchestratore.sql). Tre modi di ricordare: poche
righe sempre caricate (preferenze), fatti strutturati per entità (upsert per
entity_key), ricerca semantica su documenti (pgvector via RPC match_chunks).
"""
from __future__ import annotations

from typing import Any

import httpx

from common.supabase_rest import rest_headers, supabase_settings

# Bound esplicito sulle preferenze sempre caricate in ogni sessione: la Tappa
# 2 le vuole "poche righe", non un file che cresce senza limite.
MAX_PREFERENZE = 50


async def get_preferenze(tenant_id: str) -> dict[str, str]:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/memoria_preferenze",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "select": "chiave,valore",
                "limit": str(MAX_PREFERENZE),
            },
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    return {row["chiave"]: row["valore"] for row in resp.json()}


async def set_preferenza(tenant_id: str, chiave: str, valore: str) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/memoria_preferenze",
            params={"on_conflict": "tenant_id,chiave"},
            headers={**rest_headers(key), "Prefer": "resolution=merge-duplicates"},
            json={"tenant_id": tenant_id, "chiave": chiave, "valore": valore},
        )
    resp.raise_for_status()


async def upsert_fatto(
    tenant_id: str, entity_key: str, entity_type: str, data: dict[str, Any]
) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/memoria_fatti",
            params={"on_conflict": "tenant_id,entity_key"},
            headers={**rest_headers(key), "Prefer": "resolution=merge-duplicates"},
            json={
                "tenant_id": tenant_id,
                "entity_key": entity_key,
                "entity_type": entity_type,
                "data": data,
            },
        )
    resp.raise_for_status()


async def get_fatto(tenant_id: str, entity_key: str) -> dict | None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/memoria_fatti",
            params={"tenant_id": f"eq.{tenant_id}", "entity_key": f"eq.{entity_key}"},
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def find_documento_by_hash(tenant_id: str, content_hash: str) -> dict | None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/memoria_documenti",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "content_hash": f"eq.{content_hash}",
            },
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def find_documento_by_source(
    tenant_id: str, source_type: str, source_id: str
) -> dict | None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/memoria_documenti",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "source_type": f"eq.{source_type}",
                "source_id": f"eq.{source_id}",
            },
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def insert_documento(
    tenant_id: str,
    source_type: str,
    source_id: str,
    content_hash: str,
    categoria: str,
    priorita: str,
) -> str:
    """Inserisce il documento sorgente. Il chiamante deve aver già verificato
    che non esiste (find_documento_by_hash / find_documento_by_source) —
    dedup cross-origine è una decisione applicativa, non lasciata a un solo
    vincolo DB (vedi idea salvata su Memoria in notes/)."""
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/memoria_documenti",
            headers={**rest_headers(key), "Prefer": "return=representation"},
            json={
                "tenant_id": tenant_id,
                "source_type": source_type,
                "source_id": source_id,
                "content_hash": content_hash,
                "categoria": categoria,
                "priorita": priorita,
            },
        )
    resp.raise_for_status()
    return resp.json()[0]["id"]


async def insert_chunk(
    tenant_id: str,
    documento_id: str,
    chunk_index: int,
    chunk_text: str,
    embedding: list[float],
) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/memoria_chunk_embedding",
            headers=rest_headers(key),
            json={
                "tenant_id": tenant_id,
                "documento_id": documento_id,
                "chunk_index": chunk_index,
                "chunk_text": chunk_text,
                "embedding": embedding,
            },
        )
    resp.raise_for_status()


async def match_chunks(
    tenant_id: str, query_embedding: list[float], match_count: int = 5
) -> list[dict]:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/rpc/match_chunks",
            headers=rest_headers(key),
            json={
                "query_embedding": query_embedding,
                "p_tenant_id": tenant_id,
                "match_count": match_count,
            },
        )
    resp.raise_for_status()
    return resp.json()


async def get_import_cursore(tenant_id: str, source_type: str) -> str | None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/memoria_import_cursore",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "source_type": f"eq.{source_type}",
                "select": "cursore",
            },
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0]["cursore"] if rows else None


async def set_import_cursore(tenant_id: str, source_type: str, cursore: str) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/memoria_import_cursore",
            params={"on_conflict": "tenant_id,source_type"},
            headers={**rest_headers(key), "Prefer": "resolution=merge-duplicates"},
            json={
                "tenant_id": tenant_id,
                "source_type": source_type,
                "cursore": cursore,
            },
        )
    resp.raise_for_status()


async def get_sessione_agent(tenant_id: str) -> str | None:
    """Session id dell'Agent SDK da riprendere tra richieste HTTP separate
    (vedi orchestratore/router.py). Nota: la persistenza del *contenuto*
    della conversazione resta quella di default dell'SDK (disco locale del
    container) - se il container viene rideployato a metà conversazione, la
    sessione si perde e si riparte da una nuova (nessun dato di Memoria
    coinvolto, solo il contesto conversazionale). Limite noto, accettato per
    la prima istanza - vedi DECISIONS.md."""
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/orchestratore_sessione",
            params={"tenant_id": f"eq.{tenant_id}", "select": "session_id"},
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0]["session_id"] if rows else None


async def set_sessione_agent(tenant_id: str, session_id: str) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/orchestratore_sessione",
            params={"on_conflict": "tenant_id"},
            headers={**rest_headers(key), "Prefer": "resolution=merge-duplicates"},
            json={"tenant_id": tenant_id, "session_id": session_id},
        )
    resp.raise_for_status()
