"""Eval del comportamento del ponte vocale (Tappa 6) — NON gira in CI.

Verifica su casi reali con verità nota la decisione di Haiku: astenersi
(NO_PONTE) dove non c'è lavoro, generare la presa in carico dove c'è —
anche quando la richiesta inizia con un saluto (caso trovato a STOP 2,
2026-07-19: 'Ciao, che impegno domani?' veniva scambiato per chiacchiera).

Lancio: dalla cartella codice/, `.venv/Scripts/python -m orchestratore.eval.eval_ponte`
Registro esiti: docs/eval.md
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from orchestratore import ponte  # noqa: E402

# (frase, deve_astenersi)
CASI = [
    # lavoro puro -> ponte
    ("che impegni ho la settimana prossima?", False),
    ("manda una mail a Marco", False),
    ("cancella l'evento di lunedì", False),
    # saluto + lavoro -> ponte (il saluto iniziale non conta)
    ("Ciao, che impegno domani?", False),
    ("buongiorno! mi cerchi la fattura di Anthropic?", False),
    # nessun lavoro -> astensione
    ("ciao, chi sei?", True),
    ("come stai?", True),
    ("grazie mille", True),
    ("ok perfetto", True),
]


async def main() -> None:
    errori = 0
    for frase, deve_astenersi in CASI:
        esito = await ponte.genera_ponte(frase)
        ok = (esito is None) == deve_astenersi
        errori += not ok
        print(("PASS" if ok else "FAIL"), repr(frase), "->", repr(esito))
    print(f"\n{len(CASI) - errori}/{len(CASI)} PASS")
    raise SystemExit(1 if errori else 0)


if __name__ == "__main__":
    asyncio.run(main())
