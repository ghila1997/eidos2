"""Connessione WebSocket persistente verso /chat/stream (Tappa 6, incr.4).

Wrapper di I/O puro (rete): verificato in reale (STOP 2), non con unit
test - stessa convenzione di stt.py/tts.py in questo pacchetto (vedi
voce/__init__.py). La logica di decisione (quando interrompere, quando
lasciar proseguire) vive server-side in orchestratore/turno_vocale.py,
gia' testata li'.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import websockets

from . import config


class ErroreSessioneVoce(Exception):
    """Connessione al server persa: il turno corrente va gestito come
    fallito, il chiamante decide se riprovare."""


class SessioneVoce:
    def __init__(self, ws):
        self._ws = ws

    @staticmethod
    async def connetti(cookie: str) -> "SessioneVoce":
        url = config.BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/chat/stream"
        try:
            ws = await websockets.connect(url, additional_headers={"Cookie": cookie})
        except (OSError, websockets.WebSocketException) as exc:
            raise ErroreSessioneVoce(f"Non riesco a collegarmi al server vocale: {exc}") from exc
        return SessioneVoce(ws)

    async def manda_parziale(self, testo: str) -> None:
        await self._ws.send(json.dumps({"tipo": "parziale", "testo": testo}))

    async def manda_finale(self, testo: str) -> None:
        await self._ws.send(json.dumps({"tipo": "finale", "testo": testo}))

    async def eventi(self) -> AsyncIterator[dict]:
        """Itera gli eventi del server per QUESTA sessione (non solo un
        turno): il chiamante distingue i tentativi dagli eventi stessi
        (ponte/delta/tool_in_corso appartengono al tentativo corrente,
        annullato segna la fine di un tentativo scartato, fine/errore la
        fine di un turno vero)."""
        try:
            async for messaggio in self._ws:
                yield json.loads(messaggio)
        except websockets.WebSocketException as exc:
            raise ErroreSessioneVoce(f"Connessione al server vocale interrotta: {exc}") from exc

    async def chiudi(self) -> None:
        try:
            await self._ws.close()
        except Exception:
            pass
