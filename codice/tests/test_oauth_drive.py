"""Non-regressione dello split multi-provider (vedi DECISIONS.md 2026-07-15,
"Connettori multi-provider"): Drive usa un redirect path e uno scope diversi
da Gmail/Calendar, la parte generica (state, cifratura) resta condivisa e
già coperta da test_oauth.py."""
from orchestratore import oauth, oauth_calendar, oauth_drive


def test_drive_ha_provider_e_scope_diversi_da_gmail_e_calendar():
    assert oauth_drive.PROVIDER_DRIVE != oauth.PROVIDER_GMAIL
    assert oauth_drive.PROVIDER_DRIVE != oauth_calendar.PROVIDER_CALENDAR
    assert oauth_drive.DRIVE_SCOPES != oauth.GMAIL_SCOPES
    assert oauth_drive.DRIVE_SCOPES != oauth_calendar.CALENDAR_SCOPES


def test_drive_usa_redirect_path_proprio(monkeypatch):
    monkeypatch.setenv("EIDOS_OAUTH_REDIRECT_BASE_URL", "https://example.com")
    monkeypatch.setenv("EIDOS_OAUTH_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("EIDOS_OAUTH_STATE_SECRET", "secret")

    url_drive = oauth_drive.costruisci_url_autorizzazione("11111111-1111-1111-1111-111111111111")
    url_calendar = oauth_calendar.costruisci_url_autorizzazione("11111111-1111-1111-1111-111111111111")

    assert "google_drive%2Fcallback" in url_drive
    assert url_drive != url_calendar
