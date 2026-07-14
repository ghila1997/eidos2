"""Client Gmail API: fetch mail per l'ingest, invio/bozza per i tool
dell'Orchestratore. Nessun SDK Google pesante - httpx puro, coerente con
codice/fondamenta/supabase_client.py."""
from __future__ import annotations

import base64
import time
from email.mime.text import MIMEText
from typing import Any

import httpx

from . import oauth

_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(Exception):
    """Errore nella chiamata a Gmail API."""


async def ottieni_access_token(tenant_id: str) -> str:
    credenziale = await oauth.get_credenziale(tenant_id, oauth.PROVIDER_GMAIL)
    if credenziale is None:
        raise GmailError(
            "Nessuna credenziale Gmail collegata per questo tenant: "
            "serve prima /oauth/google/authorize"
        )
    refresh_token = oauth.decifra_refresh_token(credenziale["refresh_token_cifrato"])
    tokens = await oauth.rinnova_access_token(refresh_token)
    return tokens["access_token"]


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def lista_messaggi_nuovi(
    access_token: str, cursore: str | None
) -> tuple[list[str], str]:
    """Ritorna (id messaggi nuovi, nuovo cursore). Cursore = timestamp unix
    dell'ultimo import; usa la ricerca Gmail "after:" per l'incrementale."""
    query = f"after:{cursore}" if cursore else None
    params = {"maxResults": "50"}
    if query:
        params["q"] = query

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/messages", params=params, headers=_headers(access_token)
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.list fallita: {resp.status_code}")
    body = resp.json()
    ids = [m["id"] for m in body.get("messages", [])]
    return ids, str(int(time.time()))


def _estrai_corpo(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode(
            "utf-8", errors="replace"
        )
    for parte in payload.get("parts", []):
        corpo = _estrai_corpo(parte)
        if corpo:
            return corpo
    return ""


async def ottieni_messaggio(access_token: str, message_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_BASE}/messages/{message_id}",
            params={"format": "full"},
            headers=_headers(access_token),
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.get fallita: {resp.status_code}")
    body = resp.json()
    headers = {h["name"].lower(): h["value"] for h in body["payload"].get("headers", [])}
    corpo = _estrai_corpo(body["payload"]) or body.get("snippet", "")
    return {
        "message_id": message_id,
        "mittente": headers.get("from", ""),
        "oggetto": headers.get("subject", ""),
        "corpo": corpo,
    }


def _messaggio_raw(destinatario: str, oggetto: str, corpo: str) -> str:
    msg = MIMEText(corpo)
    msg["to"] = destinatario
    msg["subject"] = oggetto
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


async def invia_messaggio(access_token: str, destinatario: str, oggetto: str, corpo: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/messages/send",
            headers=_headers(access_token),
            json={"raw": _messaggio_raw(destinatario, oggetto, corpo)},
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail messages.send fallita: {resp.status_code}")
    return resp.json()


async def crea_bozza(access_token: str, destinatario: str, oggetto: str, corpo: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_BASE}/drafts",
            headers=_headers(access_token),
            json={"message": {"raw": _messaggio_raw(destinatario, oggetto, corpo)}},
        )
    if resp.status_code != 200:
        raise GmailError(f"Gmail drafts.create fallita: {resp.status_code}")
    return resp.json()
