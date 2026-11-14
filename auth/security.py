from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from auth.principal import Principal
from db import get_db
from enums import UserRole
from models import RefreshToken, User, utc_now


JWT_ALGORITHM = "HS256"
JWT_ISSUER = "veylix"
ACCESS_TOKEN_LIFETIME = timedelta(minutes=15)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
password_hasher = PasswordHash.recommended()
dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_secret() -> str:
    secret_file = os.getenv("JWT_SECRET_KEY_FILE")
    if secret_file:
        path = Path(secret_file)
        if not path.is_file():
            raise FileNotFoundError(f"JWT secret file does not exist: {path}")
        secret = path.read_text(encoding="utf-8").strip()
    else:
        secret = os.getenv("JWT_SECRET_KEY")
    if secret is None or len(secret.encode("utf-8")) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY or JWT_SECRET_KEY_FILE must provide at least 32 bytes"
        )
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
            "ver": user.token_version,
        },
        get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )
    return token, int(ACCESS_TOKEN_LIFETIME.total_seconds())


def create_refresh_token(
    db: Session,
    user: User,
    family_id: UUID | None = None,
) -> str:
    token = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid4(),
            token_hash=sha256(token.encode("ascii")).hexdigest(),
            expires_at=utc_now() + REFRESH_TOKEN_LIFETIME,
        )
    )
    return token


def rotate_refresh_token(db: Session, token: str) -> tuple[User, str, str]:
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    refresh_record = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
    )
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    if refresh_record is None:
        raise unauthorized

    now = utc_now()
    if refresh_record.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == refresh_record.family_id)
            .values(revoked_at=now)
        )
        db.commit()
        raise unauthorized

    expires_at = refresh_record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    user = db.get(User, refresh_record.user_id)
    if (
        user is None
        or not user.is_active
        or expires_at <= now
    ):
        refresh_record.revoked_at = now
        db.commit()
        raise unauthorized

    next_token = create_refresh_token(db, user, refresh_record.family_id)
    refresh_record.revoked_at = now
    access_token, _ = create_access_token(user)
    db.commit()
    return user, access_token, next_token


def revoke_refresh_token(db: Session, token: str) -> None:
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    refresh_record = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if refresh_record is not None and refresh_record.revoked_at is None:
        refresh_record.revoked_at = utc_now()
        db.commit()


def revoke_user_refresh_tokens(db: Session, user_id: UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=utc_now())
    )


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
            options={"require": ["exp", "iat", "iss", "sub", "ver"]},
        )
        user_id = UUID(claims["sub"])
        token_version = claims["ver"]
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    user = db.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or type(token_version) is not int
        or user.token_version != token_version
    ):
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
