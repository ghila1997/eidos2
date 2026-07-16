"""OAuth Google per Drive. Wrapper Drive-specifico su `oauth_core`, stesso
pattern di oauth.py (Gmail) e oauth_calendar.py (Calendar) - vedi
DECISIONS.md 2026-07-15 "Connettori multi-provider": terzo fornitore OAuth,
parte generica riusata, solo costanti/redirect path propri.

Scope `drive` (pieno), non `drive.file`: `drive.file` darebbe accesso solo
ai file creati/aperti dall'app, inutile per cercare/organizzare/condividere
file reali preesistenti caricati dal founder da altrove - vedi design Tappa 4
(Drive), stessa logica già accettata per lo scope ampio di Gmail
(`gmail.modify`). Non gestisce impostazioni account, quota, Shared Drives
(amministrazione, fuori scope - stesso criterio di completezza di Gmail/
Calendar, vedi DECISIONS.md 2026-07-14).
"""
from __future__ import annotations

from . import oauth_core

DRIVE_SCOPES = "https://www.googleapis.com/auth/drive"
_REDIRECT_PATH = "/oauth/google_drive/callback"

PROVIDER_DRIVE = "google_drive"


def costruisci_url_autorizzazione(tenant_id: str) -> str:
    return oauth_core.costruisci_url_autorizzazione(tenant_id, DRIVE_SCOPES, _REDIRECT_PATH)


async def scambia_codice(code: str) -> dict:
    return await oauth_core.scambia_codice(code, _REDIRECT_PATH)
