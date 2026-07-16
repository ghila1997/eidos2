"""Contratto SSE di POST /chat/stream (Tappa 6, incremento 1).

Il client vocale consuma eventi mentre l'agente genera: `delta` (testo),
`tool_in_corso` (per i riempitivi vocali), `azione_in_attesa` (gate di
conferma dentro lo stream, non più solo 409), `fine`, `errore`.
Il modello SDK viene sostituito con un fake: qui si testa il contratto
dell'endpoint, non l'agente.
"""
from __future__ import annotations

import json

import pytest
from claude_agent_sdk import ProcessError
from claude_agent_sdk.types import ResultMessage, StreamEvent
from starlette.testclient import TestClient

import memoria.db as memoria_db
from app import app
from orchestratore import azioni
from orchestratore import router as router_mod

TENANT = "tenant-1"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _delta(testo: str) -> StreamEvent:
    return StreamEvent(
        uuid="u1",
        session_id="sess-nuova",
        event={
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": testo},
        },
    )


def _tool_start(nome_mcp: str) -> StreamEvent:
    return StreamEvent(
        uuid="u2",
        session_id="sess-nuova",
        event={
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": nome_mcp, "input": {}},
        },
    )


def _result(testo: str = "Ciao mondo", session_id: str = "sess-nuova") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        result=testo,
    )


def _eventi_sse(corpo: str) -> list[tuple[str, dict]]:
    """Parsa il corpo SSE in [(evento, data), ...]."""
    eventi = []
    for blocco in corpo.strip().split("\n\n"):
        nome, data = None, None
        for riga in blocco.splitlines():
            if riga.startswith("event:"):
                nome = riga.removeprefix("event:").strip()
            elif riga.startswith("data:"):
                data = json.loads(riga.removeprefix("data:").strip())
        if nome is not None:
            eventi.append((nome, data))
    return eventi


@pytest.fixture()
def base(monkeypatch):
    """Auth, memoria e azioni finte; ogni test imposta la propria query fake."""

    async def fake_sessione(request):
        return {"tenant_id": TENANT, "user_id": "user-1", "role": "owner"}

    async def nessuna_azione(tenant_id):
        return None

    async def fake_preferenze(tenant_id):
        return {}

    async def fake_get_sessione(tenant_id):
        return "sess-vecchia"

    salvate: list[str] = []

    async def fake_set_sessione(tenant_id, session_id):
        salvate.append(session_id)

    monkeypatch.setattr(router_mod, "get_sessione_corrente", fake_sessione)
    monkeypatch.setattr(azioni, "ottieni_azione_pendente_tenant", nessuna_azione)
    monkeypatch.setattr(memoria_db, "get_preferenze", fake_preferenze)
    monkeypatch.setattr(memoria_db, "get_sessione_agent", fake_get_sessione)
    monkeypatch.setattr(memoria_db, "set_sessione_agent", fake_set_sessione)
    return {"salvate": salvate, "monkeypatch": monkeypatch}


def _imposta_query(monkeypatch, messaggi_per_chiamata):
    """`messaggi_per_chiamata`: lista di liste (una per invocazione di query);
    una lista può essere un'eccezione da sollevare. Registra le options."""
    chiamate: list = []

    def fake_query(*, prompt, options):
        indice = len(chiamate)
        chiamate.append(options)

        async def gen():
            esito = messaggi_per_chiamata[indice]
            if isinstance(esito, Exception):
                raise esito
            for m in esito:
                yield m

        return gen()

    monkeypatch.setattr(router_mod, "query", fake_query)
    return chiamate


def test_stream_emette_delta_e_fine(base):
    chiamate = _imposta_query(
        base["monkeypatch"], [[_delta("Ciao "), _delta("mondo"), _result("Ciao mondo")]]
    )
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    eventi = _eventi_sse(resp.text)
    assert ("delta", {"testo": "Ciao "}) == eventi[0]
    assert ("delta", {"testo": "mondo"}) == eventi[1]
    assert eventi[-1] == ("fine", {"risposta": "Ciao mondo", "azione_in_attesa": None})
    # streaming parziale abilitato e sessione ripresa
    assert chiamate[0].include_partial_messages is True
    assert chiamate[0].resume == "sess-vecchia"


