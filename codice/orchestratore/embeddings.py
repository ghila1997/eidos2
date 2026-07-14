"""Embedding via Voyage AI (partner ufficiale Anthropic per gli embedding -
vedi design Tappa 2, decisione "provider embedding"). Dimensione del modello
(1024) deve combaciare con la colonna vector(1024) della migration.
"""
from __future__ import annotations

import os

import httpx

MODEL = "voyage-3"
DIMENSIONI = 1024

_API_URL = "https://api.voyageai.com/v1/embeddings"


async def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    api_key = os.environ["VOYAGE_API_KEY"]
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": texts, "model": MODEL, "input_type": input_type},
        )
    resp.raise_for_status()
    body = resp.json()
    return [row["embedding"] for row in sorted(body["data"], key=lambda r: r["index"])]


async def embed_documenti(chunk_texts: list[str]) -> list[list[float]]:
    """Embedding di chunk da salvare in memoria_chunk_embedding."""
    return await _embed(chunk_texts, input_type="document")


async def embed_query(testo: str) -> list[float]:
    """Embedding di una query di ricerca (es. da search_emails)."""
    risultati = await _embed([testo], input_type="query")
    return risultati[0]
