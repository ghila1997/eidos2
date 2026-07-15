"""OAuth Google per Gmail. Wrapper Gmail-specifico su `oauth_core` (parte
generica: state, scambio/refresh token, cifratura, storage credenziali) -
split fatto in Tappa 4 quando è arrivato il secondo provider OAuth
(Calendar, vedi oauth_calendar.py e DECISIONS.md 2026-07-15 "Connettori
multi-provider"). Le firme restano invariate rispetto a prima dello split:
nessun chiamante esistente (gmail_client.py, router.py, test_oauth.py) è
stato toccato.
"""
from __future__ import annotations

from . import oauth_core
from .oauth_core import (  # re-esportati, invariato per i chiamanti esistenti
    StatoNonValido as StatoNonValido,
    cifra_refresh_token as cifra_refresh_token,
    decifra_refresh_token as decifra_refresh_token,
    genera_state as genera_state,
    get_credenziale as get_credenziale,
    salva_credenziale as salva_credenziale,
    verifica_state as verifica_state,
)

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify "
    "https://www.googleapis.com/auth/gmail.labels"
)
_REDIRECT_PATH = "/oauth/google/callback"

PROVIDER_GMAIL = "gmail"


def costruisci_url_autorizzazione(tenant_id: str) -> str:
    return oauth_core.costruisci_url_autorizzazione(tenant_id, GMAIL_SCOPES, _REDIRECT_PATH)


async def scambia_codice(code: str) -> dict:
    return await oauth_core.scambia_codice(code, _REDIRECT_PATH)


async def rinnova_access_token(refresh_token: str) -> dict:
    return await oauth_core.rinnova_access_token(refresh_token)
