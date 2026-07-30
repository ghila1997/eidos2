"""Azioni distruttive in attesa di conferma umana, fuori dal controllo del
modello (vedi CLAUDE.md). Il tool `send_email` (tools.py) scrive qui e si
ferma: SOLO `conferma_azione`, chiamata da un endpoint separato invocato
direttamente dall'utente (mai dal modello), esegue l'azione reale.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from common.supabase_rest import client as _supabase_client
from common.supabase_rest import rest_headers, supabase_settings
from memoria import db as memoria_db
from memoria import gestione_documenti
from memoria.entity_resolution import slug_entity
from . import calendar_client, drive_client, gmail_client

TIPO_SEND_EMAIL = "send_email"
TIPO_REPLY_EMAIL = "reply_email"
TIPO_FORWARD_EMAIL = "forward_email"
TIPO_SEND_DRAFT = "send_draft"
TIPO_TRASH_EMAIL = "trash_email"
TIPO_CREATE_EVENT = "create_event"
TIPO_UPDATE_EVENT = "update_event"
TIPO_DELETE_EVENT = "delete_event"
TIPO_SHARE_FILE = "share_file"
TIPO_TRASH_FILE = "trash_file"
TIPO_FORGET_DOCUMENT = "forget_document"
TIPO_PROPOSE_COMMITMENT = "propose_commitment"
TIPO_CLOSE_COMMITMENT = "close_commitment"

STATO_IN_ATTESA = "in_attesa"
STATO_INVIATA = "confermata_inviata"
STATO_RIFIUTATA = "rifiutata"
STATO_ERRORE = "confermata_errore"
STATO_SCADUTA = "scaduta"

# Una scheda di conferma lasciata lì non deve poter partire ore dopo, quando il
# contesto non c'è più (Tappa 7.2, decisione STOP 1). Scadenza *pigra*: nessun
# job in background (quello è materia di Tappa 10/Attese) - si controlla al volo
# quando si legge o si conferma un'azione, confrontando `created_at` con adesso.
TTL_AZIONE = timedelta(hours=1)


def _parse_ts(valore: str) -> datetime:
    """created_at di Supabase (ISO8601, con 'Z' o offset) -> datetime aware."""
    return datetime.fromisoformat(valore.replace("Z", "+00:00"))


def azione_scaduta(azione: dict[str, Any], adesso: datetime | None = None) -> bool:
    """True se l'azione è più vecchia di TTL_AZIONE. Senza `created_at`
    (payload di test minimali) la si considera non scaduta: la scadenza è una
    rete di sicurezza, non deve mai bloccare un'azione fresca per un timestamp
    mancante."""
    creata = azione.get("created_at")
    if not creata:
        return False
    adesso = adesso or datetime.now(timezone.utc)
    return adesso - _parse_ts(creata) > TTL_AZIONE


class AzioneNonTrovata(Exception):
    """Nessuna azione pending con quell'id per questo tenant."""


class AzioneGiaRisolta(Exception):
    """L'azione non è più in stato 'in_attesa' (già confermata/rifiutata)."""


