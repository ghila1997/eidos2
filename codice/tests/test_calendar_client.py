"""Trappole di calendar_client: gate sendUpdates in base ai partecipanti,
RSVP che tocca solo il proprio responseStatus, ricerca su tutti i
calendari, fallback su syncToken scaduto (410)."""
import httpx
import pytest

from orchestratore import calendar_client

_API_BASE = "https://www.googleapis.com/calendar/v3"


@pytest.mark.asyncio
async def test_crea_evento_senza_partecipanti_non_invia_notifiche(respx_mock):
    route = respx_mock.post(f"{_API_BASE}/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"id": "evt-1", "summary": "Promemoria", "start": {}, "end": {}})
    )

    await calendar_client.crea_evento("token", "Promemoria", "2026-07-20T10:00:00Z", "2026-07-20T11:00:00Z")

    assert route.calls.last.request.url.params["sendUpdates"] == "none"


@pytest.mark.asyncio
async def test_crea_evento_con_partecipanti_invia_notifiche_a_tutti(respx_mock):
    route = respx_mock.post(f"{_API_BASE}/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"id": "evt-1", "summary": "Riunione", "start": {}, "end": {}})
    )

    await calendar_client.crea_evento(
        "token", "Riunione", "2026-07-20T10:00:00Z", "2026-07-20T11:00:00Z",
        partecipanti=["cliente@example.com"],
    )

    assert route.calls.last.request.url.params["sendUpdates"] == "all"
    import json
    corpo = json.loads(route.calls.last.request.content)
    assert corpo["attendees"] == [{"email": "cliente@example.com"}]


@pytest.mark.asyncio
async def test_crea_evento_tutto_il_giorno_usa_campo_date(respx_mock):
    route = respx_mock.post(f"{_API_BASE}/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"id": "evt-1", "summary": "Scadenza", "start": {"date": "2026-07-20"}, "end": {"date": "2026-07-21"}})
    )

    await calendar_client.crea_evento(
        "token", "Scadenza", "2026-07-20", "2026-07-21", tutto_il_giorno=True,
    )

    import json
    corpo = json.loads(route.calls.last.request.content)
    assert corpo["start"] == {"date": "2026-07-20"}
    assert corpo["end"] == {"date": "2026-07-21"}


@pytest.mark.asyncio
async def test_risolvi_calendario_id_per_nome(respx_mock):
    respx_mock.get(f"{_API_BASE}/users/me/calendarList").mock(
        return_value=httpx.Response(200, json={"items": [
            {"id": "primary", "summary": "founder@example.com", "primary": True},
            {"id": "cal-lavoro-id", "summary": "Lavoro"},
        ]})
    )

    calendar_id = await calendar_client._risolvi_calendario_id("token", "lavoro")  # case-insensitive
    assert calendar_id == "cal-lavoro-id"


@pytest.mark.asyncio
async def test_risolvi_calendario_id_non_trovato_solleva_errore(respx_mock):
    respx_mock.get(f"{_API_BASE}/users/me/calendarList").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "primary", "summary": "founder@example.com"}]})
    )

    with pytest.raises(calendar_client.CalendarError):
        await calendar_client._risolvi_calendario_id("token", "Inesistente")


@pytest.mark.asyncio
async def test_rispondi_invito_modifica_solo_il_proprio_stato(respx_mock):
    """Trappola esplicita: la RSVP non deve mai toccare responseStatus di
    altri partecipanti, solo il proprio (self: true)."""
    respx_mock.get(f"{_API_BASE}/calendars/primary/events/evt-1").mock(
        return_value=httpx.Response(200, json={
            "id": "evt-1", "summary": "Riunione", "start": {}, "end": {},
            "attendees": [
                {"email": "founder@example.com", "self": True, "responseStatus": "needsAction"},
                {"email": "cliente@example.com", "self": False, "responseStatus": "needsAction"},
            ],
        })
    )
    route_patch = respx_mock.patch(f"{_API_BASE}/calendars/primary/events/evt-1").mock(
        return_value=httpx.Response(200, json={"id": "evt-1", "summary": "Riunione", "start": {}, "end": {}})
    )

    await calendar_client.rispondi_invito("token", "evt-1", "accepted")

    import json
    corpo = json.loads(route_patch.calls.last.request.content)
    attendees = {a["email"]: a["responseStatus"] for a in corpo["attendees"]}
    assert attendees["founder@example.com"] == "accepted"
    assert attendees["cliente@example.com"] == "needsAction"  # invariato


@pytest.mark.asyncio
async def test_cerca_eventi_interroga_tutti_i_calendari_di_default(respx_mock):
    respx_mock.get(f"{_API_BASE}/users/me/calendarList").mock(
        return_value=httpx.Response(200, json={"items": [
            {"id": "primary", "summary": "Primario"},
            {"id": "cal-lavoro", "summary": "Lavoro"},
        ]})
    )
    respx_mock.get(f"{_API_BASE}/calendars/primary/events").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "evt-1", "summary": "A", "start": {"dateTime": "2026-07-20T10:00:00Z"}, "end": {"dateTime": "2026-07-20T11:00:00Z"}}]})
    )
    respx_mock.get(f"{_API_BASE}/calendars/cal-lavoro/events").mock(
        return_value=httpx.Response(200, json={"items": [{"id": "evt-2", "summary": "B", "start": {"dateTime": "2026-07-21T10:00:00Z"}, "end": {"dateTime": "2026-07-21T11:00:00Z"}}]})
    )

    eventi = await calendar_client.cerca_eventi("token")

    assert {e["event_id"] for e in eventi} == {"evt-1", "evt-2"}
    assert {e["calendario"] for e in eventi} == {"Primario", "Lavoro"}


@pytest.mark.asyncio
async def test_sincronizza_eventi_con_sync_token_scaduto_fa_fallback_a_fetch_pieno(respx_mock):
    """Trappola: se Google scarta il syncToken (410 Gone), non deve
    esplodere - deve ripiegare su un fetch pieno, stesso pattern
    dell'historyId di Gmail."""
    respx_mock.get(f"{_API_BASE}/calendars/primary/events", params={"syncToken": "vecchio", "singleEvents": "true"}).mock(
        return_value=httpx.Response(410)
    )
    respx_mock.get(f"{_API_BASE}/calendars/primary/events", params={"singleEvents": "true"}).mock(
        return_value=httpx.Response(200, json={"items": [{"id": "evt-3"}], "nextSyncToken": "nuovo-token"})
    )

    eventi, nuovo_cursore = await calendar_client.sincronizza_eventi("token", "primary", "vecchio")

    assert [e["id"] for e in eventi] == ["evt-3"]
    assert nuovo_cursore == "nuovo-token"


@pytest.mark.asyncio
async def test_controlla_disponibilita_passa_persone_e_intervallo(respx_mock):
    route = respx_mock.post(f"{_API_BASE}/freeBusy").mock(
        return_value=httpx.Response(200, json={"calendars": {"rossi@example.com": {"busy": []}}})
    )

    risultato = await calendar_client.controlla_disponibilita(
        "token", ["rossi@example.com"], "2026-07-20T00:00:00Z", "2026-07-21T00:00:00Z"
    )

    import json
    corpo = json.loads(route.calls.last.request.content)
    assert corpo["items"] == [{"id": "rossi@example.com"}]
    assert risultato == {"rossi@example.com": []}
