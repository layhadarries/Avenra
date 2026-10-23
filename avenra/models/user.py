"""User domain entity."""
from typing import Optional, Any
from werkzeug.security import check_password_hash


class User:
    """Represents a Avenra user (survivor, responder, shelter staff, or admin)."""

    def __init__(
        self,
        id: int,
        name: str,
        role: str,
        email: str,
        password_hash: Optional[str] = None,
        org: Optional[str] = None,
        case_code: Optional[str] = None,
        shelter_id: Optional[int] = None,
        is_active: int = 1,
        auth_version: int = 1,
    ):
        self.id = id
        self.name = name
        self.role = role
        self.email = email
        self.password_hash = password_hash
        self.org = org
        self.case_code = case_code
        self.shelter_id = shelter_id
        self.is_active = bool(is_active)
        self.auth_version = auth_version

    @classmethod
    def from_row(cls, row) -> Optional["User"]:
        if row is None:
            return None
        return cls(
            id=row["id"],
            name=row["name"],
            role=row["role"],
            email=row["email"],
            password_hash=row["password_hash"],
            org=row["org"],
            case_code=row["case_code"],
            shelter_id=row["shelter_id"],
            is_active=row["is_active"] if "is_active" in row.keys() else 1,
            auth_version=row["auth_version"] if "auth_version" in row.keys() else 1,
        )

    def verify_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def can_sign_in(self) -> bool:
        return self.is_active and bool(self.password_hash)

    def is_survivor(self) -> bool:
        return self.role == "survivor"

    def is_responder(self) -> bool:
        return self.role == "responder"

    def is_shelter_staff(self) -> bool:
        return self.role == "shelter"

    def is_admin(self) -> bool:
        return self.role == "admin"

    def __getitem__(self, item: str) -> Any:
        """Allow dict-like indexing for backward compatibility with Jinja and legacy code."""
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "email": self.email,
            "org": self.org,
            "case_code": self.case_code,
            "shelter_id": self.shelter_id,
            "is_active": self.is_active,
            "auth_version": self.auth_version,
        }