async def crea_azione_pending(tenant_id: str, tipo: str, payload: dict[str, Any]) -> str:
    url, key = supabase_settings()
    resp = await _supabase_client().post(
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
    resp = await _supabase_client().get(
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


async def azione_bloccante(tenant_id: str) -> dict[str, Any] | None:
    """L'azione pendente che deve bloccare una nuova richiesta - come
    `ottieni_azione_pendente_tenant`, ma se l'unica pendente è **scaduta** la
    marca `scaduta` e non blocca più (scadenza pigra, senza job): così una
    scheda dimenticata non tiene la chat bloccata per sempre."""
    azione = await ottieni_azione_pendente_tenant(tenant_id)
    if azione is None:
        return None
    if azione_scaduta(azione):
        await _aggiorna_stato(azione["id"], STATO_SCADUTA)
        return None
    return azione


async def ottieni_azione(tenant_id: str, azione_id: str) -> dict[str, Any] | None:
    url, key = supabase_settings()
    resp = await _supabase_client().get(
        f"{url}/rest/v1/azioni_pending",
        params={"tenant_id": f"eq.{tenant_id}", "id": f"eq.{azione_id}"},
        headers=rest_headers(key),
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


async def _aggiorna_stato(azione_id: str, stato: str) -> None:
    url, key = supabase_settings()
    resp = await _supabase_client().patch(
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

    # Rete di sicurezza: un "Sì" su una scheda troppo vecchia non spedisce nulla
    # (il contesto potrebbe non valere più) - va richiesta di nuovo.
    if azione_scaduta(azione):
        await _aggiorna_stato(azione_id, STATO_SCADUTA)
        return {"stato": STATO_SCADUTA}

    if azione["tipo"] not in _ESECUTORI:
        raise ValueError(f"tipo azione sconosciuto: {azione['tipo']}")

    payload = azione["payload"]
    try:
        await _ESECUTORI[azione["tipo"]](tenant_id, payload)
    except Exception:
        await _aggiorna_stato(azione_id, STATO_ERRORE)
        raise
    await _aggiorna_stato(azione_id, STATO_INVIATA)

    # Frase di esito per la conferma DAL VIVO nella UI (es. "Mail inviata a X").
    # NON persistita: le azioni fatte non si tengono in cronologia - la verita'
    # di "cosa ho fatto" sta in Gmail/Calendar, si chiede lì (vedi DECISIONS.md
    # 2026-07-29). `descrizioni_azioni` importa `azioni` -> import locale.
    from . import descrizioni_azioni

    return {"stato": STATO_INVIATA, "esito": descrizioni_azioni.esito_azione(azione)}


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


async def _esegui_create_event(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await calendar_client.ottieni_access_token(tenant_id)
    await calendar_client.crea_evento(access_token, **payload)


async def _esegui_update_event(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await calendar_client.ottieni_access_token(tenant_id)
    campi = {k: v for k, v in payload.items() if k not in ("event_id", "notifica", "calendario")}
    await calendar_client.aggiorna_evento(
        access_token, payload["event_id"],
        notifica=payload["notifica"], calendario=payload.get("calendario"), **campi,
    )


async def _esegui_delete_event(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await calendar_client.ottieni_access_token(tenant_id)
    await calendar_client.elimina_evento(
        access_token, payload["event_id"],
        notifica=payload["notifica"], calendario=payload.get("calendario"),
    )


async def _esegui_share_file(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await drive_client.ottieni_access_token(tenant_id)
    await drive_client.condividi_file(
        access_token, payload["file_id"],
        email=payload.get("email"), ruolo=payload["ruolo"], pubblico=payload["pubblico"],
    )


async def _esegui_trash_file(tenant_id: str, payload: dict[str, Any]) -> None:
    access_token = await drive_client.ottieni_access_token(tenant_id)
    await drive_client.cestina_file(access_token, payload["file_id"])


async def _esegui_forget_document(tenant_id: str, payload: dict[str, Any]) -> None:
    await gestione_documenti.dimentica_documento(tenant_id, payload["documento_id"])


async def _esegui_propose_commitment(tenant_id: str, payload: dict[str, Any]) -> None:
    """Unico punto in cui un impegno proposto diventa un fatto scritto in
    memoria_impegni - solo qui, mai in tools.py (vedi DECISIONS.md
    2026-07-15, "scrittura sempre esplicita, mai automatica"). Deduplica:
    stessa entità+fonte già proposta -> non riscrive (vedi contratto STOP 1,
    punto 8)."""
    entity_key = slug_entity(payload["entity_nome"])
    esistente = await memoria_db.trova_impegno_simile(
        tenant_id, entity_key, payload["source_type"], payload["source_id"]
    )
    if esistente is not None:
        return
    await memoria_db.upsert_impegno(
        tenant_id,
        entity_key=entity_key,
        descrizione=payload["descrizione"],
        direzione=payload["direzione"],
        source_type=payload["source_type"],
        source_id=payload["source_id"],
        source_excerpt=payload["source_excerpt"],
        observed_at=payload["observed_at"],
        scadenza=payload.get("scadenza"),
        confidence=payload["confidence"],
    )


async def _esegui_close_commitment(tenant_id: str, payload: dict[str, Any]) -> None:
    await memoria_db.chiudi_impegno(tenant_id, payload["impegno_id"])


_ESECUTORI = {
    TIPO_SEND_EMAIL: _esegui_send_email,
    TIPO_REPLY_EMAIL: _esegui_reply_email,
    TIPO_FORWARD_EMAIL: _esegui_forward_email,
    TIPO_SEND_DRAFT: _esegui_send_draft,
    TIPO_TRASH_EMAIL: _esegui_trash_email,
    TIPO_CREATE_EVENT: _esegui_create_event,
    TIPO_UPDATE_EVENT: _esegui_update_event,
    TIPO_DELETE_EVENT: _esegui_delete_event,
    TIPO_SHARE_FILE: _esegui_share_file,
    TIPO_TRASH_FILE: _esegui_trash_file,
    TIPO_FORGET_DOCUMENT: _esegui_forget_document,
    TIPO_PROPOSE_COMMITMENT: _esegui_propose_commitment,
    TIPO_CLOSE_COMMITMENT: _esegui_close_commitment,
}
