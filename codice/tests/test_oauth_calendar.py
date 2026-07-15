"""Non-regressione dello split oauth_core/oauth/oauth_calendar (vedi
DECISIONS.md 2026-07-15, "Connettori multi-provider"): Calendar usa un
redirect path e uno scope diversi da Gmail, la parte generica (state,
cifratura) resta condivisa e già coperta da test_oauth.py."""
from orchestratore import oauth, oauth_calendar


def test_calendar_e_gmail_hanno_provider_e_scope_diversi():
    assert oauth_calendar.PROVIDER_CALENDAR != oauth.PROVIDER_GMAIL
    assert oauth_calendar.CALENDAR_SCOPES != oauth.GMAIL_SCOPES


def test_calendar_e_gmail_usano_redirect_path_diversi(monkeypatch):
    monkeypatch.setenv("EIDOS_OAUTH_REDIRECT_BASE_URL", "https://example.com")
    monkeypatch.setenv("EIDOS_OAUTH_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("EIDOS_OAUTH_STATE_SECRET", "secret")

    url_gmail = oauth.costruisci_url_autorizzazione("11111111-1111-1111-1111-111111111111")
    url_calendar = oauth_calendar.costruisci_url_autorizzazione("11111111-1111-1111-1111-111111111111")

    assert "google%2Fcallback" in url_gmail
    assert "google_calendar%2Fcallback" in url_calendar
    assert url_gmail != url_calendar
