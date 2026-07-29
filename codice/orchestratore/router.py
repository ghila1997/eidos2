"""Endpoint dell'Orchestratore, montati sul backend già deployato di
Fondamenta - stessa auth via cookie di sessione (get_sessione_corrente),
così l'accesso da più dispositivi arriva gratis (vedi design Tappa 2,
decisione "Orchestratore server-side").

Il motore conversazionale è il ClaudeSDKClient persistente di agente.py
(Tappa 6): /chat e /chat/stream sono due viste sullo stesso motore —
il testo aspetta la risposta intera, la voce parla su una sessione
WebSocket persistente (vedi turno_vocale.py).
"""
from __future__ import annotations

from claude_agent_sdk import ResultMessage
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from fondamenta.auth import get_sessione_corrente

from . import agente, azioni, import_calendar, import_mail, oauth, oauth_calendar, oauth_drive, turno_vocale, voce_token
from .descrizioni_azioni import descrivi_azione

router = APIRouter()


class ChatRequest(BaseModel):
    messaggio: str


class ConfermaRequest(BaseModel):
    conferma: bool


async def _blocca_se_azione_pendente(tenant_id: str) -> None:
    # `azione_bloccante` scarta da sola una pendente scaduta (TTL pigra, Tappa
    # 7.2): una scheda dimenticata non tiene la chat bloccata per sempre.
    azione_pendente = await azioni.azione_bloccante(tenant_id)
    if azione_pendente is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "messaggio": "C'è un'azione in attesa di conferma, risolvila prima di continuare.",
                "azione_id": azione_pendente["id"],
                "tipo": azione_pendente["tipo"],
                "payload": azione_pendente["payload"],
                "descrizione": descrivi_azione(azione_pendente),
            },
        )


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    sessione = await get_sessione_corrente(request)
    tenant_id = sessione["tenant_id"]
    await _blocca_se_azione_pendente(tenant_id)

    motore = await agente.motore_per(tenant_id)
    pezzi: list[str] = []
    async for message in motore.turno(body.messaggio, canale="testo"):
        if isinstance(message, ResultMessage):
            if message.subtype == "success" and message.result:
                pezzi.append(message.result)

    azione_appena_creata = await azioni.ottieni_azione_pendente_tenant(tenant_id)
    if azione_appena_creata is not None:
        azione_appena_creata["descrizione"] = descrivi_azione(azione_appena_creata)
    return {
        "risposta": "\n".join(pezzi),
        "azione_in_attesa": azione_appena_creata,
    }


@router.post("/voice/token")
async def voice_token(request: Request):
    """Emette i token effimeri per il client vocale (vedi voce_token.py).
    Richiede la sessione di Fondamenta come ogni altro endpoint."""
    await get_sessione_corrente(request)
    try:
        return await voce_token.emetti_token()
    except voce_token.VoceNonConfigurata as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except voce_token.ErroreProviderVoce as exc:
        raise HTTPException(status_code=502, detail=str(exc))


async def _ricevi_da_websocket(websocket: WebSocket) -> dict:
    """Legge un messaggio JSON dal websocket, convertendo la disconnessione
    del client in ConnessioneChiusa (vocabolario di turno_vocale, non di
    FastAPI) - estratta da chat_stream_ws per essere testabile da sola."""
    try:
        return await websocket.receive_json()
    except WebSocketDisconnect:
        raise turno_vocale.ConnessioneChiusa()


async def _invia_su_websocket(websocket: WebSocket, evento: dict) -> None:
    """Specchio di _ricevi_da_websocket per l'invio - stessa conversione
    di eccezione, stessa ragione per l'estrazione."""
    try:
        await websocket.send_json(evento)
    except WebSocketDisconnect:
        raise turno_vocale.ConnessioneChiusa()


@router.websocket("/chat/stream")
async def chat_stream_ws(websocket: WebSocket):
    """Sessione vocale (Tappa 6, incr.4): il client manda ogni transcript
    stabile (parziale/finale), il server puo' scommettere prima
    dell'endpointing di Deepgram e interrompersi se l'utente continua a
    parlare - vedi orchestratore/turno_vocale.py e design doc
    docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md."""
    try:
        sessione = await get_sessione_corrente(websocket)
    except HTTPException:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        await turno_vocale.gestisci_sessione_vocale(
            sessione["tenant_id"],
            lambda: _ricevi_da_websocket(websocket),
            lambda evento: _invia_su_websocket(websocket, evento),
        )
    except turno_vocale.ConnessioneChiusa:
        pass


