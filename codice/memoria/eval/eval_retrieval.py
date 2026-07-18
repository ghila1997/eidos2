"""Eval del retrieval di Memoria (`search_memoria`) con verità nota -
vedi CLAUDE.md "Verifica del comportamento agentico (eval)" e docs/eval.md.

Misura se la lettura unificata (match esatto sui fatti + ricerca semantica,
DECISIONS.md 2026-07-15 "Tappa 4: Memoria") recupera davvero l'informazione
giusta su query realistiche contro i DATI REALI del tenant - non un giudizio
a occhio, non mock. Complementare a eval_estrazione (che valuta la scrittura):
qui si valuta il recupero. NON copre la scelta dei tool da parte dell'agente
conversazionale completo (rimandato, vedi docs/eval.md).

NON gira in CI (chiama Voyage e Supabase veri; nessuna chiamata Anthropic,
costo trascurabile). Richiede EIDOS_TENANT_ID nel .env di codice/ e i dati
importati nelle Tappe 2-5 (mail, eventi conclusi, fatti, documenti):

    cd codice && .venv\\Scripts\\python.exe -m memoria.eval.eval_retrieval

Un FAIL non è (necessariamente) un bug: è la misura di un buco reale di
recall da registrare in docs/eval.md - il criterio di ottimizzazione che
senza queste metriche resterebbe un'opinione. Exit code 0 solo se tutti
gli scenari passano.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Le chiavi (Supabase, EIDOS_TENANT_ID) vivono nel .env di codice/;
# VOYAGE_API_KEY nel .env di root - si caricano entrambi (stesso pattern
# di eval_estrazione).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

import os  # noqa: E402

from orchestratore.tools import _search_memoria  # noqa: E402


def _righe_fonte(risultato: str) -> list[str]:
    return [r for r in risultato.splitlines() if r.startswith("- (fonte:")]


def _similarita_massima(risultato: str) -> float:
    valori = [float(m) for m in re.findall(r"similarità (\d\.\d+)", risultato)]
    return max(valori, default=0.0)


# Ogni scenario: (nome, query, tipo, criterio(risultato) -> bool, verità nota).
# Le verità note vengono dai dati reali del tenant founder (fatti salvati
# nelle Tappe 4-5, eventi calendario storici importati, documenti reali) -
# se quei dati vengono dimenticati/cancellati, lo scenario va aggiornato.

def _fatto_o_chunk(entity_key: str):
    def criterio(r: str) -> bool:
        return entity_key in r
    return criterio


SCENARI = [
    (
        "nome singolo -> fatto garantito dal match esatto",
        "rossi", None,
        lambda r: "(fatto salvato su mario_rossi)" in r,
        "fatto mario_rossi (Tappa 4): il cognome da solo deve attivare la garanzia ilike",
    ),
    (
        "nome intero con spazio -> il fatto compare comunque",
        "Mario Rossi", None,
        _fatto_o_chunk("mario_rossi"),
        "entity_key slugificata (mario_rossi): 'Mario Rossi' con lo spazio NON matcha l'ilike - misura se la semantica lo recupera lo stesso",
    ),
    (
        "trappola Tappa 4: fatto sepolto da chunk più simili",
        "che impegni ha preso Mario Rossi?", None,
        _fatto_o_chunk("mario_rossi"),
        "il fatto (contratto entro venerdì 17/07) deve emergere anche in una domanda lunga",
    ),
    (
        "dato esatto di un fornitore (IBAN)",
        "IBAN di Nastro Tecno", None,
        lambda r: "nastro_tecno" in r.lower() or "nastro tecno" in r.lower(),
        "fatto nastro_tecno_srl con IBAN estratto dal PDF locale (Tappa 5)",
    ),
    (
        "documento importato: fattura fornitore",
        "fattura di Anthropic di luglio", None,
        lambda r: "anthropic" in r.lower(),
        "gmail_attachment (invoice Anthropic Ireland) e/o fatto anthropic_ireland,_limited",
    ),
    (
        "evento calendario concluso",
        "quando ho fatto la revisione della macchina?", None,
        lambda r: "revisione" in r.lower(),
        "evento storico 'Revisione macchina' (2018-04-03) importato in Tappa 4",
    ),
    (
        "filtro per tipo: solo eventi calendario",
        "revisione macchina", "calendar_event",
        lambda r: len(_righe_fonte(r)) > 0
        and all("calendar_event" in riga for riga in _righe_fonte(r)),
        "con tipo=calendar_event ogni chunk restituito deve essere un evento",
    ),
    (
        "nome proprio dentro uno sheet Drive (recupero lessicale)",
        "email di Massimo Iasevoli", None,
        lambda r: "iasevoli" in r.lower(),
        "contatto reale nello sheet Drive importato (Tappa 5) - il caso 'nomi propri' che gli embedding rischiano di mancare",
    ),
    (
        "curriculum su Drive",
        "il curriculum di Riccardo", None,
        lambda r: any("drive_file" in riga for riga in _righe_fonte(r)),
        "CV reale importato da Drive (Tappa 5)",
    ),
    (
        "assenza: nessun fatto inventato",
        "password del wifi di casa", None,
        lambda r: "(fatto salvato" not in r,
        "nessun fatto esiste sull'argomento: la sezione fatti deve restare vuota (i chunk semantici tornano comunque, senza soglia - la similarità massima è nel dettaglio)",
    ),
]


async def main() -> int:
    tenant_id = os.environ.get("EIDOS_TENANT_ID")
    if not tenant_id:
        print("EIDOS_TENANT_ID non impostato nel .env di codice/ - impossibile interrogare la Memoria reale.")
        return 1

    falliti = 0
    for nome, query, tipo, criterio, verita in SCENARI:
        risultato = await _search_memoria(tenant_id, query, tipo)
        ok = criterio(risultato)
        sim = _similarita_massima(risultato)
        n_fonti = len(_righe_fonte(risultato))
        n_fatti = risultato.count("(fatto salvato")
        print(
            f"{'PASS' if ok else 'FAIL'}  {nome}\n"
            f"      query={query!r} tipo={tipo!r} -> fatti={n_fatti}, chunk={n_fonti}, sim_max={sim:.2f}\n"
            f"      verità nota: {verita}"
        )
        if not ok:
            prime = "\n".join(risultato.splitlines()[:4])
            print(f"      risultato (prime righe):\n{prime}")
            falliti += 1

    print(f"\n{len(SCENARI) - falliti}/{len(SCENARI)} scenari passati")
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
