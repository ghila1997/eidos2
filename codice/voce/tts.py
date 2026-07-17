"""TTS streaming ElevenLabs per un turno di risposta (Tappa 6).

Interfaccia astratta della spec §5: `invia(frase)` mentre il modello genera,
`chiudi()` a fine turno — cambiare motore TTS non tocca il resto del client.
Una sessione = un WS con un single-use token (una connessione per token).
L'audio ricevuto (PCM 16k, base64) va alle casse man mano che arriva.
"""
from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import urlencode

import websockets

from . import config
from .audio import Casse


class ErroreTTS(Exception):
    """Sintesi non disponibile: la risposta resta visibile a schermo."""


class SessioneTTS:
    def __init__(self, ws, casse: Casse, task_ricezione: asyncio.Task):
        self._ws = ws
        self.casse = casse
        self._task = task_ricezione

    async def invia(self, frase: str) -> None:
        # flush: genera subito la frase senza aspettare altro testo
        await self._ws.send(json.dumps({"text": frase + " ", "flush": True}))

    async def chiudi(self) -> None:
        """Fine testo: aspetta che arrivi tutto l'audio e che finisca di suonare."""
        try:
            await self._ws.send(json.dumps({"text": ""}))
            await asyncio.wait_for(self._task, timeout=60)
        except (asyncio.TimeoutError, websockets.WebSocketException, OSError):
            self._task.cancel()
        finally:
            self.casse.chiudi_e_attendi()
            try:
                await self._ws.close()
            except Exception:
                pass


async def apri_sessione(token: str) -> SessioneTTS:
    params = urlencode(
        {
            "model_id": config.TTS_MODEL,
            "output_format": config.TTS_OUTPUT_FORMAT,
            "single_use_token": token,
            "inactivity_timeout": config.TTS_INACTIVITY_TIMEOUT,
        }
    )
    url = config.TTS_URL.format(voice_id=config.TTS_VOICE_ID) + "?" + params
    try:
        ws = await websockets.connect(url)
        # messaggio di inizializzazione richiesto dal protocollo; speed <1
        # contrasta la prosodia frettolosa dei modelli turbo sui testi corti
        # (trovato a STOP 2 col riempitivo "velocizzato")
        await ws.send(
            json.dumps(
                {
                    "text": " ",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "speed": config.TTS_SPEED,
                    },
                }
            )
        )
    except (OSError, websockets.WebSocketException) as exc:
        raise ErroreTTS(
            "Il servizio di sintesi vocale non risponde: la risposta resta a schermo."
        ) from exc

    casse = Casse()
    casse.avvia()

    async def ricevi():
        try:
            async for messaggio in ws:
                dati = json.loads(messaggio)
                if dati.get("audio"):
                    casse.accoda(base64.b64decode(dati["audio"]))
                if dati.get("isFinal"):
                    return
        except (websockets.WebSocketException, OSError):
            return  # audio interrotto: gestito da chiudi()

    return SessioneTTS(ws, casse, asyncio.create_task(ricevi()))