@router.post("/azioni/{azione_id}/conferma")
async def conferma(azione_id: str, body: ConfermaRequest, request: Request):
    sessione = await get_sessione_corrente(request)
    try:
        return await azioni.conferma_azione(sessione["tenant_id"], azione_id, body.conferma)
    except azioni.AzioneNonTrovata:
        raise HTTPException(status_code=404, detail="azione non trovata")
    except azioni.AzioneGiaRisolta as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/oauth/google/authorize")
async def oauth_authorize(request: Request):
    sessione = await get_sessione_corrente(request)
    return RedirectResponse(oauth.costruisci_url_autorizzazione(sessione["tenant_id"]))


@router.get("/oauth/google/callback")
async def oauth_callback(code: str, state: str):
    try:
        tenant_id = oauth.verifica_state(state)
    except oauth.StatoNonValido:
        raise HTTPException(status_code=400, detail="state non valido o scaduto")

    tokens = await oauth.scambia_codice(code)
    if "refresh_token" not in tokens:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google non ha restituito un refresh_token: rimuovi l'accesso "
                "app da myaccount.google.com/permissions e riprova (serve un "
                "nuovo consenso esplicito)."
            ),
        )
    await oauth.salva_credenziale(
        tenant_id, oauth.PROVIDER_GMAIL, oauth.GMAIL_SCOPES, tokens["refresh_token"]
    )
    return {"status": "ok"}


@router.post("/import-mail")
async def import_mail_endpoint(request: Request):
    sessione = await get_sessione_corrente(request)
    return await import_mail.esegui_import(sessione["tenant_id"])


@router.get("/oauth/google_calendar/authorize")
async def oauth_calendar_authorize(request: Request):
    sessione = await get_sessione_corrente(request)
    return RedirectResponse(oauth_calendar.costruisci_url_autorizzazione(sessione["tenant_id"]))


@router.get("/oauth/google_calendar/callback")
async def oauth_calendar_callback(code: str, state: str):
    try:
        tenant_id = oauth.verifica_state(state)
    except oauth.StatoNonValido:
        raise HTTPException(status_code=400, detail="state non valido o scaduto")

    tokens = await oauth_calendar.scambia_codice(code)
    if "refresh_token" not in tokens:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google non ha restituito un refresh_token: rimuovi l'accesso "
                "app da myaccount.google.com/permissions e riprova (serve un "
                "nuovo consenso esplicito)."
            ),
        )
    await oauth.salva_credenziale(
        tenant_id, oauth_calendar.PROVIDER_CALENDAR, oauth_calendar.CALENDAR_SCOPES, tokens["refresh_token"]
    )
    return {"status": "ok"}


@router.post("/import-calendar")
async def import_calendar_endpoint(request: Request):
    sessione = await get_sessione_corrente(request)
    return await import_calendar.esegui_import(sessione["tenant_id"])


@router.get("/oauth/google_drive/authorize")
async def oauth_drive_authorize(request: Request):
    sessione = await get_sessione_corrente(request)
    return RedirectResponse(oauth_drive.costruisci_url_autorizzazione(sessione["tenant_id"]))


@router.get("/oauth/google_drive/callback")
async def oauth_drive_callback(code: str, state: str):
    try:
        tenant_id = oauth.verifica_state(state)
    except oauth.StatoNonValido:
        raise HTTPException(status_code=400, detail="state non valido o scaduto")

    tokens = await oauth_drive.scambia_codice(code)
    if "refresh_token" not in tokens:
        raise HTTPException(
            status_code=400,
            detail=(
                "Google non ha restituito un refresh_token: rimuovi l'accesso "
                "app da myaccount.google.com/permissions e riprova (serve un "
                "nuovo consenso esplicito)."
            ),
        )
    await oauth.salva_credenziale(
        tenant_id, oauth_drive.PROVIDER_DRIVE, oauth_drive.DRIVE_SCOPES, tokens["refresh_token"]
    )
    return {"status": "ok"}
