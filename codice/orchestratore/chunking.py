"""Suddivisione testo in chunk per l'embedding. Dimensione in caratteri, non
token: approssimazione accettabile per la prima istanza (Tappa 2)."""
from __future__ import annotations

DIMENSIONE_CHUNK = 1500
SOVRAPPOSIZIONE = 200


def spezza_in_chunk(testo: str) -> list[str]:
    testo = testo.strip()
    if not testo:
        return []
    if len(testo) <= DIMENSIONE_CHUNK:
        return [testo]

    chunk = []
    inizio = 0
    while inizio < len(testo):
        fine = inizio + DIMENSIONE_CHUNK
        chunk.append(testo[inizio:fine])
        if fine >= len(testo):
            break
        inizio = fine - SOVRAPPOSIZIONE
    return chunk
