"""Session tokens issued after a successful local login (see
app/services/local_auth.py).

A JWT here is just a signed, stateless session — there is no server-side
session store to invalidate on logout (the frontend simply discards the
token; it naturally expires after ``jwt_expires_minutes``). That's a
reasonable tradeoff for an internal tool with no "log out everywhere"
requirement in the design, not an oversight.
"""
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings


class InvalidTokenError(Exception):
    pass


def create_access_token(username: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Returns the username (the "sub" claim). Raises InvalidTokenError for
    anything wrong with the token — expired, malformed, wrong signature."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    username = payload.get("sub")
    if not username:
        raise InvalidTokenError("Le jeton ne contient pas d'identifiant utilisateur.")
    return username
