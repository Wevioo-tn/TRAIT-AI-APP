from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.jwt_auth import create_access_token
from app.services.local_auth import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    ok = await authenticate(session, payload.username, payload.password)
    if not ok:
        # Same message whether the username is unknown or the password is
        # wrong — see local_auth.py for why that's deliberate.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiant ou mot de passe incorrect.")

    token = create_access_token(payload.username)
    return TokenResponse(access_token=token, username=payload.username)
