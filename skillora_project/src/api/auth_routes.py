"""
Authentication routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from src.api.schemas import TokenOut, UserOut
from src.api.security import authenticate_admin, create_access_token, require_auth

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/token", response_model=TokenOut, summary="Issue JWT token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_admin(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": user["username"]})
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut, summary="Current user")
def read_users_me(current_user=Depends(require_auth)):
    return UserOut(username=current_user["username"])
