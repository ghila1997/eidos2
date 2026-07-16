"""Token effimeri per il client vocale (Tappa 6).

Pattern di produzione fin da subito (deciso a STOP 1): le key permanenti di
Deepgram/ElevenLabs vivono solo nell'env del server; il client (CLI vocale
oggi, browser a Tappa 7) riceve credenziali a scadenza e parla direttamente
coi fornitori — l'audio non attraversa mai il backend.

- Deepgram: POST /v1/auth/grant -> JWT, TTL 30s (il client lo chiede
  subito prima di aprire il WebSocket STT)
- ElevenLabs: POST /v1/single-use-token/tts_websocket -> token monouso,
  15 minuti, valido per il WebSocket TTS
Verificati sulla doc ufficiale dei fornitori 2026-07-16.
"""
from __future__ import annotations

import os

import httpx

DEEPGRAM_GRANT_URL = "https://api.deepgram.com/v1/auth/grant"
ELEVENLABS_TOKEN_URL = "https://api.elevenlabs.io/v1/single-use-token/tts_websocket"

SCADENZA_DEEPGRAM_SECONDI = 30
SCADENZA_ELEVENLABS_SECONDI = 900


class VoceNonConfigurata(Exception):
    """Manca almeno una key dei fornitori voce nell'env del server."""


class ErroreProviderVoce(Exception):
    """Un fornitore voce ha risposto con un errore: messaggio pulito,
    i dettagli interni del fornitore non arrivano mai al client."""


async def emetti_token() -> dict:
    deepgram_key = os.environ.get("DEEPGRAM_API_KEY")
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    if not deepgram_key or not elevenlabs_key:
        raise VoceNonConfigurata(
            "La voce non è configurata sul server (mancano le chiavi dei fornitori audio)."
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp_dg = await client.post(
            DEEPGRAM_GRANT_URL,
            headers={"Authorization": f"Token {deepgram_key}"},
            json={"ttl_seconds": SCADENZA_DEEPGRAM_SECONDI},
        )
        if resp_dg.status_code != 200:
            raise ErroreProviderVoce("Il servizio di trascrizione vocale non è raggiungibile.")

        resp_xi = await client.post(
            ELEVENLABS_TOKEN_URL,
            headers={"xi-api-key": elevenlabs_key},
        )
        if resp_xi.status_code != 200:
            raise ErroreProviderVoce("Il servizio di sintesi vocale non è raggiungibile.")

    return {
        "deepgram": {
            "token": resp_dg.json()["access_token"],
            "scadenza_secondi": resp_dg.json().get("expires_in", SCADENZA_DEEPGRAM_SECONDI),
        },
        "elevenlabs": {
            "token": resp_xi.json()["token"],
            "scadenza_secondi": SCADENZA_ELEVENLABS_SECONDI,
        },
    }
