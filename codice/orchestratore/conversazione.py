"""Record della conversazione (Tappa 7.3): i messaggi (utente / assistente /
esito azione) sopravvivono cross-sessione per tenant, cosi' la cronologia c'e'
ancora dopo un refresh.

Vive nell'Orchestratore, non nell'interfaccia: e' il record della conversazione
del *motore*, e non lo scrive solo la UI web (`sessione_web`), lo scrive anche
il flusso di conferma di un'azione (`azioni.conferma_azione`) quando l'azione
parte davvero - cosi' l'esito ("Mail inviata a ...") entra nella cronologia da
qualunque canale (web/CLI/voce), non solo dal web.

Log **per-messaggio** (vedi migration): un turno = riga utente + riga
assistente (con i `passi` fatti nel turno); l'esito di un'azione e' una riga a
se'. Solo REST server-side con service role key (`common.supabase_rest`), RLS
senza policy: nessun accesso da client.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from common.supabase_rest import rest_headers, supabase_settings

# Ultimi N messaggi caricati all'apertura (~2-3 per turno). "Carica piu'
# vecchi" e' un di piu' segnato "minore/dopo" in
# notes/interfaccia-prodotto-finito.md, non ora.
MAX_MESSAGGI = 400

_TABELLA = "conversazione_messaggi"


async def salva_turno(
    tenant_id: str,
    testo_utente: str,
    testo_assistente: str,
    passi: list[dict] | None = None,
) -> None:
    """Salva un turno completo come due messaggi (utente + assistente) in una
    sola scrittura. Chiamato solo a turno riuscito: un turno fallito o
    interrotto non lascia righe a meta'.

    `passi` (le "cose fatte in mezzo": i tool del turno) vanno sul messaggio
    assistente. I due messaggi ricevono un `created_at` esplicito a 1ms di
    distanza cosi' l'ordine utente->assistente e' garantito anche a parita' di
    istante (il default now() li lascerebbe pari)."""
    url, key = supabase_settings()
    base = datetime.now(timezone.utc)
    righe = [
        {
            "tenant_id": tenant_id,
            "ruolo": "utente",
            "contenuto": testo_utente,
            "created_at": base.isoformat(),
        },
        {
            "tenant_id": tenant_id,
            "ruolo": "assistente",
            "contenuto": testo_assistente,
            "passi": passi or None,
            "created_at": (base + timedelta(milliseconds=1)).isoformat(),
        },
    ]
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/{_TABELLA}",
            headers=rest_headers(key),
            json=righe,
        )
    resp.raise_for_status()


async def salva_esito(tenant_id: str, contenuto: str) -> None:
    """Aggiunge un messaggio di esito azione ("Mail inviata a ..."), scritto
    quando un'azione parte davvero. E' un messaggio a se': arriva anche molto
    dopo il turno che l'ha proposta, e da qualunque canale."""
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/rest/v1/{_TABELLA}",
            headers=rest_headers(key),
            json={"tenant_id": tenant_id, "ruolo": "esito", "contenuto": contenuto},
        )
    resp.raise_for_status()


async def get_messaggi(tenant_id: str, limite: int = MAX_MESSAGGI) -> list[dict]:
    """Ultimi `limite` messaggi del tenant in ordine cronologico crescente (i
    piu' vecchi in cima, come si legge una chat). Filtrato sempre per tenant
    (anti-leak): non esiste una lettura non scoping-ata. Prende gli N piu'
    recenti (desc + limit) e li inverte, per non caricare tutto lo storico a
    ogni apertura."""
    url, key = supabase_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{url}/rest/v1/{_TABELLA}",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "select": "ruolo,contenuto,passi,created_at",
                "order": "created_at.desc",
                "limit": str(limite),
            },
            headers=rest_headers(key),
        )
    resp.raise_for_status()
    return list(reversed(resp.json()))
