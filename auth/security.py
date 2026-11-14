from datetime import datetime, timedelta, timezone
import os
import secrets
from collections.abc import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from auth.principal import Principal
from db import get_db
from enums import UserRole
from models import User


JWT_ALGORITHM = "HS256"
JWT_ISSUER = "veylix"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
password_hasher = PasswordHash.recommended()
dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if secret is None or len(secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes")
    return secret


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def verify_login_password(password: str, user: User | None) -> bool:
    password_hash = user.password_hash if user is not None else dummy_password_hash
    is_valid = verify_password(password, password_hash)
    return user is not None and user.is_active and is_valid


def create_access_token(user: User) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires_at = now + ACCESS_TOKEN_LIFETIME
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iss": JWT_ISSUER,
            "iat": now,
            "exp": expires_at,
        },
        get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )
    return token, int(ACCESS_TOKEN_LIFETIME.total_seconds())


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        claims = jwt.decode(
            credentials.credentials,
            get_jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        user_id = UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return Principal(user_id=user.id, username=user.username, role=user.role)


def require_roles(*roles: UserRole) -> Callable[..., Principal]:
    allowed_roles = frozenset(roles)

    def authorize(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return principal

    return authorize
