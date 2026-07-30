from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# Le chiavi API/Supabase vivono nel .env di root (SUPABASE_ANON_KEY,
# ANTHROPIC_API_KEY, VOYAGE_API_KEY, credenziali founder), non in
# codice/.env (solo Supabase + EIDOS_TENANT_ID, per l'Agente Locale) -
# load_dotenv() senza percorso dipende dalla cwd da cui si lancia uvicorn
# e trova solo UNO dei due file, mai entrambi insieme. Espliciti entrambi
# così il server parte identico indipendentemente da dove viene lanciato.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

# uvicorn configura solo i PROPRI logger (uvicorn.error/access): quelli dei
# nostri moduli propagano a un root senza handler, quindi ogni logger.info del
# progetto finiva nel nulla e restavano visibili solo warning ed errori (via
# lastResort di logging). Trovato cercando perche' una riga di diagnostica non
# compariva pur essendo eseguita - il canale era muto, non il codice.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(levelname)s:     %(name)s - %(message)s",
)

from fondamenta.auth import router as auth_router  # noqa: E402
from interfaccia_utente import router as interfaccia_utente  # noqa: E402
from orchestratore import agente, ponte  # noqa: E402
from orchestratore.router import router as orchestratore_router  # noqa: E402


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Prescaldi in background: il motore agente (il primo turno dopo un
    # riavvio non paga i ~10s di connessione) e la connessione Anthropic del
    # ponte vocale (handshake ~1s sulla prima chiamata). In background per
    # non bloccare l'avvio (healthcheck del deploy).
    prescaldi = [
        asyncio.create_task(agente.prescalda(os.environ.get("EIDOS_TENANT_ID"))),
        asyncio.create_task(ponte.prescalda()),
    ]
    yield
    for task in prescaldi:
        task.cancel()


app = FastAPI(title="Eidos 2.0", lifespan=_lifespan)
app.include_router(auth_router)
app.include_router(orchestratore_router)


@app.get("/health")
async def health():
    return {"status": "ok", "message": "hello world"}


# Interfaccia web per ultima: monta gli statici su /static e la pagina su /
# (vedi interfaccia_utente/router.py, configura()).
interfaccia_utente.configura(app)