def test_stream_emette_tool_in_corso_senza_prefisso_mcp(base):
    _imposta_query(
        base["monkeypatch"],
        [[_tool_start("mcp__eidos__search_memoria"), _delta("Trovato."), _result("Trovato.")]],
    )
    resp = _client().post("/chat/stream", json={"messaggio": "cerca x"})
    eventi = _eventi_sse(resp.text)
    assert ("tool_in_corso", {"tool": "search_memoria"}) in eventi


def test_stream_tool_nativo_resta_col_suo_nome(base):
    _imposta_query(
        base["monkeypatch"], [[_tool_start("Read"), _delta("ok"), _result("ok")]]
    )
    resp = _client().post("/chat/stream", json={"messaggio": "leggi"})
    assert ("tool_in_corso", {"tool": "Read"}) in _eventi_sse(resp.text)


def test_stream_409_se_azione_gia_pendente(base):
    async def azione_pendente(tenant_id):
        return {"id": "az-1", "tipo": "send_email", "payload": {}}

    base["monkeypatch"].setattr(azioni, "ottieni_azione_pendente_tenant", azione_pendente)
    _imposta_query(base["monkeypatch"], [[_result()]])
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["azione_id"] == "az-1"


def test_stream_azione_creata_arriva_nello_stream(base):
    azione = {"id": "az-9", "tipo": "send_email", "payload": {"destinatario": "x@y.it"}}
    esiti = iter([None, azione])  # prima del run: nessuna; dopo: creata

    async def azione_poi_creata(tenant_id):
        return next(esiti)

    base["monkeypatch"].setattr(azioni, "ottieni_azione_pendente_tenant", azione_poi_creata)
    _imposta_query(base["monkeypatch"], [[_delta("Preparo."), _result("Preparo.")]])
    resp = _client().post("/chat/stream", json={"messaggio": "manda mail"})
    eventi = _eventi_sse(resp.text)
    assert eventi[-1] == ("fine", {"risposta": "Preparo.", "azione_in_attesa": azione})


def test_stream_salva_session_id_nuovo(base):
    _imposta_query(base["monkeypatch"], [[_result(session_id="sess-nuova")]])
    _client().post("/chat/stream", json={"messaggio": "ciao"})
    assert base["salvate"] == ["sess-nuova"]


def test_stream_sessione_persa_riparte_da_zero(base):
    """Stesso fallback di /chat: la sessione salvata non esiste più nel
    container -> ProcessError -> si riprova con sessione nuova."""
    chiamate = _imposta_query(
        base["monkeypatch"],
        [ProcessError("sessione persa"), [_delta("Eccomi."), _result("Eccomi.")]],
    )
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    eventi = _eventi_sse(resp.text)
    assert ("delta", {"testo": "Eccomi."}) in eventi
    assert chiamate[0].resume == "sess-vecchia"
    assert chiamate[1].resume is None


def test_stream_errore_a_meta_da_evento_pulito(base):
    """Guasto durante la generazione: evento `errore` con messaggio leggibile,
    mai traceback nel flusso (regola 'ogni guasto ha una voce')."""

    def fake_query(*, prompt, options):
        async def gen():
            yield _delta("Inizio")
            raise RuntimeError("boom interno con dettagli privati")

        return gen()

    base["monkeypatch"].setattr(router_mod, "query", fake_query)
    resp = _client().post("/chat/stream", json={"messaggio": "ciao"})
    eventi = _eventi_sse(resp.text)
    assert eventi[0] == ("delta", {"testo": "Inizio"})
    nomi = [n for n, _ in eventi]
    assert "errore" in nomi
    corpo_errore = dict(eventi)["errore"]["messaggio"]
    assert "boom interno" not in corpo_errore
    assert "Traceback" not in resp.text
