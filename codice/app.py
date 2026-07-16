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

from fondamenta.auth import router as auth_router  # noqa: E402
from orchestratore.router import router as orchestratore_router  # noqa: E402

app = FastAPI(title="Eidos 2.0")
app.include_router(auth_router)
app.include_router(orchestratore_router)


@app.get("/health")
async def health():
    return {"status": "ok", "message": "hello world"}
