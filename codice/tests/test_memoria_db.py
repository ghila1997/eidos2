import httpx
import pytest

from memoria import db as memoria_db

SUPABASE_URL = "https://fake.supabase.co"
TENANT = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_upsert_fatto_usa_on_conflict_su_entity_key(respx_mock):
    """Trappola: l'upsert deve appoggiarsi al vincolo unico (tenant_id,
    entity_key) del DB, non limitarsi a un insert che duplicherebbe i fatti."""
    route = respx_mock.post(f"{SUPABASE_URL}/rest/v1/memoria_fatti").mock(
        return_value=httpx.Response(201, json=[{"id": "fatto-1"}])
    )

    await memoria_db.upsert_fatto(TENANT, "cliente:rossi", "cliente", {"nome": "Rossi"})

    richiesta = route.calls.last.request
    assert richiesta.url.params["on_conflict"] == "tenant_id,entity_key"
    assert richiesta.headers["Prefer"] == "resolution=merge-duplicates"


@pytest.mark.asyncio
async def test_match_chunks_filtra_sempre_per_tenant(respx_mock):
    """Anti-leak: la ricerca semantica non deve mai poter essere chiamata
    senza uno scoping esplicito per tenant."""
    route = respx_mock.post(f"{SUPABASE_URL}/rest/v1/rpc/match_chunks").mock(
        return_value=httpx.Response(200, json=[])
    )

    await memoria_db.match_chunks(TENANT, [0.1, 0.2], match_count=3)

    corpo = route.calls.last.request.content
    import json

    body = json.loads(corpo)
    assert body["p_tenant_id"] == TENANT
    assert body["match_count"] == 3


@pytest.mark.asyncio
async def test_get_preferenze_richiede_bound_esplicito(respx_mock):
    """Le preferenze sempre caricate devono restare 'poche righe': la query
    porta sempre un limit esplicito, non un fetch illimitato."""
    route = respx_mock.get(f"{SUPABASE_URL}/rest/v1/memoria_preferenze").mock(
        return_value=httpx.Response(200, json=[{"chiave": "tono", "valore": "diretto"}])
    )

    risultato = await memoria_db.get_preferenze(TENANT)

    assert risultato == {"tono": "diretto"}
    assert route.calls.last.request.url.params["limit"] == str(memoria_db.MAX_PREFERENZE)
