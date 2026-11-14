from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth.principal import Principal
from auth.security import create_access_token, get_current_principal, verify_login_password
from db import get_db
from models import User
from schemas.auth import LoginRequest, TokenResponse, UserRead


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/token", response_model=TokenResponse)
def issue_token(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(
        select(User).where(func.lower(User.username) == payload.username)
    )
    authenticated = verify_login_password(
        payload.password.get_secret_value(),
        user,
    )
    if user is None or not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(user)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserRead)
def get_current_user(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
