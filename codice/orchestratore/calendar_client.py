"""Client Google Calendar API: tutto quello che un essere umano fa
normalmente con un calendario (cercare, creare, riprogrammare, cancellare,
rispondere a un invito, controllare disponibilità) - vedi design Tappa 4,
decisione "completezza dei connettori" (stesso criterio di Gmail).

Nessun SDK Google pesante - httpx puro, coerente con gmail_client.py.

Lettura multi-calendario di default (`lista_calendari`): un umano single-
operator spesso ha almeno un calendario secondario (Lavoro/Personale) oltre
al primario - restringere la lettura al solo primario darebbe risposte di
disponibilità sbagliate (vedi DECISIONS.md 2026-07-15). La scrittura resta
su un calendario preferito (default "primary") a meno che non venga
specificato un nome.

Scope OAuth: calendar.events (vedi oauth_calendar.py) - crea/legge/
modifica/cancella eventi su tutti i calendari accessibili, non gestisce
impostazioni/ACL dei calendari (amministrazione, fuori scope).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx

from . import oauth_calendar, oauth_core

_API_BASE = "https://www.googleapis.com/calendar/v3"

CALENDARIO_SCRITTURA_DEFAULT = "primary"


class CalendarError(Exception):
    """Errore nella chiamata a Google Calendar API."""


# Client HTTP riusato tra le chiamate: un client nuovo a ogni richiesta paga
# l'handshake TLS ogni volta (~0,7s misurati contro ~0,1-0,2s riusando la
# connessione, STOP 2 Tappa 6 2026-07-19) - dominava la latenza di un turno
# vocale col calendario. Stesso principio del client Anthropic in ponte.py.
_client_condiviso: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _client_condiviso
    if _client_condiviso is None:
        _client_condiviso = httpx.AsyncClient(timeout=30.0)
    return _client_condiviso


async def ottieni_access_token(tenant_id: str) -> str:
    # access_token_valido tiene una cache in-memory (~1,6s risparmiati a ogni
    # tool call oltre il primo, vedi oauth_core.py) - non rifà il giro
    # Supabase+Google se l'access token è ancora valido.
    token = await oauth_core.access_token_valido(tenant_id, oauth_calendar.PROVIDER_CALENDAR)
    if token is None:
        raise CalendarError(
            "Nessuna credenziale Calendar collegata per questo tenant: "
            "serve prima /oauth/google_calendar/authorize"
        )
    return token


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def lista_calendari(access_token: str) -> list[dict[str, Any]]:
    resp = await _client().get(
        f"{_API_BASE}/users/me/calendarList", headers=_headers(access_token)
    )
    if resp.status_code != 200:
        raise CalendarError(f"Calendar calendarList.list fallita: {resp.status_code}")
    return [
        {"id": voce["id"], "nome": voce.get("summary", voce["id"]), "primario": voce.get("primary", False)}
        for voce in resp.json().get("items", [])
    ]


async def _risolvi_calendario_id(access_token: str, nome_calendario: str | None) -> str:
    if nome_calendario is None:
        return CALENDARIO_SCRITTURA_DEFAULT
    for calendario in await lista_calendari(access_token):
        if calendario["nome"].lower() == nome_calendario.lower():
            return calendario["id"]
    raise CalendarError(f"Calendario '{nome_calendario}' non trovato tra quelli disponibili")


def _corpo_evento(
    *,
    titolo: str | None = None,
    inizio: str | None = None,
    fine: str | None = None,
    fuso_orario: str | None = None,
    tutto_il_giorno: bool = False,
    descrizione: str | None = None,
    luogo: str | None = None,
    partecipanti: list[str] | None = None,
    promemoria_minuti: list[int] | None = None,
    ricorrenza: str | None = None,
    videochiamata: bool = False,
    occupato: bool | None = None,
    colore: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if titolo is not None:
        body["summary"] = titolo
    if descrizione is not None:
        body["description"] = descrizione
    if luogo is not None:
        body["location"] = luogo
    if inizio is not None and fine is not None:
        if tutto_il_giorno:
            body["start"] = {"date": inizio}
            body["end"] = {"date": fine}
        else:
            body["start"] = {"dateTime": inizio, "timeZone": fuso_orario or "UTC"}
            body["end"] = {"dateTime": fine, "timeZone": fuso_orario or "UTC"}
    if partecipanti is not None:
        body["attendees"] = [{"email": email} for email in partecipanti]
    if promemoria_minuti is not None:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": minuti} for minuti in promemoria_minuti],
        }
    if ricorrenza is not None:
        body["recurrence"] = [ricorrenza]
    if videochiamata:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    if occupato is not None:
        body["transparency"] = "opaque" if occupato else "transparent"
    if colore is not None:
        body["colorId"] = colore
    return body


def estrai_evento(item: dict, calendario_nome: str | None = None) -> dict[str, Any]:
    inizio = item.get("start", {})
    fine = item.get("end", {})
    return {
        "event_id": item["id"],
        "titolo": item.get("summary", "(senza titolo)"),
        "inizio": inizio.get("dateTime") or inizio.get("date"),
        "fine": fine.get("dateTime") or fine.get("date"),
        "tutto_il_giorno": "date" in inizio,
        "descrizione": item.get("description", ""),
        "luogo": item.get("location", ""),
        "partecipanti": [a["email"] for a in item.get("attendees", [])],
        "allegati": [
            {"titolo": a.get("title", ""), "link": a.get("fileUrl", "")}
            for a in item.get("attachments", [])
        ],
        "videochiamata": item.get("hangoutLink"),
        "occupato": item.get("transparency", "opaque") != "transparent",
        "status": item.get("status"),
        "calendario": calendario_nome,
    }


async def cerca_eventi(
    access_token: str,
    query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    tutti_i_calendari: bool = True,
) -> list[dict[str, Any]]:
    """Cerca eventi (passato+futuro, testo libero) - di default su tutti i
    calendari accessibili, non solo il primario (vedi motivazione in cima
    al file)."""
    if tutti_i_calendari:
        calendari = await lista_calendari(access_token)
    else:
        calendari = [{"id": CALENDARIO_SCRITTURA_DEFAULT, "nome": "primary"}]

    params: dict[str, str] = {"singleEvents": "true", "orderBy": "startTime", "maxResults": "50"}
    if query:
        params["q"] = query
    if date_from:
        params["timeMin"] = date_from
    if date_to:
        params["timeMax"] = date_to

    async def _eventi_di(calendario: dict[str, Any]) -> list[dict[str, Any]]:
        resp = await _client().get(
            f"{_API_BASE}/calendars/{calendario['id']}/events",
            params=params,
            headers=_headers(access_token),
        )
        if resp.status_code != 200:
            raise CalendarError(f"Calendar events.list fallita: {resp.status_code}")
        return [estrai_evento(item, calendario["nome"]) for item in resp.json().get("items", [])]

    # In parallelo, non in sequenza: con più calendari collegati (comune per
    # un umano single-operator) le chiamate sequenziali sommavano un
    # round-trip di rete ciascuna (STOP 2 Tappa 6, 2026-07-19).
    per_calendario = await asyncio.gather(*(_eventi_di(c) for c in calendari))
    return [evento for lista in per_calendario for evento in lista]


async def sincronizza_eventi(
    access_token: str, calendar_id: str, sync_token: str | None
) -> tuple[list[dict], str]:
    """Incrementale per l'import in Memoria (vedi import_calendar.py):
    cursore nativo `syncToken` di Google Calendar, non un fetch a
    intervalli - stesso principio dell'`historyId` di Gmail. Se il token
    scade lato Google (410 Gone), fallback a fetch pieno con nuovo
    syncToken - dedup a valle (import_calendar.py) copre eventuali eventi
    già importati ripescati dal fetch pieno."""
    params: dict[str, str] = {"singleEvents": "true"}
    if sync_token:
        params["syncToken"] = sync_token

    eventi: list[dict] = []
    nuovo_sync_token = sync_token
    page_token: str | None = None
    while True:
        request_params = dict(params)
        if page_token:
            request_params["pageToken"] = page_token
        resp = await _client().get(
            f"{_API_BASE}/calendars/{calendar_id}/events",
            params=request_params, headers=_headers(access_token),
        )
        if resp.status_code == 410:
            return await sincronizza_eventi(access_token, calendar_id, None)
        if resp.status_code != 200:
            raise CalendarError(f"Calendar events.list (sync) fallita: {resp.status_code}")
        body = resp.json()
        eventi.extend(body.get("items", []))
        page_token = body.get("nextPageToken")
        if "nextSyncToken" in body:
            nuovo_sync_token = body["nextSyncToken"]
        if not page_token:
            break
    return eventi, nuovo_sync_token or ""


async def ottieni_evento(access_token: str, event_id: str, calendario: str | None = None) -> dict[str, Any]:
    calendar_id = await _risolvi_calendario_id(access_token, calendario)
    resp = await _client().get(
        f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
        headers=_headers(access_token),
    )
    if resp.status_code != 200:
        raise CalendarError(f"Calendar events.get fallita: {resp.status_code}")
    return estrai_evento(resp.json(), calendario)


async def crea_evento(
    access_token: str,
    titolo: str,
    inizio: str,
    fine: str,
    fuso_orario: str = "UTC",
    tutto_il_giorno: bool = False,
    descrizione: str | None = None,
    luogo: str | None = None,
    partecipanti: list[str] | None = None,
    promemoria_minuti: list[int] | None = None,
    ricorrenza: str | None = None,
    videochiamata: bool = False,
    occupato: bool | None = None,
    colore: str | None = None,
    calendario: str | None = None,
) -> dict[str, Any]:
    """Senza partecipanti: nessuna notifica esterna (evento privato). Con
    partecipanti: Google invia inviti reali - vedi gate in tools.py."""
    calendar_id = await _risolvi_calendario_id(access_token, calendario)
    body = _corpo_evento(
        titolo=titolo, inizio=inizio, fine=fine, fuso_orario=fuso_orario,
        tutto_il_giorno=tutto_il_giorno, descrizione=descrizione, luogo=luogo,
        partecipanti=partecipanti, promemoria_minuti=promemoria_minuti,
        ricorrenza=ricorrenza, videochiamata=videochiamata, occupato=occupato, colore=colore,
    )
    params: dict[str, str] = {"sendUpdates": "all" if partecipanti else "none"}
    if videochiamata:
        params["conferenceDataVersion"] = "1"
    resp = await _client().post(
        f"{_API_BASE}/calendars/{calendar_id}/events",
        params=params, headers=_headers(access_token), json=body,
    )
    if resp.status_code not in (200, 201):
        raise CalendarError(f"Calendar events.insert fallita: {resp.status_code}")
    return estrai_evento(resp.json(), calendario or "primary")


async def aggiorna_evento(
    access_token: str,
    event_id: str,
    *,
    notifica: bool,
    calendario: str | None = None,
    **campi: Any,
) -> dict[str, Any]:
    """`notifica` è deciso dal chiamante (tools.py, dopo aver verificato se
    l'evento ha partecipanti nuovi o esistenti - vedi gate in tools.py)."""
    calendar_id = await _risolvi_calendario_id(access_token, calendario)
    body = _corpo_evento(**campi)
    params: dict[str, str] = {"sendUpdates": "all" if notifica else "none"}
    if campi.get("videochiamata"):
        params["conferenceDataVersion"] = "1"
    resp = await _client().patch(
        f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
        params=params, headers=_headers(access_token), json=body,
    )
    if resp.status_code != 200:
        raise CalendarError(f"Calendar events.patch fallita: {resp.status_code}")
    return estrai_evento(resp.json(), calendario)


async def elimina_evento(
    access_token: str, event_id: str, *, notifica: bool, calendario: str | None = None
) -> None:
    calendar_id = await _risolvi_calendario_id(access_token, calendario)
    params: dict[str, str] = {"sendUpdates": "all" if notifica else "none"}
    resp = await _client().delete(
        f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
        params=params, headers=_headers(access_token),
    )
    if resp.status_code not in (200, 204):
        raise CalendarError(f"Calendar events.delete fallita: {resp.status_code}")


async def rispondi_invito(
    access_token: str, event_id: str, risposta: str, calendario: str | None = None
) -> dict[str, Any]:
    """Modifica SOLO il proprio responseStatus nell'array partecipanti
    (identificato da `self: true`, marcato da Google), mai gli altri
    partecipanti - trappola esplicita da test."""
    calendar_id = await _risolvi_calendario_id(access_token, calendario)
    resp = await _client().get(
        f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
        headers=_headers(access_token),
    )
    if resp.status_code != 200:
        raise CalendarError(f"Calendar events.get fallita: {resp.status_code}")
    evento_grezzo = resp.json()
    attendees = evento_grezzo.get("attendees", [])
    trovato = False
    for attendee in attendees:
        if attendee.get("self"):
            attendee["responseStatus"] = risposta
            trovato = True
    if not trovato:
        raise CalendarError("Non risulti tra i partecipanti di questo evento")

    resp = await _client().patch(
        f"{_API_BASE}/calendars/{calendar_id}/events/{event_id}",
        params={"sendUpdates": "all"},
        headers=_headers(access_token),
        json={"attendees": attendees},
    )
    if resp.status_code != 200:
        raise CalendarError(f"Calendar events.patch (RSVP) fallita: {resp.status_code}")
    return estrai_evento(resp.json(), calendario)


async def controlla_disponibilita(
    access_token: str, persone: list[str], date_from: str, date_to: str
) -> dict[str, list[dict[str, str]]]:
    """Rispetta `transparency`: un evento segnato "libero" da chi lo ha
    creato non risulta come occupato qui (comportamento nativo di Google
    freeBusy, non filtrato da noi)."""
    resp = await _client().post(
        f"{_API_BASE}/freeBusy",
        headers=_headers(access_token),
        json={
            "timeMin": date_from,
            "timeMax": date_to,
            "items": [{"id": email} for email in persone],
        },
    )
    if resp.status_code != 200:
        raise CalendarError(f"Calendar freeBusy.query fallita: {resp.status_code}")
    calendari = resp.json().get("calendars", {})
    return {email: dati.get("busy", []) for email, dati in calendari.items()}
