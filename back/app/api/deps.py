from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.jwt_auth import InvalidTokenError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: the authenticated username, or a 401. Applied at
    the router level to every /api/traites/* route (see routes/traites.py)
    — everything under it requires a session, matching the design's own
    "Accès réservé aux collaborateurs habilités" promise."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise.")
    try:
        return decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalide ou expirée.") from exc
