"""Cattura microfono e riproduzione casse (sounddevice). Import pigro:
il resto del pacchetto voce (logica pura) non deve richiedere PortAudio,
così i test girano anche in CI senza dispositivi audio."""
from __future__ import annotations

import queue
import threading

from . import config


class ErroreAudio(Exception):
    """Mic o casse non disponibili: messaggio chiaro, mai stack trace."""


def _sounddevice():
    try:
        import sounddevice
        return sounddevice
    except OSError as exc:  # PortAudio mancante/rotto
        raise ErroreAudio(f"Audio non disponibile su questa macchina: {exc}") from exc


class Microfono:
    """Cattura continua in blocchi PCM 16kHz/16bit/mono su una coda."""

    def __init__(self) -> None:
        self._sd = _sounddevice()
        self.coda: queue.Queue[bytes] = queue.Queue()
        self._stream = None

    def avvia(self) -> None:
        blocco = int(config.SAMPLE_RATE * config.CHUNK_MS / 1000)

        def _callback(indata, frames, time_info, status):
            self.coda.put(bytes(indata))

        try:
            self._stream = self._sd.RawInputStream(
                samplerate=config.SAMPLE_RATE,
                blocksize=blocco,
                channels=1,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
        except Exception as exc:
            raise ErroreAudio(
                "Non riesco ad aprire il microfono: controlla che sia collegato "
                f"e non in uso da un'altra app. ({type(exc).__name__})"
            ) from exc

    def ferma(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        # svuota la coda: il prossimo turno riparte pulito
        while not self.coda.empty():
            self.coda.get_nowait()


class Casse:
    """Riproduzione PCM in un thread dedicato: i chunk arrivano dal WS TTS
    e si accodano; la riproduzione non blocca il loop asincrono."""

    def __init__(self) -> None:
        self._sd = _sounddevice()
        self._coda: queue.Queue[bytes | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self.ha_suonato = False

    def avvia(self) -> None:
        self._thread = threading.Thread(target=self._riproduci, daemon=True)
        self._thread.start()

    def _riproduci(self) -> None:
        try:
            with self._sd.RawOutputStream(
                samplerate=config.SAMPLE_RATE, channels=1, dtype="int16"
            ) as stream:
                while True:
                    chunk = self._coda.get()
                    if chunk is None:
                        return
                    self.ha_suonato = True
                    stream.write(chunk)
        except Exception:
            # le casse cadute non devono uccidere il client: la risposta
            # resta comunque visibile a schermo (spec §8)
            while self._coda.get() is not None:
                pass

    def accoda(self, pcm: bytes) -> None:
        self._coda.put(pcm)

    def chiudi_e_attendi(self) -> None:
        """Segnala fine coda e aspetta che l'audio finisca di suonare."""
        self._coda.put(None)
        if self._thread is not None:
            self._thread.join()
            self._thread = None
