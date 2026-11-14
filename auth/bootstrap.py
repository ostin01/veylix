import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth.security import get_jwt_secret, hash_password
from db import SessionLocal
from enums import UserRole
from models import User
from schemas.auth import UserCreate


def bootstrap_admin(db: Session, username: str, password: str) -> bool:
    credentials = UserCreate(
        username=username,
        password=password,
        role=UserRole.ADMIN,
    )
    if db.scalar(select(User.id).where(User.role == UserRole.ADMIN)) is not None:
        return False

    normalized_username = credentials.username
    existing_user = db.scalar(
        select(User.id).where(func.lower(User.username) == normalized_username)
    )
    if existing_user is not None:
        raise RuntimeError("Bootstrap username already belongs to a non-admin account")

    db.add(
        User(
            username=normalized_username,
            password_hash=hash_password(credentials.password.get_secret_value()),
            role=UserRole.ADMIN,
        )
    )
    db.commit()
    return True


def main() -> None:
    get_jwt_secret()
    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME")
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD must be configured"
        )
    with SessionLocal() as db:
        created = bootstrap_admin(db, username, password)
    if created:
        print("Created the initial administrator account")
    else:
        print("An administrator account already exists; bootstrap was skipped")


if __name__ == "__main__":
    main()
