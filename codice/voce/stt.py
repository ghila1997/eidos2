"""STT streaming Deepgram per un turno di parlato (push-to-talk, Tappa 6).

Un turno = apri WS con token effimero (Bearer JWT, serve valido solo alla
connessione — verificato su doc), invia i blocchi mic, accumula i final,
chiudi a `speech_final` (endpointing 300ms). Gli interim alimentano la
trascrizione live a schermo.
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable
from urllib.parse import urlencode

import websockets

from . import config
from .audio import Microfono


class ErroreSTT(Exception):
    """Trascrizione non riuscita: messaggio pulito per l'utente."""


async def trascrivi_turno(
    token: str,
    microfono: Microfono,
    su_interim: Callable[[str], None] = lambda t: None,
) -> str:
    """Ascolta finché Deepgram segnala fine frase; ritorna il transcript
    completo (stringa vuota = nessun parlato entro il tempo massimo)."""
    url = f"{config.STT_URL}?{urlencode(config.STT_PARAMS)}"
    try:
        async with websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            microfono.avvia()
            try:
                return await asyncio.wait_for(
                    _conversa(ws, microfono, su_interim),
                    timeout=config.SILENZIO_MAX_SECONDI + 30,
                )
            finally:
                microfono.ferma()
    except (OSError, websockets.WebSocketException) as exc:
        raise ErroreSTT(
            "Ho un problema di connessione col servizio di trascrizione, riprova."
        ) from exc
    except asyncio.TimeoutError:
        return ""


async def _conversa(ws, microfono: Microfono, su_interim) -> str:
    finali: list[str] = []
    parlato_iniziato = asyncio.Event()

    async def invia_audio():
        inattivita = 0.0
        while True:
            try:
                chunk = microfono.coda.get_nowait()
                await ws.send(chunk)
                inattivita = 0.0
            except Exception:
                await asyncio.sleep(0.02)
                inattivita += 0.02
                # nessun parlato mai iniziato entro il massimo: turno vuoto
                if not parlato_iniziato.is_set() and inattivita > config.SILENZIO_MAX_SECONDI:
                    await ws.send(json.dumps({"type": "CloseStream"}))
                    return

    task_invio = asyncio.create_task(invia_audio())
    try:
        async for messaggio in ws:
            dati = json.loads(messaggio)
            if dati.get("type") == "SpeechStarted":
                parlato_iniziato.set()
                continue
            if dati.get("type") != "Results":
                continue
            alternativa = dati.get("channel", {}).get("alternatives", [{}])[0]
            transcript = alternativa.get("transcript", "")
            if transcript:
                parlato_iniziato.set()
                su_interim(" ".join(finali + [transcript]))
            if dati.get("is_final") and transcript:
                finali.append(transcript)
            if dati.get("speech_final") and finali:
                return " ".join(finali)
        return " ".join(finali)
    finally:
        task_invio.cancel()
