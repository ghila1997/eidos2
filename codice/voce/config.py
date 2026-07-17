"""Configurazione del client vocale (Tappa 6). Override via env EIDOS_VOCE_*."""
from __future__ import annotations

import os

BASE_URL = os.environ.get("EIDOS_API_BASE_URL", "https://eidos2-api-production.up.railway.app")

# STT Deepgram (parametri della spec §4, verificati su doc 2026-07-16)
STT_URL = "wss://api.deepgram.com/v1/listen"
STT_PARAMS = {
    "model": os.environ.get("EIDOS_VOCE_STT_MODEL", "nova-3"),
    "language": "it",
    "interim_results": "true",
    "endpointing": os.environ.get("EIDOS_VOCE_ENDPOINTING", "300"),
    "smart_format": "true",
    "vad_events": "true",
    "encoding": "linear16",
    "sample_rate": "16000",
}

# TTS ElevenLabs (WS stream-input; il token monouso va nel query param
# single_use_token, verificato su doc 2026-07-16)
TTS_URL = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
TTS_VOICE_ID = os.environ.get("EIDOS_VOCE_TTS_VOICE", "21m00Tcm4TlvDq8ikWAM")
TTS_MODEL = os.environ.get("EIDOS_VOCE_TTS_MODEL", "eleven_turbo_v2_5")
TTS_OUTPUT_FORMAT = "pcm_16000"
TTS_INACTIVITY_TIMEOUT = "180"  # tool lunghi: la sessione TTS non deve cadere

TTS_SPEED = float(os.environ.get("EIDOS_VOCE_TTS_SPEED", "0.95"))

SAMPLE_RATE = 16000            # condiviso da mic e casse
CHUNK_MS = 50                  # dimensione blocco mic
SILENZIO_MAX_SECONDI = 12      # nessun parlato: il turno si chiude da solo

# Riempitivi locali disattivati su richiesta dell'utente (STOP 2, 2026-07-17):
# resta l'apertura contestuale a discrezione del modello (prompt vocale).
# Riattivabili con EIDOS_VOCE_RIEMPITIVI=1 quando si rivaluta.
RIEMPITIVI_ATTIVI = os.environ.get("EIDOS_VOCE_RIEMPITIVI", "0") == "1"
PRIMO_RIEMPITIVO_SECONDI = 1.5 # silenzio dopo la domanda: riempitivo su timer
ATTESA_LUNGA_SECONDI = 10      # secondo riempitivo ("ancora un momento...")
