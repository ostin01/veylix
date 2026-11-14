from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from auth.bootstrap import bootstrap_admin
from auth.security import get_jwt_secret, verify_password
from db import Base
from enums import UserRole
from models import User


def test_jwt_secret_can_be_loaded_from_a_mounted_secret_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "file-backed-test-jwt-secret-with-at-least-32-bytes"
    secret_file = tmp_path / "jwt-secret"
    secret_file.write_text(secret, encoding="utf-8")
    monkeypatch.setenv("JWT_SECRET_KEY_FILE", str(secret_file))
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    assert get_jwt_secret() == secret


def test_admin_bootstrap_is_idempotent_and_hashes_password() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        assert bootstrap_admin(db, "Initial-Admin", "a-very-long-bootstrap-password")
        assert not bootstrap_admin(db, "Ignored-Second-Admin", "another-long-password")
        admin = db.scalar(select(User).where(User.role == UserRole.ADMIN))
        assert admin is not None
        assert admin.username == "initial-admin"
        assert admin.password_hash != "a-very-long-bootstrap-password"
        assert verify_password("a-very-long-bootstrap-password", admin.password_hash)

    engine.dispose()
