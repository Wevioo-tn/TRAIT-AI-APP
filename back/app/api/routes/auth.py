from fastapi import APIRouter, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.schemas.auth import LoginRequest, TokenResponse
from app.services.jwt_auth import create_access_token
from app.services.ldap_auth import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    # authenticate() does a blocking LDAP network round-trip — run it off
    # the event loop rather than stalling every other request while it
    # waits on the directory (same pattern as the blocking disk I/O in
    # services/storage.py).
    ok = await run_in_threadpool(authenticate, payload.username, payload.password)
    if not ok:
        # Same message whether the username is unknown or the password is
        # wrong — see ldap_auth.py for why that's deliberate.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiant ou mot de passe incorrect.")

    token = create_access_token(payload.username)
    return TokenResponse(access_token=token, username=payload.username)
