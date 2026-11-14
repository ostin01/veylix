from dataclasses import dataclass
from uuid import UUID

from enums import UserRole


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    username: str
    role: UserRole
