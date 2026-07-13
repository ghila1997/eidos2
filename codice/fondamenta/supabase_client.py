"""Client minimo verso le API REST di Supabase (Auth + PostgREST).

Nessun JWT verificato localmente: Supabase resta l'unica autorità su identità
e sessioni, coerente con la decisione in DECISIONS.md di non reintrodurre un
flusso di sessione custom.
"""
from __future__ import annotations

import os

import httpx


class SupabaseAuthError(Exception):
    """Credenziali o token rifiutati da Supabase."""


def _settings() -> tuple[str, str, str]:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    service_role_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return url, anon_key, service_role_key


async def sign_in_with_password(email: str, password: str) -> dict:
    url, anon_key, _ = _settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": anon_key, "Content-Type": "application/json"},
            json={"email": email, "password": password},
        )
    if resp.status_code != 200:
        raise SupabaseAuthError(f"login rifiutato da Supabase: {resp.status_code}")
    return resp.json()


async def get_user(access_token: str) -> dict:
    url, anon_key, _ = _settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/auth/v1/user",
            headers={"apikey": anon_key, "Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise SupabaseAuthError(f"token rifiutato da Supabase: {resp.status_code}")
    return resp.json()


async def get_tenant_membership(user_id: str) -> dict | None:
    """Legge la riga tenant_members dell'utente usando la service role key
    (bypassa RLS: chiamata server-side, mai esposta al client)."""
    url, _, service_role_key = _settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/tenant_members",
            params={"user_id": f"eq.{user_id}", "select": "tenant_id,role"},
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
            },
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None
