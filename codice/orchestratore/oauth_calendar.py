"""OAuth Google per Calendar. Wrapper Calendar-specifico su `oauth_core`,
stesso pattern di oauth.py (Gmail) - vedi DECISIONS.md 2026-07-15
"Connettori multi-provider": secondo fornitore OAuth, parte generica
riusata, solo costanti/redirect path propri.

Scope `calendar.events` + `calendar.calendarlist.readonly`: crea/legge/
modifica/cancella eventi su tutti i calendari a cui il founder ha accesso,
più la sola lettura dell'elenco calendari (necessaria per la ricerca
multi-calendario, vedi calendar_client.py) - non gestisce impostazioni/ACL
dei calendari stessi (amministrazione, fuori scope - stesso criterio di
completezza di Gmail, vedi DECISIONS.md 2026-07-14). `calendar.events` da
solo NON include l'accesso a `calendarList.list` - trappola reale trovata
testando a mano il 2026-07-15, vedi DECISIONS.md.
"""
from __future__ import annotations

from . import oauth_core

CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
)
_REDIRECT_PATH = "/oauth/google_calendar/callback"

PROVIDER_CALENDAR = "google_calendar"


def costruisci_url_autorizzazione(tenant_id: str) -> str:
    return oauth_core.costruisci_url_autorizzazione(tenant_id, CALENDAR_SCOPES, _REDIRECT_PATH)


async def scambia_codice(code: str) -> dict:
    return await oauth_core.scambia_codice(code, _REDIRECT_PATH)
