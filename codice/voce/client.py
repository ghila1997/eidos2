"""Client vocale push-to-talk (Tappa 6).

Premi Invio, parla: si manda il transcript finale al server via WebSocket
persistente (protocollo di /chat/stream, design doc:
docs/superpowers/specs/2026-07-19-speculativo-vocale-design.md).

Speculativo (scommettere su un transcript parziale prima della fine della
frase) DISATTIVATO su richiesta dell'utente (STOP 2, 2026-07-22): scattava
anche su normali pause di respiro a meta' frase, sentito come innaturale.
L'infrastruttura resta pronta (voce/rilevatore_frase.py, SessioneVoce.
manda_parziale, l'interrupt sicuro server-side in turno_vocale.py) - non
rimossa, solo non collegata qui. Vedi DECISIONS.md per la decisione.
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


async def _ascolta(sessione: SessioneVoce, token_deepgram: str) -> str:
    """Ascolta il microfono e ritorna il transcript finale.

    Speculativo disattivato su richiesta dell'utente (STOP 2, 2026-07-22):
    la scommessa su un parziale 'stabile' scattava anche su normali pause
    di respiro a meta' frase, con un tentativo poi scartato (annullato) -
    l'infrastruttura per lo speculativo (RilevatoreFrase, manda_parziale,
    l'interrupt sicuro server-side) resta intatta e pronta, semplicemente
    non e' piu' collegata qui: si manda solo il transcript finale, come
    prima di questo incremento."""
    microfono = Microfono()
    print("… parla pure (mi fermo quando fai una pausa)")
    ultimo_interim_a = time.monotonic()

    def su_interim(testo: str) -> None:
        nonlocal ultimo_interim_a
        ultimo_interim_a = time.monotonic()
        print(f"\r  {testo}", end="", flush=True)

    transcript = await stt.trascrivi_turno(token_deepgram, microfono, su_interim)
    # diagnostica STOP 2: quanto ci mette Deepgram a chiudere la frase dopo
    # l'ultimo aggiornamento della trascrizione live (endpointing atteso
    # ~0.3s - se questo numero e' alto, il ritardo e' qui, non nel motore)
    print(f"\n(chiusura trascrizione: {time.monotonic() - ultimo_interim_a:.1f}s)")
    if transcript:
        await sessione.manda_finale(transcript)
    return transcript


async def _apri_tts(client: httpx.AsyncClient) -> tts.SessioneTTS:
    tokens = await _token_voce(client)
    return await tts.apri_sessione(tokens["elevenlabs"]["token"])


async def _apri_tts_misurato(
    client: httpx.AsyncClient, t0: float, tempi: dict[str, float]
) -> tts.SessioneTTS:
    """Come _apri_tts, ma registra SUBITO quando l'handshake finisce
    davvero, non quando qualcuno lo richiede. Senza questo, 'tts_pronto'
    (registrato in assicura_tts) misura anche l'attesa della prima frase
    completa dell'LLM se l'handshake finisce prima - numero fuorviante,
    trovato a STOP 2 (2026-07-22) confrontando 'risposta' e 'tts_pronto'."""
    sessione = await _apri_tts(client)
    tempi.setdefault("handshake_tts_reale", time.monotonic() - t0)
    return sessione


async def _pronuncia_eventi_turno(sessione: SessioneVoce) -> dict | None:
    """Consuma gli eventi del server per il turno corrente, li pronuncia,
    gestisce 'annullato' fermando subito il TTS senza dire nulla. Ritorna
    l'azione in attesa di conferma (se il turno ne ha creata una)."""
    spezza = SpezzaFrasi()
    sessione_tts: tts.SessioneTTS | None = None
    azione: dict | None = None
    t0 = time.monotonic()  # fine del parlato: base del cronometro per turno
    tempi: dict[str, float] = {}

    try:
        async with httpx.AsyncClient(
            base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=180.0
        ) as client_http:
            # prefetch: token+WS ElevenLabs partono subito, in parallelo con
            # l'attesa dei primi eventi dal server, invece di aprirli solo al
            # primo bisogno. Diagnosi reale STOP 2 (2026-07-22): 'tts_pronto'
            # era quasi tutto il tempo del turno (handshake mai sovrapposto a
            # nient'altro) - il token resta comunque preso qui, non prima
            # (single-use, stessa ragione del fix sul token Deepgram sopra)
            tentativo_tts = asyncio.create_task(_apri_tts_misurato(client_http, t0, tempi))

            async def assicura_tts() -> tts.SessioneTTS:
                nonlocal sessione_tts
                if sessione_tts is None:
                    sessione_tts = await tentativo_tts
                    tempi.setdefault("tts_pronto", time.monotonic() - t0)
                return sessione_tts

            async for evento in sessione.eventi():
                tipo = evento["evento"]
                if tipo == "annullato":
                    if sessione_tts is not None:
                        await sessione_tts.chiudi()
                        sessione_tts = None
                    else:
                        tentativo_tts.cancel()
                    spezza = SpezzaFrasi()
                    tempi.clear()  # il cronometro riparte col tentativo vero
                    tentativo_tts = asyncio.create_task(
                        _apri_tts_misurato(client_http, t0, tempi)
                    )
                    print("\n(tentativo annullato, riparto)", flush=True)
                    continue
                if tipo == "ponte":
                    tempi["ponte"] = time.monotonic() - t0
                    print(f"(ponte: {evento['testo']})", flush=True)
                    ses = await assicura_tts()
                    await ses.invia(per_tts(evento["testo"]))
                    continue
                if tipo == "tool_in_corso":
                    print(f"\n[{evento['tool']}…]", flush=True)
                    continue
                if tipo == "delta":
                    tempi.setdefault("risposta", time.monotonic() - t0)
                    print(evento["testo"], end="", flush=True)
                    for frase in spezza.aggiungi(evento["testo"]):
                        ses = await assicura_tts()
                        await ses.invia(per_tts(frase))
                    continue
                if tipo == "errore":
                    for frase in spezza.chiudi():
                        ses = await assicura_tts()
                        await ses.invia(per_tts(frase))
                    print(f"\n{evento['messaggio']}")
                    ses = await assicura_tts()
                    await ses.invia(per_tts(evento["messaggio"]))
                    break
                if tipo == "fine":
                    for frase in spezza.chiudi():
                        ses = await assicura_tts()
                        await ses.invia(per_tts(frase))
                    azione = evento.get("azione_in_attesa")
                    if azione:
                        print(f"\n\n[Conferma richiesta] {_descrivi_azione(azione)}")
                        ses = await assicura_tts()
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
        if sessione_tts is None:
            # il prefetch puo' essere finito senza che nessuno l'abbia mai
            # atteso (turno senza testo da pronunciare) - va comunque
            # recuperato e chiuso, altrimenti la connessione WS aperta resta
            # a perdere insieme al thread delle casse
            tentativo_tts.cancel()
            try:
                sessione_tts = await tentativo_tts
            except (asyncio.CancelledError, tts.ErroreTTS, RuntimeError):
                sessione_tts = None
        if sessione_tts is not None:
            await sessione_tts.chiudi()
            if sessione_tts.primo_audio_monotonic is not None:
                tempi["primo_audio"] = sessione_tts.primo_audio_monotonic - t0
    pezzi_tempo = [f"{nome} {secondi:.1f}s" for nome, secondi in tempi.items()]
    pezzi_tempo.append(f"totale {time.monotonic() - t0:.1f}s")
    print(f"(tempi: {' · '.join(pezzi_tempo)})")
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


async def _token_deepgram_fresco() -> str:
    """Il token Deepgram dura solo 30s (grant JWT, vedi voce_token.py) - va
    ripreso a ogni turno, non una volta sola all'avvio della sessione.
    Trovato in reale (STOP 2, 2026-07-20): dopo un paio di turni il token
    preso all'avvio era gia' scaduto, la connessione Deepgram del turno
    successivo falliva a meta' frase con un errore di connessione."""
    async with httpx.AsyncClient(
        base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=60.0
    ) as client:
        tokens = await _token_voce(client)
    return tokens["deepgram"]["token"]


async def _loop(cookie: str) -> None:
    sessione = await SessioneVoce.connetti(cookie)

    print("Eidos voce — premi Invio e parla (Ctrl+C per uscire)\n")
    azione_in_attesa: dict | None = None
    while True:
        try:
            await asyncio.to_thread(input, "[Invio per parlare] ")
            token_deepgram = await _token_deepgram_fresco()
            transcript = await _ascolta(sessione, token_deepgram)
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
