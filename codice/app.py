from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from fondamenta.auth import router as auth_router  # noqa: E402
from orchestratore.router import router as orchestratore_router  # noqa: E402

app = FastAPI(title="Eidos 2.0")
app.include_router(auth_router)
app.include_router(orchestratore_router)


@app.get("/health")
async def health():
    return {"status": "ok", "message": "hello world"}
