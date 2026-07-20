"""Client vocale push-to-talk con generazione speculativa (Tappa 6,
incr.4).

Premi Invio, parla: appena il transcript resta stabile (RilevatoreFrase),
si manda un 'parziale' al server - che puo' gia' iniziare a generare prima
ancora che Deepgram segnali la fine della frase (endpointing 300ms). Se
continui a parlare, il server interrompe da solo il tentativo sbagliato
(evento 'annullato') e il client smette di pronunciarlo, in silenzio.

Il backend resta l'unico motore agentico; qui c'e' solo I/O audio e la
decisione locale di QUANDO mandare un parziale (design doc:
docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md).
"""
from __future__ import annotations

import asyncio
import time

import httpx

from cli import _carica_cookie, _descrivi_azione, _salva_cookie

from . import config, stt, tts
from .audio import ErroreAudio, Microfono
from .conferme import interpreta_transcript
from .frasi import SpezzaFrasi
from .rilevatore_frase import RilevatoreFrase
from .sanificazione import per_tts
from .sessione_ws import ErroreSessioneVoce, SessioneVoce


def _login_sincrono() -> str:
    """Login (o riuso cookie) con un client sincrono usa-e-getta; ritorna
    l'header Cookie da passare alla connessione WebSocket."""
    with httpx.Client(base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=60.0) as client:
        if client.get("/me").status_code == 200:
            return "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        print(f"Login su {config.BASE_URL}")
        email = input("Email: ").strip()
        password = input("Password: ").strip()
        resp = client.post("/login", json={"email": email, "password": password})
        if resp.status_code != 200:
            print(f"Login fallito ({resp.status_code}): {resp.text}")
            raise SystemExit(1)
        _salva_cookie(resp.cookies)
        print("Login riuscito.\n")
        return "; ".join(f"{k}={v}" for k, v in resp.cookies.items())


async def _token_voce(client: httpx.AsyncClient) -> dict:
    resp = await client.post("/voice/token")
    if resp.status_code != 200:
        dettaglio = resp.json().get("detail", "errore sconosciuto")
        raise RuntimeError(f"Token voce non disponibili: {dettaglio}")
    return resp.json()


async def _ascolta_e_specula(
    sessione: SessioneVoce, token_deepgram: str
) -> str:
    """Ascolta il microfono; ogni volta che il transcript resta stabile
    (RilevatoreFrase) manda un 'parziale' al server - non aspetta piu' solo
    il transcript finale per iniziare a informare il server. Ritorna il
    transcript finale (per la stampa a schermo/gestione conferme)."""
    microfono = Microfono()
    rilevatore = RilevatoreFrase()
    print("… parla pure (mi fermo quando fai una pausa)")

    def su_interim(testo: str) -> None:
        print(f"\r  {testo}", end="", flush=True)
        candidato = rilevatore.aggiorna(testo, time.monotonic())
        if candidato:
            asyncio.ensure_future(sessione.manda_parziale(candidato))

    transcript = await stt.trascrivi_turno(token_deepgram, microfono, su_interim)
    print()
    if transcript:
        await sessione.manda_finale(transcript)
    return transcript


