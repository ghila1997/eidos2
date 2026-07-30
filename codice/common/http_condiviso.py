"""Client HTTP condiviso per le API Google (Gmail, Drive, OAuth).

Stessa ragione già documentata in `common/supabase_rest.py`: un
`httpx.AsyncClient` nuovo a ogni chiamata paga l'handshake TLS ogni volta.
Su Supabase era stato risolto, sui client Google no - e lì pesa di più,
perché una singola richiesta dell'utente ne fa molte di fila.

Misurato il 2026-07-30 su Gmail (`users.getProfile`, 8 chiamate):

    client nuovo ogni volta   1,10 s l'una
    client condiviso          0,18 s l'una

Su una conferma di 21 cestinamenti: ~23 s contro ~3,7 s.

`sessione()` esiste per sostituire `async with httpx.AsyncClient() as c:`
riga per riga senza reindentare i chiamanti **e senza chiudere** il client
condiviso all'uscita del blocco (uscire da un `async with httpx.AsyncClient()`
lo chiude: se lo facessimo qui, il client successivo ripagherebbe l'handshake
e il guadagno sparirebbe).

Il timeout resta quello di default di httpx, come prima: qui si cambia solo
quante connessioni si aprono, non quanto si aspetta una risposta.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

_client_condiviso: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client_condiviso
    if _client_condiviso is None:
        _client_condiviso = httpx.AsyncClient()
    return _client_condiviso


@asynccontextmanager
async def sessione() -> AsyncIterator[httpx.AsyncClient]:
    yield client()
