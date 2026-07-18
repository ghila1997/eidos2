"""Helper condiviso per chiamate PostgREST con service role key.

Usato da più moduli oltre Fondamenta (memoria, orchestratore) per evitare di
duplicare tre volte la stessa lettura di env var e gli stessi header HTTP.
Fondamenta (codice/fondamenta/supabase_client.py) resta com'è: gestisce
anche Auth, non solo PostgREST, e non tocchiamo un modulo già validato.
"""
from __future__ import annotations

import os

import httpx

# Client HTTP riusato tra le chiamate PostgREST: un client nuovo a ogni
# richiesta paga l'handshake TLS ogni volta (~0,7s misurati su Google
# Calendar, stesso principio qui) - trovato dominare la latenza di un turno
# vocale (STOP 2 Tappa 6, 2026-07-19), azioni.py chiamato due volte a turno.
_client_condiviso: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client_condiviso
    if _client_condiviso is None:
        _client_condiviso = httpx.AsyncClient(timeout=30.0)
    return _client_condiviso


def supabase_settings() -> tuple[str, str]:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    service_role_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, service_role_key


def rest_headers(service_role_key: str) -> dict:
    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
