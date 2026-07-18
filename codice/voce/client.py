"""Client vocale push-to-talk (Tappa 6, incremento 2).

Premi Invio, parla: l'endpointing Deepgram chiude il turno (300ms di
silenzio), il transcript va a POST /chat/stream, le frasi della risposta
vanno in sintesi mentre il modello genera. Le azioni distruttive arrivano
come azione pending: la descrizione viene letta ad alta voce e la conferma
è il confronto deterministico del transcript con l'elenco chiuso del CLI
(voce/conferme.py) — mai un'interpretazione del modello.

Il backend resta l'unico motore agentico; qui c'è solo I/O audio
(design STOP 1). Riuso deliberato di cli.py per login/cookie/descrizioni.
Tutto il turno è asincrono: lo stream HTTP, il WS TTS e il watchdog dei
riempitivi convivono nello stesso event loop — un HTTP sincrono qui
bloccherebbe l'audio durante i tool lunghi.
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
from .riempitivi import GestoreRiempitivi
from .sanificazione import per_tts
from .sse import ParserSSE


def _login_sincrono() -> dict:
    """Login (o riuso cookie) con un client sincrono usa-e-getta; ritorna
    i cookie validi da passare al client asincrono del loop vocale."""
    with httpx.Client(base_url=config.BASE_URL, cookies=_carica_cookie(), timeout=60.0) as client:
        if client.get("/me").status_code == 200:
            return dict(client.cookies)
        print(f"Login su {config.BASE_URL}")
        email = input("Email: ").strip()
        password = input("Password: ").strip()
        resp = client.post("/login", json={"email": email, "password": password})
        if resp.status_code != 200:
            print(f"Login fallito ({resp.status_code}): {resp.text}")
            raise SystemExit(1)
        _salva_cookie(resp.cookies)
        print("Login riuscito.\n")
        return dict(resp.cookies)


async def _token_voce(client: httpx.AsyncClient) -> dict:
    resp = await client.post("/voice/token")
    if resp.status_code != 200:
        dettaglio = resp.json().get("detail", "errore sconosciuto")
        raise RuntimeError(f"Token voce non disponibili: {dettaglio}")
    return resp.json()


async def _ascolta(token_deepgram: str) -> str:
    microfono = Microfono()
    print("… parla pure (mi fermo quando fai una pausa)")

    def su_interim(testo: str) -> None:
        print(f"\r  {testo}", end="", flush=True)

    transcript = await stt.trascrivi_turno(token_deepgram, microfono, su_interim)
    print()
    return transcript


async def _turno_risposta(
    client: httpx.AsyncClient, messaggio: str, sessione_tts: tts.SessioneTTS
) -> dict | None:
    """Invia il messaggio a /chat/stream e pronuncia la risposta in streaming.
    La sessione TTS arriva già aperta (preparata mentre l'utente parlava):
    il timer del riempitivo parte da qui, cioè dalla fine del parlato, senza
    pagare token e handshake nel silenzio (trovato a STOP 2, ~5s percepiti).
    Ritorna l'azione in attesa di conferma, se il turno ne ha creata una."""
    spezza = SpezzaFrasi()
    riempitivi = GestoreRiempitivi()
    parser = ParserSSE()
    azione: dict | None = None
    errore_stream: str | None = None
    t0 = time.monotonic()  # fine del parlato: base del cronometro per turno
    tempi: dict[str, float] = {}
    ultimo_audio = time.monotonic()

    async def pronuncia(frase: str) -> None:
        nonlocal ultimo_audio
        pulita = per_tts(frase)
        if pulita:
            await sessione_tts.invia(pulita)
            ultimo_audio = time.monotonic()

    ultimo_tool = ""

    async def watchdog_attesa() -> None:
        """Il silenzio non segnalato è il guasto peggiore (spec §5): il primo
        riempitivo parte su timer, non solo sull'evento tool — il modello può
        'pensare' secondi prima di chiamare il primo tool (trovato a STOP 2)."""
        while True:
            await asyncio.sleep(0.5)
            if sessione_tts.casse.ha_suonato:
                riempitivi.su_audio_risposta()
            trascorso = time.monotonic() - ultimo_audio
            if trascorso > config.PRIMO_RIEMPITIVO_SECONDI:
                frase = riempitivi.su_tool(ultimo_tool)
                if frase:
                    print(f"\n(riempitivo: {frase})", flush=True)
                    await pronuncia(frase)
            if trascorso > config.ATTESA_LUNGA_SECONDI:
                frase = riempitivi.su_attesa_lunga()
                if frase:
                    print(f"\n(riempitivo: {frase})", flush=True)
                    await pronuncia(frase)

    watchdog = asyncio.create_task(watchdog_attesa()) if config.RIEMPITIVI_ATTIVI else None
    try:
        async with client.stream(
            "POST", "/chat/stream", json={"messaggio": messaggio}
        ) as resp:
            if resp.status_code == 409:
                await resp.aread()
                dettaglio = resp.json()["detail"]
                return {
                    "id": dettaglio["azione_id"],
                    "tipo": dettaglio["tipo"],
                    "payload": dettaglio["payload"],
                }
            if resp.status_code != 200:
                await resp.aread()
                print(f"Errore ({resp.status_code}): {resp.text}")
                await pronuncia("Ho avuto un problema a elaborare la richiesta.")
                return None

            async for chunk in resp.aiter_text():
                for nome, data in parser.aggiungi(chunk):
                    if nome == "delta":
                        # la risposta sta arrivando: da qui nessun riempitivo,
                        # anche se l'audio vero deve ancora iniziare a suonare
                        riempitivi.su_audio_risposta()
                        tempi.setdefault("risposta", time.monotonic() - t0)
                        print(data["testo"], end="", flush=True)
                        for frase in spezza.aggiungi(data["testo"]):
                            await pronuncia(frase)
                    elif nome == "ponte":
                        # presa in carico generata da Haiku (server): arriva
                        # solo se il modello non ha ancora aperto bocca
                        tempi["ponte"] = time.monotonic() - t0
                        print(f"(ponte: {data['testo']})", flush=True)
                        await pronuncia(data["testo"])
                    elif nome == "tool_in_corso":
                        ultimo_tool = data["tool"]
                        print(f"\n[{data['tool']}…]", flush=True)
                        if config.RIEMPITIVI_ATTIVI:
                            frase = riempitivi.su_tool(data["tool"])
                            if frase:
                                print(f"(riempitivo: {frase})", flush=True)
                                await pronuncia(frase)
                    elif nome == "fine":
                        azione = data.get("azione_in_attesa")
                    elif nome == "errore":
                        errore_stream = data["messaggio"]

        for frase in spezza.chiudi():
            await pronuncia(frase)
        if errore_stream:
            print(f"\n{errore_stream}")
            await pronuncia(errore_stream)
        if azione:
            print(f"\n\n[Conferma richiesta] {_descrivi_azione(azione)}")
            await pronuncia(
                f"Serve la tua conferma: {_descrivi_azione(azione)}. "
                "Premi Invio e rispondi con un sì o con un no."
            )
        pezzi_tempo = [f"{nome} {secondi:.1f}s" for nome, secondi in tempi.items()]
        pezzi_tempo.append(f"totale {time.monotonic() - t0:.1f}s")
        print(f"\n(tempi: {' · '.join(pezzi_tempo)})")
        return azione
    finally:
        if watchdog is not None:
            watchdog.cancel()
        await sessione_tts.chiudi()


async def _turno_conferma(
    client: httpx.AsyncClient, azione: dict, transcript: str, sessione_tts: tts.SessioneTTS
) -> bool:
    """True se l'azione è stata risolta (confermata o annullata)."""

    async def esito_vocale(testo: str) -> None:
        print(testo)
        await sessione_tts.invia(per_tts(testo))

    conferma = interpreta_transcript(transcript)
    if conferma is None:
        await esito_vocale("Non ho capito: rispondi con un sì o con un no chiaro.")
        return False
    resp = await client.post(f"/azioni/{azione['id']}/conferma", json={"conferma": conferma})
    if resp.status_code != 200:
        print(f"Errore nella conferma ({resp.status_code}): {resp.text}")
        await esito_vocale("Non sono riuscito a registrare la conferma.")
        return False
    stato = resp.json()["stato"]
    await esito_vocale("Fatto." if stato == "confermata_inviata" else "Azione annullata.")
    return True


async def _chiudi_silenziosamente(task_tts: asyncio.Task) -> None:
    """Chiude una sessione TTS preparata ma rimasta inutilizzata."""
    try:
        sessione = await task_tts
        await sessione.chiudi()
    except Exception:
        pass


async def _loop(cookies: dict) -> None:
    async with httpx.AsyncClient(
        base_url=config.BASE_URL, cookies=cookies, timeout=180.0
    ) as client:
        print("Eidos voce — premi Invio e parla (Ctrl+C per uscire)\n")
        azione_in_attesa: dict | None = None
        while True:
            task_tts: asyncio.Task | None = None
            try:
                await asyncio.to_thread(input, "[Invio per parlare] ")
                # token una volta sola per turno; la sessione TTS si apre
                # MENTRE l'utente parla, così alla fine del parlato è pronta
                tokens = await _token_voce(client)
                task_tts = asyncio.create_task(
                    tts.apri_sessione(tokens["elevenlabs"]["token"])
                )
                transcript = await _ascolta(tokens["deepgram"]["token"])
                if not transcript:
                    print("Non ho sentito nulla, riprova.")
                    await _chiudi_silenziosamente(task_tts)
                    continue
                print(f"Tu: {transcript}\n")
                sessione_tts = await task_tts

                if azione_in_attesa is not None:
                    try:
                        if await _turno_conferma(
                            client, azione_in_attesa, transcript, sessione_tts
                        ):
                            azione_in_attesa = None
                    finally:
                        await sessione_tts.chiudi()
                    continue

                azione_in_attesa = await _turno_risposta(client, transcript, sessione_tts)
            except (stt.ErroreSTT, tts.ErroreTTS, ErroreAudio, RuntimeError) as exc:
                print(f"\n{exc}")
                if task_tts is not None and not task_tts.done():
                    await _chiudi_silenziosamente(task_tts)


def main() -> None:
    try:
        cookies = _login_sincrono()
        asyncio.run(_loop(cookies))
    except KeyboardInterrupt:
        print("\nA presto.")
