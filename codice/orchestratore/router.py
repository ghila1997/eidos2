"""Endpoint dell'Orchestratore, montati sul backend già deployato di
Fondamenta - stessa auth via cookie di sessione (get_sessione_corrente),
così l'accesso da più dispositivi arriva gratis (vedi design Tappa 2,
decisione "Orchestratore server-side").

Il motore conversazionale è il ClaudeSDKClient persistente di agente.py
(Tappa 6): /chat e /chat/stream sono due viste sullo stesso motore —
il testo aspetta la risposta intera, la voce consuma lo stream SSE.
"""
from __future__ import annotations

import asyncio
import json
import logging

from claude_agent_sdk import ResultMessage
from claude_agent_sdk.types import StreamEvent
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel

from fondamenta.auth import get_sessione_corrente

from . import agente, azioni, import_calendar, import_mail, oauth, oauth_calendar, oauth_drive, ponte, voce_token

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    messaggio: str


class ConfermaRequest(BaseModel):
    conferma: bool


async def _blocca_se_azione_pendente(tenant_id: str) -> None:
    azione_pendente = await azioni.ottieni_azione_pendente_tenant(tenant_id)
    if azione_pendente is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "messaggio": "C'è un'azione in attesa di conferma, risolvila prima di continuare.",
                "azione_id": azione_pendente["id"],
                "tipo": azione_pendente["tipo"],
                "payload": azione_pendente["payload"],
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


def _riga_sse(evento: str, data: dict | None) -> str:
    return f"event: {evento}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _nome_tool_pulito(nome: str) -> str:
    """`mcp__<server>__<tool>` -> `<tool>`; i tool nativi restano invariati.
    Il client vocale mappa questo nome sui riempitivi ('un attimo, controllo...')."""
    if nome.startswith("mcp__"):
        return nome.split("__", 2)[2]
    return nome


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Variante streaming di /chat (SSE) per il client vocale (Tappa 6):
    eventi `delta` (testo man mano che il modello genera), `tool_in_corso`
    (alimenta i riempitivi vocali), `fine` (risposta completa + eventuale
    azione in attesa di conferma), `errore` (messaggio pulito, mai traceback).
    Stessa auth, stesso motore e stesso gate di /chat."""
    sessione = await get_sessione_corrente(request)
    tenant_id = sessione["tenant_id"]
    # il ponte parte SUBITO, in parallelo al controllo azioni pendenti
    # (~0,3s di Supabase): ogni decimo di secondo qui è silenzio in cuffia
    task_ponte = asyncio.create_task(ponte.genera_ponte(body.messaggio))
    try:
        await _blocca_se_azione_pendente(tenant_id)
    except HTTPException:
        task_ponte.cancel()
        raise

    motore = await agente.motore_per(tenant_id)

    async def genera():
        """Fonde due sorgenti: il turno dell'agente (in una coda alimentata da
        un task) e il ponte vocale (Haiku puro, vedi ponte.py). Regola d'oro:
        il ponte esce appena pronto SOLO se nessun testo del modello è ancora
        uscito — mai due voci, mai un ponte superfluo."""
        pezzi: list[str] = []
        coda: asyncio.Queue = asyncio.Queue()

        async def alimenta():
            try:
                async for m in motore.turno(body.messaggio, canale="voce"):
                    await coda.put(("messaggio", m))
                await coda.put(("fine_turno", None))
            except Exception as exc:
                await coda.put(("eccezione", exc))

        task_turno = asyncio.create_task(alimenta())
        testo_visto = False
        ponte_risolto = False
        try:
            while True:
                if not ponte_risolto and task_ponte.done():
                    ponte_risolto = True
                    # result() None = astensione (saluti/chiacchiere): la
                    # risposta vera arriva da sola, il ponte tace
                    if not testo_visto and task_ponte.exception() is None and task_ponte.result():
                        yield _riga_sse("ponte", {"testo": task_ponte.result()})
                try:
                    tipo, contenuto = await asyncio.wait_for(coda.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                if tipo == "eccezione":
                    raise contenuto
                if tipo == "fine_turno":
                    break
                message = contenuto
                if isinstance(message, StreamEvent):
                    evento = message.event
                    tipo_evento = evento.get("type")
                    if tipo_evento == "content_block_delta":
                        delta = evento.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            if not testo_visto:
                                testo_visto = True
                                if not ponte_risolto:
                                    ponte_risolto = True
                                    task_ponte.cancel()
                            yield _riga_sse("delta", {"testo": delta["text"]})
                    elif tipo_evento == "content_block_start":
                        blocco = evento.get("content_block") or {}
                        if blocco.get("type") == "tool_use":
                            yield _riga_sse(
                                "tool_in_corso",
                                {"tool": _nome_tool_pulito(blocco.get("name", ""))},
                            )
                elif isinstance(message, ResultMessage):
                    if message.subtype == "success" and message.result:
                        pezzi.append(message.result)

            azione_appena_creata = await azioni.ottieni_azione_pendente_tenant(tenant_id)
            yield _riga_sse(
                "fine",
                {"risposta": "\n".join(pezzi), "azione_in_attesa": azione_appena_creata},
            )
        except Exception:
            # I retry (client morto, errori transitori a monte) vivono nel
            # motore; qui arriva solo il fallimento definitivo. Mai traceback
            # nel flusso ("ogni guasto ha una voce", spec Tappa 6) — ma il
            # dettaglio vero va nel log, altrimenti è indiagnosticabile.
            logger.exception("errore durante lo stream di /chat/stream")
            yield _riga_sse(
                "errore",
                {"messaggio": "Non sono riuscito a elaborare la richiesta, riprova."},
            )
        finally:
            task_ponte.cancel()
            task_turno.cancel()

    return StreamingResponse(genera(), media_type="text/event-stream")


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
