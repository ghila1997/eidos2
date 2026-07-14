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
    _salva_cookie(client.cookies)
    print("Login riuscito.\n")


def _assicura_sessione(client: httpx.Client) -> None:
    resp = client.get("/me")
    if resp.status_code == 200:
        return
    _login(client)


def _mostra_conferma(azione: dict) -> None:
    payload = azione["payload"]
    print(
        f"\n[Conferma richiesta] invio a {payload['destinatario']}, "
        f"oggetto '{payload['oggetto']}':\n{payload['corpo']}\n"
    )


def _chiedi_conferma(client: httpx.Client, azione_id: str) -> None:
    while True:
        risposta = input("Confermi l'invio? [y/n]: ").strip().lower()
        if risposta in ("y", "n"):
            break
        print("Rispondi 'y' o 'n'.")
    resp = client.post(f"/azioni/{azione_id}/conferma", json={"conferma": risposta == "y"})
    if resp.status_code != 200:
        print(f"Errore nella conferma ({resp.status_code}): {resp.text}")
        return
    stato = resp.json()["stato"]
    if stato == "confermata_inviata":
        print("Email inviata.\n")
    elif stato == "rifiutata":
        print("Invio annullato.\n")
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
