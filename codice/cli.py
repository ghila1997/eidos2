"""CLI testuale dell'Orchestratore - client remoto sottile.

Parla via HTTP col backend deployato (stessa auth a cookie di Fondamenta):
nessuna logica dell'agente gira qui, solo input/output. Per questo è
utilizzabile da qualunque dispositivo con questo script e una connessione -
niente stato locale oltre al cookie di sessione (vedi design Tappa 2,
decisione "Orchestratore server-side").

Uso:
    python cli.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

BASE_URL = os.environ.get("EIDOS_API_BASE_URL", "https://eidos2-api-production.up.railway.app")
COOKIE_FILE = Path.home() / ".eidos" / "cookies.json"


def _carica_cookie() -> dict:
    if COOKIE_FILE.exists():
        return json.loads(COOKIE_FILE.read_text())
    return {}


def _salva_cookie(cookies: httpx.Cookies) -> None:
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(dict(cookies)))


def _login(client: httpx.Client) -> None:
    print(f"Login su {BASE_URL}")
    email = input("Email: ").strip()
    password = input("Password: ").strip()
    resp = client.post("/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        print(f"Login fallito ({resp.status_code}): {resp.text}")
        raise SystemExit(1)
    # Trappola reale trovata testando a mano (2026-07-16): `client.cookies`
    # accumula anche un cookie sb_access_token stale precaricato da un
    # cookies.json precedente (dominio "" per come lo salviamo noi) insieme
    # a quello appena impostato dalla risposta (dominio reale, es.
    # eidos2-api-production.up.railway.app) - stesso nome, domini diversi,
    # httpx.Cookies solleva CookieConflict a qualunque accesso ambiguo
    # (dict(), [] o .get() senza domain). `resp.cookies` contiene solo i
    # cookie impostati da QUESTA risposta, nessuna ambiguità possibile.
    _salva_cookie(resp.cookies)
    print("Login riuscito.\n")


def _assicura_sessione(client: httpx.Client) -> None:
    resp = client.get("/me")
    if resp.status_code == 200:
        return
    _login(client)


def _descrivi_azione(azione: dict) -> str:
    """Rende leggibile un'azione pending a partire dalla `descrizione` che il
    server allega (fonte unica per CLI e web, Tappa 7.2): il CLI non ricalcola
    più la descrizione, la formatta soltanto. Fallback minimale se un vecchio
    server non la mandasse."""
    d = azione.get("descrizione")
    if not d:
        return f"azione di tipo '{azione.get('tipo', '?')}'"
    righe = [f"{d.get('titolo', '')}".strip()]
    for r in d.get("dettagli", []):
        righe.append(f"  {r['etichetta']}: {r['valore']}")
    if d.get("corpo"):
        righe.append(f"\n{d['corpo']}")
    return "\n".join(righe).strip()


def _mostra_conferma(azione: dict) -> None:
    print(f"\n[Conferma richiesta]\n{_descrivi_azione(azione)}\n")


_RISPOSTE_AFFERMATIVE = {"y", "si", "sì", "confermo", "vai", "ok", "autorizzo"}
_RISPOSTE_NEGATIVE = {"n", "no", "annulla", "fermati", "stop"}


def _interpreta_risposta(testo: str) -> bool | None:
    """Elenco chiuso di frasi accettate, confronto deterministico (non
    interpretazione del modello) - stesso principio di sicurezza di un
    semplice y/n, solo meno rigido. Le frasi vocali (wake-phrase, gestione
    ambiguità da voce) restano fuori: competenza di Tappa 6 (Voce), non di
    qui - vedi CLAUDE.md, "testo prima, voce dopo". None = non riconosciuta."""
    testo = testo.strip().lower()
    if testo in _RISPOSTE_AFFERMATIVE:
        return True
    if testo in _RISPOSTE_NEGATIVE:
        return False
    return None


def _chiedi_conferma(client: httpx.Client, azione_id: str) -> None:
    while True:
        conferma = _interpreta_risposta(input("Confermi? [sì/no]: "))
        if conferma is not None:
            break
        print("Rispondi con un sì o un no chiaro (es. 'sì', 'confermo', 'no', 'annulla').")
    resp = client.post(f"/azioni/{azione_id}/conferma", json={"conferma": conferma})
    if resp.status_code != 200:
        print(f"Errore nella conferma ({resp.status_code}): {resp.text}")
        return
    stato = resp.json()["stato"]
    if stato == "confermata_inviata":
        print("Fatto.\n")
    elif stato == "rifiutata":
        print("Azione annullata.\n")
    elif stato == "scaduta":
        print("Azione scaduta (troppo tempo trascorso), richiedila di nuovo.\n")
    else:
        print(f"Stato azione: {stato}\n")


def main() -> None:
    with httpx.Client(base_url=BASE_URL, cookies=_carica_cookie(), timeout=60.0) as client:
        _assicura_sessione(client)
        print("Eidos - digita un messaggio (Ctrl+C per uscire)\n")

        azione_in_attesa: dict | None = None
        while True:
            try:
                if azione_in_attesa is not None:
                    _chiedi_conferma(client, azione_in_attesa["id"])
                    azione_in_attesa = None
                    continue

                messaggio = input("Tu: ").strip()
                if not messaggio:
                    continue

                resp = client.post("/chat", json={"messaggio": messaggio})
                if resp.status_code == 409:
                    dettaglio = resp.json()["detail"]
                    azione_in_attesa = {
                        "id": dettaglio["azione_id"],
                        "tipo": dettaglio["tipo"],
                        "payload": dettaglio["payload"],
                    }
                    _mostra_conferma(azione_in_attesa)
                    continue
                if resp.status_code != 200:
                    print(f"Errore ({resp.status_code}): {resp.text}")
                    continue

                body = resp.json()
                print(f"Eidos: {body['risposta']}\n")
                if body.get("azione_in_attesa"):
                    azione_in_attesa = body["azione_in_attesa"]
                    _mostra_conferma(azione_in_attesa)
            except KeyboardInterrupt:
                print("\nA presto.")
                break


if __name__ == "__main__":
    main()
