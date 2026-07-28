"""Risoluzione entità condivisa (usata da orchestratore/tools.py e
memoria/ingest_documento.py - prima erano due copie private identiche,
consolidate qui perché azioni.py deve poterla chiamare senza creare un
import circolare con tools.py, che importa già azioni).

Oggi solo slug del nome: pochi nodi puliti > tanti sporchi (vedi
memory-business.md §7) - nessun collegamento cross-source (es. indirizzo
mail -> nome persona). Miglioramento pianificato quando serve davvero
(vedi ROADMAP.md / notes, cuneo "impegni impliciti")."""
from __future__ import annotations

import re

# Forme societarie italiane/comuni più frequenti nelle firme mail reali
# (trovate testando su Nastro Tecno srl, sessione 2026-07-23) - rimosse
# prima dello slug così "Isagro" e "ISAGRO S.p.A." risolvono alla stessa
# entità. Elenco corto e deliberatamente incompleto: si allarga solo su
# caso reale mancante, non a priori (vedi CLAUDE.md, "pochi nodi puliti").
_SUFFISSI_SOCIETARI = [
    "s.p.a.", "spa", "s.r.l.", "srl", "s.n.c.", "snc", "s.a.s.", "sas",
    "ltd", "llc", "inc", "gmbh",
]
_SUFFISSO_RE = re.compile(
    r"[\s,]*(" + "|".join(re.escape(s) for s in _SUFFISSI_SOCIETARI) + r")\.?\s*$",
    re.IGNORECASE,
)


def slug_entity(nome: str) -> str:
    pulito = _SUFFISSO_RE.sub("", nome.strip())
    return "_".join(pulito.strip().lower().split())
