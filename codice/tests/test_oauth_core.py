"""Cache dell'access token OAuth (Tappa 6, STOP 2 2026-07-19): ogni tool
call su Calendar/Drive/Gmail rifaceva un ciclo completo (Supabase +
refresh Google, ~1,6s misurati) anche a token ancora valido - inaccettabile
a ogni turno di una conversazione vocale. Un access token Google dura
tipicamente 1h; qui si riusa finché non è vicino a scadere."""
from __future__ import annotations

import time

import pytest

from orchestratore import oauth_core

TENANT = "11111111-1111-1111-1111-111111111111"
PROVIDER = "calendar"


@pytest.fixture(autouse=True)
def _svuota_cache_token():
    oauth_core._CACHE_ACCESS_TOKEN.clear()
    yield
    oauth_core._CACHE_ACCESS_TOKEN.clear()


def _monta_rete(monkeypatch, refresh_token="rt-cifrato", access_token="at-nuovo", expires_in=3600):
    chiamate = {"credenziale": 0, "rinnova": 0}

    async def fake_get_credenziale(tenant_id, provider):
        chiamate["credenziale"] += 1
        return {"refresh_token_cifrato": refresh_token}

    async def fake_rinnova(rt):
        chiamate["rinnova"] += 1
        return {"access_token": access_token, "expires_in": expires_in}

    monkeypatch.setattr(oauth_core, "get_credenziale", fake_get_credenziale)
    monkeypatch.setattr(oauth_core, "rinnova_access_token", fake_rinnova)
    monkeypatch.setattr(oauth_core, "decifra_refresh_token", lambda c: "rt-decifrato")
    return chiamate


async def test_prima_chiamata_fa_il_giro_completo(monkeypatch):
    chiamate = _monta_rete(monkeypatch)
    token = await oauth_core.access_token_valido(TENANT, PROVIDER)
    assert token == "at-nuovo"
    assert chiamate == {"credenziale": 1, "rinnova": 1}


async def test_seconda_chiamata_usa_la_cache_senza_rete(monkeypatch):
    chiamate = _monta_rete(monkeypatch)
    await oauth_core.access_token_valido(TENANT, PROVIDER)
    token = await oauth_core.access_token_valido(TENANT, PROVIDER)
    assert token == "at-nuovo"
    assert chiamate == {"credenziale": 1, "rinnova": 1}


async def test_token_vicino_a_scadenza_si_rinnova(monkeypatch):
    """Margine di sicurezza: un token che scade tra pochi secondi si
    rinnova comunque, non si aspetta la scadenza esatta (rischio di usare
    un token già rifiutato dall'API)."""
    chiamate = _monta_rete(monkeypatch, expires_in=3600)
    await oauth_core.access_token_valido(TENANT, PROVIDER)
    orologio = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: orologio + 3600 - 5)
    await oauth_core.access_token_valido(TENANT, PROVIDER)
    assert chiamate["rinnova"] == 2


async def test_nessuna_credenziale_ritorna_none(monkeypatch):
    async def fake_get_credenziale(tenant_id, provider):
        return None

    monkeypatch.setattr(oauth_core, "get_credenziale", fake_get_credenziale)
    assert await oauth_core.access_token_valido(TENANT, PROVIDER) is None


async def test_cache_separata_per_tenant_e_provider(monkeypatch):
    chiamate = _monta_rete(monkeypatch)
    await oauth_core.access_token_valido(TENANT, "calendar")
    await oauth_core.access_token_valido(TENANT, "drive")
    await oauth_core.access_token_valido("altro-tenant", "calendar")
    assert chiamate == {"credenziale": 3, "rinnova": 3}
