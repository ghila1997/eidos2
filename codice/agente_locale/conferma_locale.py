"""Conferma sincrona al terminale per Agente Locale (vedi DECISIONS.md,
"Safety Supervisor: punto unico di autorizzazione per ogni tool call"):
sessione locale, singolo utente, un solo terminale - non serve la coda
`azioni_pending` usata da Gmail (pensata per conferme asincrone/
multi-dispositivo). La persona che deve confermare e' li', allo stesso
terminale, quindi il gate si risolve subito, fuori dal controllo del
modello (la decisione la prende questo codice, non il modello).
"""
from __future__ import annotations


def conferma_terminale(messaggio: str) -> bool:
    while True:
        risposta = input(f"\n[Conferma richiesta] {messaggio} [y/n]: ").strip().lower()
        if risposta in ("y", "n"):
            return risposta == "y"
        print("Rispondi 'y' o 'n'.")
