"""Montaggio dell'interfaccia web nel backend FastAPI (Tappa 7.1).

Same-origin: la pagina statica e' servita dallo stesso backend che espone
gli endpoint, quindi il cookie di sessione di Fondamenta
(`get_sessione_corrente`, `samesite=lax`) vale senza CORS. Un solo punto di
aggancio: `configura(app)` monta gli statici e include il router (WS + `/`).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fondamenta.auth import get_sessione_corrente

from . import sessione_web

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX = STATIC_DIR / "index.html"

router = APIRouter()


@router.get("/")
async def index() -> FileResponse:
    """La pagina non e' protetta: si carica sempre, poi il JS chiama /me per
    decidere se mostrare il login o la scena (il cookie e' httponly, la
    decisione la prende il server via /me, non il client leggendo il cookie)."""
    return FileResponse(INDEX)


async def _ricevi(websocket: WebSocket) -> dict:
    """Legge un messaggio JSON dal client convertendo la disconnessione nel
    vocabolario di sessione_web (non FastAPI), cosi' il ciclo e' testabile
    senza un vero WebSocket - stesso pattern del turno vocale."""
    try:
        return await websocket.receive_json()
    except WebSocketDisconnect:
        raise sessione_web.ConnessioneChiusa()


async def _invia(websocket: WebSocket, evento: dict) -> None:
    try:
        await websocket.send_json(evento)
    except WebSocketDisconnect:
        raise sessione_web.ConnessioneChiusa()


@router.websocket("/ws/session")
async def ws_session(websocket: WebSocket) -> None:
    """Canale unico della UI web (DECISIONS.md 2026-07-28 pt.3). In 7.1
    multiplexa un turno di solo testo in streaming; le tappe successive vi
    aggiungono log/conferme/voce sullo stesso canale."""
    try:
        sessione = await get_sessione_corrente(websocket)
    except HTTPException:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        await sessione_web.gestisci_sessione(
            sessione["tenant_id"],
            lambda: _ricevi(websocket),
            lambda evento: _invia(websocket, evento),
        )
    except sessione_web.ConnessioneChiusa:
        pass


def configura(app: FastAPI) -> None:
    """Monta gli statici su /static e include il router (WS + pagina). Da
    chiamare per ultimo in app.py: la rotta `/` non deve mascherare rotte
    piu' specifiche degli altri router (qui non succede, ma l'ordine e'
    esplicito)."""
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
