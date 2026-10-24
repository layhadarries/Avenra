"""Alert domain entity."""
from typing import Optional, Any


class Alert:
    """Represents an emergency alert triggered by a survivor."""

    def __init__(
        self,
        id: int,
        user_id: int,
        case_code: str,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        status: str = "new",
        acknowledged_by: Optional[str] = None,
        acknowledged_at: Optional[str] = None,
        client_id: Optional[str] = None,
        client_ts: Optional[str] = None,
        created_at: Optional[str] = None,
        location_accuracy: Optional[float] = None,
        location_recorded_at: Optional[str] = None,
    ):
        self.id = id
        self.user_id = user_id
        self.case_code = case_code
        self.lat = lat
        self.lng = lng
        self.status = status
        self.acknowledged_by = acknowledged_by
        self.acknowledged_at = acknowledged_at
        self.client_id = client_id
        self.client_ts = client_ts
        self.created_at = created_at
        self.location_accuracy = location_accuracy
        self.location_recorded_at = location_recorded_at

    @classmethod
    def from_row(cls, row) -> Optional["Alert"]:
        if row is None:
            return None
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            case_code=row["case_code"],
            lat=row["lat"],
            lng=row["lng"],
            status=row["status"],
            acknowledged_by=row["acknowledged_by"],
            acknowledged_at=row["acknowledged_at"],
            client_id=row["client_id"],
            client_ts=row["client_ts"],
            created_at=row["created_at"],
            location_accuracy=row["location_accuracy"],
            location_recorded_at=row["location_recorded_at"],
        )

    def is_acknowledged(self) -> bool:
        return self.status in ("acknowledged", "in_progress", "resolved")

    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lng is not None

    def serialize(self, location_allowed: bool = True) -> dict:
        """Return location information only when disclosure is permitted."""
        has_coords = self.has_coordinates()
        location_visible = has_coords and location_allowed

        return {
            "id": self.id,
            "case_code": self.case_code,
            "status": self.status,
            "lat": self.lat if location_visible else None,
            "lng": self.lng if location_visible else None,
            "location_accuracy": (
                self.location_accuracy if location_visible else None
            ),
            "location_recorded_at": (
                self.location_recorded_at if location_visible else None
            ),
            "location_redacted": bool(
                has_coords and not location_allowed
            ),
            "client_ts": self.client_ts,
            "created_at": self.created_at,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
        }

    def created_body(self) -> dict:
        """Small JSON payload returned to the survivor phone."""
        return {
            "id": self.id,
            "client_id": self.client_id,
            "location_shared": self.lat is not None,
            "case_code": self.case_code,
            "status": self.status,
            "created_at": self.created_at,
        }

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
