"""Azioni distruttive in attesa di conferma umana, fuori dal controllo del
modello (vedi CLAUDE.md). Il tool `send_email` (tools.py) scrive qui e si
ferma: SOLO `conferma_azione`, chiamata da un endpoint separato invocato
direttamente dall'utente (mai dal modello), esegue l'azione reale.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from common.supabase_rest import client as _supabase_client
from common.supabase_rest import rest_headers, supabase_settings
from memoria import db as memoria_db
from memoria import gestione_documenti
from memoria.entity_resolution import slug_entity
from . import calendar_client, drive_client, gmail_client

logger = logging.getLogger(__name__)

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

# Quante azioni di un gruppo si eseguono insieme (vedi `conferma_gruppo`).
# 5: abbastanza da non far sembrare bloccata una scheda da 30 azioni, poco
# abbastanza da non arrivare a Gmail come una raffica.
_PARALLELE_PER_GRUPPO = 5


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


async def ottieni_azioni_pendenti_tenant(tenant_id: str) -> list[dict[str, Any]]:
    """**Tutte** le azioni in attesa del tenant, dalla più vecchia alla più
    recente. Sono sempre un gruppo omogeneo di un solo turno: una nuova
    richiesta è bloccata finché ce n'è anche una sola pendente (vedi
    `azioni_bloccanti` e i suoi chiamanti), quindi non possono mescolarsi
    azioni di turni diversi. Per questo il "gruppo" non ha bisogno di una
    colonna sua: è l'insieme delle `in_attesa` di quel tenant.

    Leggeva `limit=1` (e senza `order`): con 21 `trash_email` in un turno
    l'utente ne vedeva una sola, presa a caso, e le altre 20 riemergevano una
    per messaggio. Vedi ROADMAP.md, fix conferme multiple."""
    url, key = supabase_settings()
    resp = await _supabase_client().get(
        f"{url}/rest/v1/azioni_pending",
        params={
            "tenant_id": f"eq.{tenant_id}",
            "stato": f"eq.{STATO_IN_ATTESA}",
            "order": "created_at.asc",
        },
        headers=rest_headers(key),
    )
    resp.raise_for_status()
    return resp.json()


async def azioni_bloccanti(tenant_id: str) -> list[dict[str, Any]]:
    """Le azioni pendenti che devono bloccare una nuova richiesta - come
    `ottieni_azioni_pendenti_tenant`, ma le **scadute le marca tutte insieme**
    e non le restituisce (scadenza pigra, senza job): così un gruppo
    dimenticato non tiene la chat bloccata per sempre.

    Tutte insieme e non una per volta: le azioni di un gruppo nascono nello
    stesso secondo e quindi scadono insieme; marcarne una per richiesta
    obbligherebbe a mandare 21 messaggi per sbloccare 21 schede."""
    pendenti = await ottieni_azioni_pendenti_tenant(tenant_id)
    scadute = {a["id"] for a in pendenti if azione_scaduta(a)}
    if scadute:
        await _aggiorna_stato_molte(sorted(scadute), STATO_SCADUTA)
    return [a for a in pendenti if a["id"] not in scadute]


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


async def _aggiorna_stato_molte(azione_ids: list[str], stato: str) -> None:
    """Stesso stato su più azioni in una sola PATCH (`id=in.(...)`): scadere un
    gruppo di 21 non deve costare 21 round-trip a Supabase."""
    if not azione_ids:
        return
    url, key = supabase_settings()
    resp = await _supabase_client().patch(
        f"{url}/rest/v1/azioni_pending",
        params={"id": f"in.({','.join(azione_ids)})"},
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

    # `tipo` in uscita serve a chi risolve un gruppo intero (`conferma_gruppo`)
    # per contare per tipo senza rileggere le azioni da Supabase.
    if not conferma:
        await _aggiorna_stato(azione_id, STATO_RIFIUTATA)
        return {"stato": STATO_RIFIUTATA, "tipo": azione["tipo"]}

    # Rete di sicurezza: un "Sì" su una scheda troppo vecchia non spedisce nulla
    # (il contesto potrebbe non valere più) - va richiesta di nuovo.
    if azione_scaduta(azione):
        await _aggiorna_stato(azione_id, STATO_SCADUTA)
        return {"stato": STATO_SCADUTA, "tipo": azione["tipo"]}

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

    return {
        "stato": STATO_INVIATA,
        "tipo": azione["tipo"],
        "esito": descrizioni_azioni.esito_azione(azione),
    }


async def conferma_gruppo(
    tenant_id: str, decisioni: dict[str, bool]
) -> dict[str, Any]:
    """Risolve in un colpo solo le azioni di un gruppo (`{azione_id: sì/no}`).

    Non è una scorciatoia intorno al gate: passa comunque da `conferma_azione`
    per ogni azione, che resta il punto unico in cui una distruttiva diventa
    reale (CLAUDE.md). Quello che cambia è solo *quante volte si chiede*: la
    decisione umana su "cestina queste 21" è una, non ventuno.

    Le azioni **non citate** in `decisioni` non vengono toccate: la UI manda
    sempre tutto il gruppo, ma un client parziale non deve poter far sparire
    in silenzio una conferma che l'utente non ha mai visto.

    Un fallimento non ferma il resto (una mail su 21 che non parte per un 500
    di Gmail non deve annullare le altre 20 già decise): si prosegue e si
    riporta onestamente quante sono andate e quante no.

    Poche alla volta in parallelo (`_PARALLELE_PER_GRUPPO`) e non tutte in
    fila: 30 azioni in sequenza sono ~12s con la scheda ferma e l'utente
    convinto che si sia bloccata (STOP 2, 2026-07-30). Il parallelismo non
    tocca il gate - ogni azione passa comunque da `conferma_azione`, che la
    rivalida e la esegue per conto suo; cambia solo quante aspettano il
    proprio turno di rete. Limitato e non illimitato per non scaricare 30
    richieste insieme su Gmail.
    """
    semaforo = asyncio.Semaphore(_PARALLELE_PER_GRUPPO)

    async def _risolvi(azione_id: str, conferma: bool) -> dict[str, Any]:
        async with semaforo:
            try:
                risultato = await conferma_azione(tenant_id, azione_id, conferma)
                return {"id": azione_id, **risultato}
            except AzioneNonTrovata:
                return {"id": azione_id, "stato": "non_trovata"}
            except AzioneGiaRisolta:
                return {"id": azione_id, "stato": "gia_risolta"}
            except Exception as exc:
                # `conferma_azione` l'ha già marcata in errore: qui si annota e
                # si continua col resto del gruppo.
                logger.exception("azione %s del gruppo fallita", azione_id)
                return {"id": azione_id, "stato": STATO_ERRORE, "errore": str(exc)}

    # gather tiene l'ordine delle decisioni: l'esito resta leggibile nell'ordine
    # in cui l'utente ha visto le voci nella scheda.
    esiti = list(await asyncio.gather(*(_risolvi(i, c) for i, c in decisioni.items())))

    from . import descrizioni_azioni

    return {"esiti": esiti, "esito": descrizioni_azioni.esito_gruppo(esiti)}


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
