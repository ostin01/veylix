from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.principal import Principal
from auth.security import hash_password, require_roles, revoke_user_refresh_tokens
from db import get_db
from enums import UserRole
from models import User
from schemas.auth import UserCreate, UserListResponse, UserRead, UserStatusUpdate


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


@router.patch("/{user_id}/status", response_model=UserRead)
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    principal: Principal = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if payload.is_active == user.is_active:
        return user
    if not payload.is_active and user.id == principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrators cannot deactivate their own account",
        )
    if not payload.is_active and user.role == UserRole.ADMIN:
        active_admins = db.scalars(
            select(User.id)
            .where(
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
            .order_by(User.id)
            .with_for_update()
        ).all()
        if len(active_admins) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last active administrator cannot be deactivated",
            )

    user.is_active = payload.is_active
    user.token_version += 1
    if not payload.is_active:
        revoke_user_refresh_tokens(db, user.id)
    db.commit()
    db.refresh(user)
    return user
