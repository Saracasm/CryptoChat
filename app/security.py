"""Week 6: JWT auth, user isolation, and observability hooks."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from uuid import UUID
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/profiles/login")


def create_access_token(
    *, user_id: UUID, username: str, secret: str, expires_in_minutes: int = 60
) -> str:
    """Issue a signed JWT."""
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=expires_in_minutes)
    payload = {"sub": str(user_id), "username": username, "exp": expires_at}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> UUID:
    """Decode and validate a JWT, returning the user_id it was issued for."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        ) from error
    return UUID(payload["sub"])


def require_current_user(secret: str):
    """Create a dependency that resolves the current user_id from a bearer token."""
    def dependency(token: str = Depends(oauth2_scheme)) -> UUID:
        return decode_access_token(token, secret)
    return dependency