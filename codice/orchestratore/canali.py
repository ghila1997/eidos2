"""Canali aperti verso l'utente, per tenant.

Serve a mandare eventi che **non nascono da un messaggio del client**: quando
l'utente conferma un gruppo di azioni, la POST risponde subito e l'esecuzione
prosegue per conto suo — l'avanzamento deve poter raggiungere la sessione web
già aperta senza che questa lo abbia chiesto.

Sta qui e non in `interfaccia_utente/sessione_web.py` per non far dipendere
l'orchestratore dall'interfaccia: chi apre un canale lo registra, chi ha
qualcosa da dire chiama `annuncia`, e i due non si conoscono.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

Canale = Callable[[dict], Awaitable[None]]

# Una lista e non un canale solo: lo stesso tenant puo' avere due schede
# aperte, ed entrambe devono vedere cosa sta succedendo.
_canali_per_tenant: dict[str, list[Canale]] = {}


# Eventi prodotti mentre nessun canale era aperto, in attesa del primo che si
# apre. Serve perche' l'esito di un'azione racconta una cosa **gia' avvenuta**:
# se il socket non c'e' in quell'istante (sessione scaduta, rete caduta, scheda
# chiusa) buttarlo via significa che l'utente non sapra' mai che 30 mail sono
# finite nel cestino. La consegna e' differita, non facoltativa.
#
# In memoria e con una scadenza: e' un recapito mancato, non un archivio. La
# verita' di "cosa e' stato fatto" resta in Gmail/Calendar (DECISIONS.md
# 2026-07-29); qui si tiene solo il tempo di dirlo a chi torna.
_da_recapitare: dict[str, list[tuple[float, dict]]] = {}

VALIDITA_RECAPITO = 3600.0   # oltre un'ora e' cronaca vecchia, non una notizia


def registra(tenant_id: str, canale: Canale) -> None:
    _canali_per_tenant.setdefault(tenant_id, []).append(canale)
    logger.info("canale aperto (tenant %s): %d aperti", tenant_id, len(_canali_per_tenant[tenant_id]))
    arretrati = _da_recapitare.pop(tenant_id, [])
    if arretrati:
        asyncio.create_task(_recapita_arretrati(tenant_id, canale, arretrati))


async def _recapita_arretrati(
    tenant_id: str, canale: Canale, arretrati: list[tuple[float, dict]]
) -> None:
    adesso = time.monotonic()
    for prodotto_a, evento in arretrati:
        if adesso - prodotto_a > VALIDITA_RECAPITO:
            continue
        try:
            # `differito`: la UI lo mostra come cosa avvenuta prima, non come
            # qualcosa che sta succedendo adesso.
            await canale({**evento, "differito": True})
            logger.info("esito arretrato recapitato (tenant %s): %s", tenant_id, evento.get("esito"))
        except Exception:
            # Non riuscito nemmeno stavolta: si rimette in coda per il prossimo.
            _da_recapitare.setdefault(tenant_id, []).append((prodotto_a, evento))


def deregistra(tenant_id: str, canale: Canale) -> None:
    canali = _canali_per_tenant.get(tenant_id, [])
    if canale in canali:
        canali.remove(canale)
    if not canali:
        _canali_per_tenant.pop(tenant_id, None)
    logger.info("canale chiuso (tenant %s): %d rimasti", tenant_id, len(_canali_per_tenant.get(tenant_id, [])))


async def annuncia(tenant_id: str, evento: dict) -> None:
    """Manda un evento a tutti i canali aperti del tenant.

    Non solleva mai: un canale morto (scheda chiusa nel frattempo) non deve
    far fallire chi sta annunciando. L'avanzamento di un'azione e' un di piu',
    l'azione e' la cosa che conta - e nemmeno deve impedire agli altri canali
    dello stesso tenant di ricevere l'evento.
    """
    aperti = list(_canali_per_tenant.get(tenant_id, []))
    consegnati = 0
    for canale in aperti:
        try:
            await canale(evento)
            consegnati += 1
        except Exception:
            logger.debug("canale non raggiungibile per l'evento %s", evento.get("evento"))
    # A INFO e non a debug per l'esito di un'azione: e' l'unica traccia che dice
    # se il risultato di una cosa gia' *avvenuta* e' arrivato all'utente o si e'
    # perso per strada, e sono pochi eventi. Zero canali = azione eseguita che
    # nessuno ha visto.
    if evento.get("evento") == "azione_fine":
        logger.info(
            "esito azione consegnato a %d/%d canali aperti (tenant %s): %s",
            consegnati, len(aperti), tenant_id, evento.get("esito"),
        )
        if consegnati == 0:
            # Nessuno l'ha ricevuto: si tiene per la prima sessione che apre.
            # L'azione E' avvenuta - non dirlo mai sarebbe la cosa peggiore.
            _da_recapitare.setdefault(tenant_id, []).append((time.monotonic(), evento))
            logger.info("esito messo da parte per il prossimo canale (tenant %s)", tenant_id)
