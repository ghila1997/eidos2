"""Helper condiviso per chiamate PostgREST con service role key.

Usato da più moduli oltre Fondamenta (memoria, orchestratore) per evitare di
duplicare tre volte la stessa lettura di env var e gli stessi header HTTP.
Fondamenta (codice/fondamenta/supabase_client.py) resta com'è: gestisce
anche Auth, non solo PostgREST, e non tocchiamo un modulo già validato.
"""
from __future__ import annotations

import os


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
