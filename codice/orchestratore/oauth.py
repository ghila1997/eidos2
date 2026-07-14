"""OAuth Google per Gmail: lettura+invio come un'unica capacità in questa
tappa (vedi design Tappa 2 - il principio "OAuth per singola capacità" delle
idee salvate su Connettori Cloud si applica in pieno da Tappa 4 in poi, con
più fornitori; qui Gmail è l'unica fonte). State firmato con HMAC (CSRF),
refresh token cifrato con Fernet prima di finire nel DB - mai in chiaro.
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

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify "
    "https://www.googleapis.com/auth/gmail.labels"
)
_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_MAX_AGE_SECONDS = 600

PROVIDER_GMAIL = "gmail"


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


def costruisci_url_autorizzazione(tenant_id: str) -> str:
    redirect_base = os.environ["EIDOS_OAUTH_REDIRECT_BASE_URL"].rstrip("/")
    params = {
        "client_id": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_ID"],
        "redirect_uri": f"{redirect_base}/oauth/google/callback",
        "response_type": "code",
        "scope": GMAIL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": genera_state(tenant_id),
    }
    return f"{_AUTHORIZE_URL}?{urlencode(params)}"


async def scambia_codice(code: str) -> dict:
    redirect_base = os.environ["EIDOS_OAUTH_REDIRECT_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["EIDOS_OAUTH_GOOGLE_CLIENT_SECRET"],
                "redirect_uri": f"{redirect_base}/oauth/google/callback",
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
