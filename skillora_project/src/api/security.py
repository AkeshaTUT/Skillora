"""
JWT auth helpers for protected API endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    API_ADMIN_PASSWORD,
    API_ADMIN_PASSWORD_HASH,
    API_ADMIN_USERNAME,
    SECRET_KEY,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


class AuthUser(dict):
    """Simple authenticated principal payload."""


def verify_password(plain_password: str) -> bool:
    if API_ADMIN_PASSWORD_HASH:
        return pwd_context.verify(plain_password, API_ADMIN_PASSWORD_HASH)
    return plain_password == API_ADMIN_PASSWORD


def authenticate_admin(username: str, password: str) -> AuthUser | None:
    if username != API_ADMIN_USERNAME:
        return None
    if not verify_password(password):
        return None
    return AuthUser(username=username)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if username != API_ADMIN_USERNAME:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    return AuthUser(username=username)


def require_auth(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user
