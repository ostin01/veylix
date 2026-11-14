from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.principal import Principal
from auth.security import hash_password, require_roles
from db import get_db
from enums import UserRole
from models import User
from schemas.auth import UserCreate, UserListResponse, UserRead


router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=UserListResponse)
def list_users(
    principal: Principal = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> UserListResponse:
    users = db.scalars(select(User).order_by(User.username.asc(), User.id.asc())).all()
    return UserListResponse(items=users)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    principal: Principal = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    if db.scalar(
        select(User.id).where(func.lower(User.username) == payload.username)
    ) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already registered",
        )

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password.get_secret_value()),
        role=payload.role,
        created_by_id=principal.user_id,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already registered",
        ) from error
    db.refresh(user)
    return user