async def _pronuncia_eventi_turno(sessione: SessioneVoce) -> dict | None:
    """Consuma gli eventi del server per il turno corrente, li pronuncia,
    gestisce 'annullato' fermando subito il TTS senza dire nulla. Ritorna
    l'azione in attesa di conferma (se il turno ne ha creata una)."""
    spezza = SpezzaFrasi()
    sessione_tts: tts.SessioneTTS | None = None
    azione: dict | None = None

    async def assicura_tts(client: httpx.AsyncClient) -> tts.SessioneTTS:
        nonlocal sessione_tts
        if sessione_tts is None:
            tokens = await _token_voce(client)
            sessione_tts = await tts.apri_sessione(tokens["elevenlabs"]["token"])
        return sessione_tts

    try:
        async with httpx.AsyncClient(
            base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=180.0
        ) as client_http:
            async for evento in sessione.eventi():
                tipo = evento["evento"]
                if tipo == "annullato":
                    if sessione_tts is not None:
                        await sessione_tts.chiudi()
                        sessione_tts = None
                    spezza = SpezzaFrasi()
                    print("\n(tentativo annullato, riparto)", flush=True)
                    continue
                if tipo == "ponte":
                    print(f"(ponte: {evento['testo']})", flush=True)
                    ses = await assicura_tts(client_http)
                    await ses.invia(per_tts(evento["testo"]))
                    continue
                if tipo == "tool_in_corso":
                    print(f"\n[{evento['tool']}…]", flush=True)
                    continue
                if tipo == "delta":
                    print(evento["testo"], end="", flush=True)
                    for frase in spezza.aggiungi(evento["testo"]):
                        ses = await assicura_tts(client_http)
                        await ses.invia(per_tts(frase))
                    continue
                if tipo == "errore":
                    for frase in spezza.chiudi():
                        ses = await assicura_tts(client_http)
                        await ses.invia(per_tts(frase))
                    print(f"\n{evento['messaggio']}")
                    ses = await assicura_tts(client_http)
                    await ses.invia(per_tts(evento["messaggio"]))
                    break
                if tipo == "fine":
                    for frase in spezza.chiudi():
                        ses = await assicura_tts(client_http)
                        await ses.invia(per_tts(frase))
                    azione = evento.get("azione_in_attesa")
                    if azione:
                        print(f"\n\n[Conferma richiesta] {_descrivi_azione(azione)}")
                        ses = await assicura_tts(client_http)
                        await ses.invia(per_tts(
                            f"Serve la tua conferma: {_descrivi_azione(azione)}. "
                            "Premi Invio e rispondi con un si' o con un no."
                        ))
                    print()
                    break
    finally:
        # garantito anche sui percorsi d'eccezione (connessione WS persa,
        # errore TTS): senza questo, un'eccezione qui sopra lascerebbe la
        # sessione TTS aperta e il thread delle casse bloccato in attesa
        # (Casse.chiudi_e_attendi non viene mai chiamato) - stessa garanzia
        # che il vecchio client.py dava con un try/finally attorno al turno.
        if sessione_tts is not None:
            await sessione_tts.chiudi()
    return azione


async def _turno_conferma(azione: dict, transcript: str) -> bool:
    """True se l'azione e' stata risolta (confermata o annullata). Le
    conferme passano ancora dal REST esistente (/azioni/{id}/conferma),
    non dal WebSocket - e' un'azione singola, non un turno di generazione."""
    conferma = interpreta_transcript(transcript)
    async with httpx.AsyncClient(
        base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=60.0
    ) as client:
        if conferma is None:
            await _pronuncia_singola(client, "Non ho capito: rispondi con un si' o con un no chiaro.")
            return False
        resp = await client.post(f"/azioni/{azione['id']}/conferma", json={"conferma": conferma})
        if resp.status_code != 200:
            print(f"Errore nella conferma ({resp.status_code}): {resp.text}")
            await _pronuncia_singola(client, "Non sono riuscito a registrare la conferma.")
            return False
        stato = resp.json()["stato"]
        esito = "Fatto." if stato == "confermata_inviata" else "Azione annullata."
        print(esito)
        await _pronuncia_singola(client, esito)
        return True


async def _pronuncia_singola(client: httpx.AsyncClient, testo: str) -> None:
    try:
        tokens = await _token_voce(client)
        sessione = await tts.apri_sessione(tokens["elevenlabs"]["token"])
    except (tts.ErroreTTS, RuntimeError):
        return
    try:
        try:
            await sessione.invia(per_tts(testo))
        finally:
            await sessione.chiudi()
    except Exception:
        pass


async def _loop(cookie: str) -> None:
    sessione = await SessioneVoce.connetti(cookie)
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=60.0) as client:
        tokens = await _token_voce(client)
    token_deepgram = tokens["deepgram"]["token"]

    print("Eidos voce — premi Invio e parla (Ctrl+C per uscire)\n")
    azione_in_attesa: dict | None = None
    while True:
        try:
            await asyncio.to_thread(input, "[Invio per parlare] ")
            transcript = await _ascolta_e_specula(sessione, token_deepgram)
            if not transcript:
                print("Non ho sentito nulla, riprova.")
                continue
            print(f"Tu: {transcript}\n")

            if azione_in_attesa is not None:
                if await _turno_conferma(azione_in_attesa, transcript):
                    azione_in_attesa = None
                continue

            azione_in_attesa = await _pronuncia_eventi_turno(sessione)
        except (stt.ErroreSTT, tts.ErroreTTS, ErroreAudio, ErroreSessioneVoce, RuntimeError) as exc:
            print(f"\n{exc}")


def main() -> None:
    try:
        cookie = _login_sincrono()
        asyncio.run(_loop(cookie))
    except KeyboardInterrupt:
        print("\nA presto.")
