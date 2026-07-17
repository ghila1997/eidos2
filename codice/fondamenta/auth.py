import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import supabase_client

router = APIRouter()

ACCESS_COOKIE = "sb_access_token"
REFRESH_COOKIE = "sb_refresh_token"

# Cache delle sessioni verificate, per access token. Perché: la verifica
# costava ~0,5-0,8s di roundtrip Supabase a OGNI richiesta — inaccettabile in
# una conversazione vocale (trovato a STOP 2 Tappa 6). Costo del TTL: una
# revoca di sessione diventa effettiva entro 60s invece che subito —
# accettabile in fase single-user, da rivalutare alla Tappa 8 (multi-tenant).
_CACHE_SESSIONI: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDI = 60.0
_CACHE_MAX_VOCI = 1000


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    try:
        tokens = await supabase_client.sign_in_with_password(body.email, body.password)
    except supabase_client.SupabaseAuthError:
        raise HTTPException(status_code=401, detail="credenziali non valide")

    response.set_cookie(
        ACCESS_COOKIE,
        tokens["access_token"],
        httponly=True,
        secure=True,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens["refresh_token"],
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"status": "ok"}


async def get_sessione_corrente(request: Request) -> dict:
    """Identità + tenant dell'utente loggato, dal cookie di sessione.
    Riusata anche da altri moduli (es. orchestratore/router.py) per non
    duplicare la verifica auth - stessa logica di /me, un punto solo."""
    access_token = request.cookies.get(ACCESS_COOKIE)
    if not access_token:
        raise HTTPException(status_code=401, detail="sessione mancante")

    in_cache = _CACHE_SESSIONI.get(access_token)
    if in_cache is not None and time.monotonic() - in_cache[0] < _CACHE_TTL_SECONDI:
        return dict(in_cache[1])

    try:
        user = await supabase_client.get_user(access_token)
    except supabase_client.SupabaseAuthError:
        raise HTTPException(status_code=401, detail="sessione non valida")

    membership = await supabase_client.get_tenant_membership(user["id"])
    if membership is None:
        raise HTTPException(status_code=404, detail="nessun tenant associato a questo utente")

    sessione = {
        "user_id": user["id"],
        "email": user.get("email"),
        "tenant_id": membership["tenant_id"],
        "role": membership["role"],
    }
    if len(_CACHE_SESSIONI) >= _CACHE_MAX_VOCI:
        _CACHE_SESSIONI.clear()  # tetto duro, mai crescita illimitata
    _CACHE_SESSIONI[access_token] = (time.monotonic(), sessione)
    return dict(sessione)


@router.get("/me")
async def me(request: Request):
    return await get_sessione_corrente(request)
