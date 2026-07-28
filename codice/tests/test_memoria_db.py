import json

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
async def test_find_fatti_ilike_usa_match_parziale_case_insensitive(respx_mock):
    route = respx_mock.get(f"{SUPABASE_URL}/rest/v1/memoria_fatti").mock(
        return_value=httpx.Response(200, json=[{"entity_key": "rossi", "entity_type": "persona", "data": {}}])
    )

    risultato = await memoria_db.find_fatti_ilike(TENANT, "Rossi")

    assert risultato[0]["entity_key"] == "rossi"
    assert route.calls.last.request.url.params["entity_key"] == "ilike.*Rossi*"


@pytest.mark.asyncio
async def test_elimina_chunk_documento_filtra_per_tenant_e_documento(respx_mock):
    route = respx_mock.delete(f"{SUPABASE_URL}/rest/v1/memoria_chunk_embedding").mock(
        return_value=httpx.Response(200, json=[])
    )

    await memoria_db.elimina_chunk_documento(TENANT, "doc-1")

    params = route.calls.last.request.url.params
    assert params["tenant_id"] == f"eq.{TENANT}"
    assert params["documento_id"] == "eq.doc-1"


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


@pytest.mark.asyncio
async def test_upsert_impegno_inserisce_con_stato_aperto(respx_mock):
    route = respx_mock.post(f"{SUPABASE_URL}/rest/v1/memoria_impegni").mock(
        return_value=httpx.Response(201, json=[{"id": "impegno-1"}])
    )

    impegno_id = await memoria_db.upsert_impegno(
        TENANT,
        entity_key="isagro",
        descrizione="Restituire pagamento doppio fattura 725FE",
        direzione="nostro",
        source_type="gmail",
        source_id="msg-1",
        source_excerpt="si richiede risarcimento doppio pagamento",
        observed_at="2026-07-21T09:53:31+00:00",
        scadenza=None,
        confidence=0.9,
    )

    assert impegno_id == "impegno-1"
    corpo = json.loads(route.calls.last.request.content)
    assert corpo["tenant_id"] == TENANT
    assert corpo["entity_key"] == "isagro"
    assert corpo["direzione"] == "nostro"
    assert corpo["stato"] == "aperto"
    assert corpo["confidence"] == 0.9


@pytest.mark.asyncio
async def test_get_impegni_aperti_filtra_tenant_e_stato(respx_mock):
    route = respx_mock.get(f"{SUPABASE_URL}/rest/v1/memoria_impegni").mock(
        return_value=httpx.Response(200, json=[{"entity_key": "isagro", "stato": "aperto"}])
    )

    risultato = await memoria_db.get_impegni_aperti(TENANT)

    assert risultato[0]["entity_key"] == "isagro"
    params = route.calls.last.request.url.params
    assert params["tenant_id"] == f"eq.{TENANT}"
    assert params["stato"] == "eq.aperto"


@pytest.mark.asyncio
async def test_chiudi_impegno_marca_stato_chiuso_con_timestamp(respx_mock):
    route = respx_mock.patch(f"{SUPABASE_URL}/rest/v1/memoria_impegni").mock(
        return_value=httpx.Response(200, json=[{"id": "impegno-1"}])
    )

    await memoria_db.chiudi_impegno(TENANT, "impegno-1")

    richiesta = route.calls.last.request
    assert richiesta.url.params["tenant_id"] == f"eq.{TENANT}"
    assert richiesta.url.params["id"] == "eq.impegno-1"
    corpo = json.loads(richiesta.content)
    assert corpo["stato"] == "chiuso"
    assert "chiuso_il" in corpo


@pytest.mark.asyncio
async def test_trova_impegno_simile_filtra_entity_e_source(respx_mock):
    """Base per la deduplica: stessa mail riproposta due volte non deve
    creare doppioni (vedi contratto STOP 1, punto 8)."""
    route = respx_mock.get(f"{SUPABASE_URL}/rest/v1/memoria_impegni").mock(
        return_value=httpx.Response(200, json=[])
    )

    risultato = await memoria_db.trova_impegno_simile(TENANT, "isagro", "gmail", "msg-1")

    assert risultato is None
    params = route.calls.last.request.url.params
    assert params["tenant_id"] == f"eq.{TENANT}"
    assert params["entity_key"] == "eq.isagro"
    assert params["source_type"] == "eq.gmail"
    assert params["source_id"] == "eq.msg-1"
