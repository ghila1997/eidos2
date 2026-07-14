"""Azioni distruttive in attesa di conferma umana, fuori dal controllo del
modello (vedi CLAUDE.md). Il tool `send_email` (tools.py) scrive qui e si
ferma: SOLO `conferma_azione`, chiamata da un endpoint separato invocato
direttamente dall'utente (mai dal modello), esegue l'azione reale.
"""
from __future__ import annotations

from typing import Any

import httpx

from common.supabase_rest import rest_headers, supabase_settings
from . import gmail_client

TIPO_SEND_EMAIL = "send_email"
TIPO_REPLY_EMAIL = "reply_email"
TIPO_FORWARD_EMAIL = "forward_email"
TIPO_SEND_DRAFT = "send_draft"
TIPO_TRASH_EMAIL = "trash_email"

STATO_IN_ATTESA = "in_attesa"
STATO_INVIATA = "confermata_inviata"
STATO_RIFIUTATA = "rifiutata"
STATO_ERRORE = "confermata_errore"


class AzioneNonTrovata(Exception):
    """Nessuna azione pending con quell'id per questo tenant."""


class AzioneGiaRisolta(Exception):
    """L'azione non è più in stato 'in_attesa' (già confermata/rifiutata)."""


async def crea_azione_pending(tenant_id: str, tipo: str, payload: dict[str, Any]) -> str:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/azioni_pending",
            headers={**rest_headers(key), "Prefer": "return=representation"},
            json={"tenant_id": tenant_id, "tipo": tipo, "payload": payload},
        )
    resp.raise_for_status()
    return resp.json()[0]["id"]


async def ottieni_azione_pendente_tenant(tenant_id: str) -> dict[str, Any] | None:
    """Usata dal router /chat: se c'è già un'azione in_attesa per il tenant,
    la chat si blocca finché non viene risolta (conferma o rifiuto) - vedi
    design Tappa 2, "regola pratica" sulla conferma pendente."""
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/azioni_pending",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "stato": f"eq.{STATO_IN_ATTESA}",
                "limit": "1",
            },
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def ottieni_azione(tenant_id: str, azione_id: str) -> dict[str, Any] | None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/azioni_pending",
            params={"tenant_id": f"eq.{tenant_id}", "id": f"eq.{azione_id}"},
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def _aggiorna_stato(azione_id: str, stato: str) -> None:
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{url}/rest/v1/azioni_pending",
            params={"id": f"eq.{azione_id}"},
            headers=rest_headers(key),
            json={"stato": stato},
        )
    resp.raise_for_status()


async def conferma_azione(
    tenant_id: str, azione_id: str, conferma: bool
) -> dict[str, Any]:
    """Punto unico in cui un'azione distruttiva diventa reale. Scoped per
    tenant_id: un'azione di un altro tenant risulta "non trovata", mai
    eseguibile (anti-leak anche qui, non solo sulla lettura dati)."""
    azione = await ottieni_azione(tenant_id, azione_id)
    if azione is None:
        raise AzioneNonTrovata(azione_id)
    if azione["stato"] != STATO_IN_ATTESA:
        raise AzioneGiaRisolta(f"stato attuale: {azione['stato']}")

    if not conferma:
        await _aggiorna_stato(azione_id, STATO_RIFIUTATA)
        return {"stato": STATO_RIFIUTATA}

    if azione["tipo"] not in _ESECUTORI:
        raise ValueError(f"tipo azione sconosciuto: {azione['tipo']}")

    payload = azione["payload"]
    try:
        await _ESECUTORI[azione["tipo"]](tenant_id, payload)
    except Exception:
        await _aggiorna_stato(azione_id, STATO_ERRORE)
        raise
    await _aggiorna_stato(azione_id, STATO_INVIATA)
    return {"stato": STATO_INVIATA}


async def _esegui_send_email(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await gmail_client.ottieni_access_token(tenant_id)
    await gmail_client.invia_messaggio(
        access_token,
        payload["destinatario"],
        payload["oggetto"],
        payload["corpo"],
        cc=payload.get("cc"),
        bcc=payload.get("bcc"),
    )


async def _esegui_reply_email(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await gmail_client.ottieni_access_token(tenant_id)
    await gmail_client.rispondi_messaggio(
        access_token,
        payload["message_id"],
        payload["corpo"],
        destinatario=payload.get("destinatario"),
        cc=payload.get("cc"),
        bcc=payload.get("bcc"),
    )


async def _esegui_forward_email(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await gmail_client.ottieni_access_token(tenant_id)
    await gmail_client.inoltra_messaggio(
        access_token,
        payload["message_id"],
        payload["destinatario"],
        testo_aggiuntivo=payload.get("testo_aggiuntivo", ""),
        cc=payload.get("cc"),
        bcc=payload.get("bcc"),
    )


async def _esegui_send_draft(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await gmail_client.ottieni_access_token(tenant_id)
    await gmail_client.invia_bozza(access_token, payload["draft_id"])


async def _esegui_trash_email(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await gmail_client.ottieni_access_token(tenant_id)
    await gmail_client.cestina_messaggio(access_token, payload["message_id"])


_ESECUTORI = {
    TIPO_SEND_EMAIL: _esegui_send_email,
    TIPO_REPLY_EMAIL: _esegui_reply_email,
    TIPO_FORWARD_EMAIL: _esegui_forward_email,
    TIPO_SEND_DRAFT: _esegui_send_draft,
    TIPO_TRASH_EMAIL: _esegui_trash_email,
}
