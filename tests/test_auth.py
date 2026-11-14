from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from auth.bootstrap import bootstrap_admin
from auth.security import verify_password
from db import Base
from enums import UserRole
from models import User


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
