import pytest
from cryptography.fernet import Fernet

from orchestratore.safety import supervisor


@pytest.fixture(autouse=True)
def _isola_audit_log_safety(tmp_path, monkeypatch):
    """Nessun test (anche quelli che non conoscono il Supervisor, come
    test_tools.py/test_azioni.py che ora ci passano attraverso) deve poter
    scrivere nell'audit log reale del repo."""
    monkeypatch.setattr(supervisor, "_AUDIT_LOG_PATH", tmp_path / "safety_audit.log")


@pytest.fixture(autouse=True)
def fake_supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.setenv("VOYAGE_API_KEY", "fake-voyage-key")
    monkeypatch.setenv("EIDOS_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("EIDOS_OAUTH_GOOGLE_CLIENT_ID", "fake-google-client-id")
    monkeypatch.setenv("EIDOS_OAUTH_GOOGLE_CLIENT_SECRET", "fake-google-client-secret")
    monkeypatch.setenv("EIDOS_OAUTH_REDIRECT_BASE_URL", "https://eidos2-api-production.up.railway.app")
    monkeypatch.setenv("EIDOS_OAUTH_STATE_SECRET", "fake-oauth-state-secret")
