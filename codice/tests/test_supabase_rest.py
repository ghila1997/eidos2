"""Client HTTP condiviso per le chiamate PostgREST (Tappa 6, STOP 2
2026-07-19): un client nuovo a ogni chiamata paga l'handshake TLS ogni volta
(~0,7s misurati su Google Calendar, stesso principio qui) - dominava la
latenza di ogni turno vocale (azioni.py chiamato due volte a turno)."""
from __future__ import annotations

import pytest

from common import supabase_rest


@pytest.fixture(autouse=True)
def _chiudi_client_condiviso():
    yield
    supabase_rest._client_condiviso = None


def test_client_riusato_tra_chiamate():
    primo = supabase_rest.client()
    secondo = supabase_rest.client()
    assert primo is secondo
