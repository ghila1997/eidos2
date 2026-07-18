"""OAuth Google generico: state firmato (CSRF), scambio/refresh token,
cifratura credenziali, storage per tenant+provider. Nessuna costante
specifica di una capacità (scope, redirect path) - quelle vivono nei moduli
per provider (oauth.py per Gmail, oauth_calendar.py per Calendar), vedi
DECISIONS.md 2026-07-15 "Connettori multi-provider".

Split da oauth.py quando è arrivato il secondo provider OAuth (Calendar,
Tappa 4) - rimandato consapevolmente in Tappa 2/3 perché con un solo
provider la mescolanza non causava ancora danno reale (vedi DECISIONS.md
2026-07-14, "Autorizzazioni").
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet

from common.supabase_rest import rest_headers, supabase_settings

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_MAX_AGE_SECONDS = 600


class StatoNonValido(Exception):
    """Lo state ricevuto nel callback OAuth non è valido o è scaduto."""


def _firma_state(tenant_id: str, timestamp: str) -> str:
    secret = os.environ["EIDOS_OAUTH_STATE_SECRET"].encode()
    msg = f"{tenant_id}:{timestamp}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def genera_state(tenant_id: str) -> str:
    timestamp = str(int(time.time()))
    firma = _firma_state(tenant_id, timestamp)
    payload = f"{tenant_id}:{timestamp}:{firma}"
    return base64.urlsafe_b64encode(payload.encode()).decode()


def verifica_state(state: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(state.encode()).decode()
        tenant_id, timestamp, firma = payload.split(":")
    except Exception as exc:
        raise StatoNonValido("state malformato") from exc

    if not hmac.compare_digest(firma, _firma_state(tenant_id, timestamp)):
        raise StatoNonValido("firma state non valida")
    if time.time() - int(timestamp) > _STATE_MAX_AGE_SECONDS:
        raise StatoNonValido("state scaduto")
    return tenant_id


def costruisci_url_autorizzazione(tenant_id: str, scope: str, redirect_path: str) -> str:
    """`redirect_path` es. "/oauth/google/callback" o
    "/oauth/google_calendar/callback" - deve combaciare esattamente con
    quello passato a `scambia_codice` per lo stesso flusso, e con quanto
    registrato nella console Google Cloud. `include_granted_scopes` abilita
    l'autorizzazione incrementale: collegare Calendar non richiede di
    riconcedere lo scope Gmail già ottenuto in Tappa 2."""
    redirect_base = os.environ["EIDOS_OAUTH_REDIRECT_BASE_URL"].rstrip("/")
    params = {
        "client_id": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_ID"],
        "redirect_uri": f"{redirect_base}{redirect_path}",
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": genera_state(tenant_id),
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def scambia_codice(code: str, redirect_path: str) -> dict:
    redirect_base = os.environ["EIDOS_OAUTH_REDIRECT_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_SECRET"],
                "redirect_uri": f"{redirect_base}{redirect_path}",
                "grant_type": "authorization_code",
            },
        )
    resp.raise_for_status()
    return resp.json()


async def rinnova_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_SECRET"],
                "grant_type": "refresh_token",
            },
        )
    resp.raise_for_status()
    return resp.json()


def cifra_refresh_token(refresh_token: str) -> str:
    fernet = Fernet(os.environ["EIDOS_CREDENTIAL_ENCRYPTION_KEY"].encode())
    return fernet.encrypt(refresh_token.encode()).decode()


def decifra_refresh_token(token_cifrato: str) -> str:
    fernet = Fernet(os.environ["EIDOS_CREDENTIAL_ENCRYPTION_KEY"].encode())
    return fernet.decrypt(token_cifrato.encode()).decode()


async def salva_credenziale(tenant_id: str, provider: str, scope: str, refresh_token: str) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/oauth_credenziali",
            params={"on_conflict": "tenant_id,provider"},
            headers={**rest_headers(key), "Prefer": "resolution=merge-duplicates"},
            json={
                "tenant_id": tenant_id,
                "provider": provider,
                "scope": scope,
                "refresh_token_cifrato": cifra_refresh_token(refresh_token),
            },
        )
    resp.raise_for_status()


async def get_credenziale(tenant_id: str, provider: str) -> dict | None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/oauth_credenziali",
            params={"tenant_id": f"eq.{tenant_id}", "provider": f"eq.{provider}"},
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


# Cache in-memory dell'access token, per (tenant_id, provider). Perché: ogni
# chiamata a un tool Calendar/Drive/Gmail rifaceva Supabase + refresh Google
# da zero (~1,6s misurati, STOP 2 Tappa 6 2026-07-19), anche a token ancora
# valido - un access token Google dura ~1h. Margine di sicurezza: si rinnova
# un po' prima della scadenza esatta, mai al limite.
_CACHE_ACCESS_TOKEN: dict[tuple[str, str], tuple[str, float]] = {}
_MARGINE_SICUREZZA_SECONDI = 60.0


async def access_token_valido(tenant_id: str, provider: str) -> str | None:
    """None = nessuna credenziale collegata (il chiamante solleva il suo
    errore specifico con l'URL di autorizzazione giusto per il provider)."""
    chiave = (tenant_id, provider)
    in_cache = _CACHE_ACCESS_TOKEN.get(chiave)
    if in_cache is not None and time.monotonic() < in_cache[1]:
        return in_cache[0]

    credenziale = await get_credenziale(tenant_id, provider)
    if credenziale is None:
        return None
    refresh_token = decifra_refresh_token(credenziale["refresh_token_cifrato"])
    tokens = await rinnova_access_token(refresh_token)
    scadenza = time.monotonic() + tokens.get("expires_in", 3600) - _MARGINE_SICUREZZA_SECONDI
    _CACHE_ACCESS_TOKEN[chiave] = (tokens["access_token"], scadenza)
    return tokens["access_token"]
