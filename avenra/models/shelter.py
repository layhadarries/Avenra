"""Shelter domain entity."""
from typing import Optional, Any


class Shelter:
    """Represents a shelter or crisis clinic."""

    def __init__(
        self,
        id: int,
        name: str,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        beds_total: int = 0,
        beds_available: int = 0,
        accepting: int = 1,
        languages: Optional[str] = None,
        hours: Optional[str] = None,
        walk_ins: int = 0,
        address: Optional[str] = None,
        verified: int = 0,
    ):
        self.id = id
        self.name = name
        self.lat = lat
        self.lng = lng
        self.beds_total = beds_total
        self.beds_available = beds_available
        self.accepting = bool(accepting)
        self.languages = languages
        self.hours = hours
        self.walk_ins = bool(walk_ins)
        self.address = address
        self.verified = bool(verified)

    @classmethod
    def from_row(cls, row) -> Optional["Shelter"]:
        if row is None:
            return None
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            id=row["id"],
            name=row["name"],
            lat=row["lat"],
            lng=row["lng"],
            beds_total=row["beds_total"],
            beds_available=row["beds_available"],
            accepting=row["accepting"],
            languages=row["languages"],
            hours=row["hours"],
            walk_ins=row["walk_ins"],
            address=row["address"] if "address" in keys else None,
            verified=row["verified"] if "verified" in keys else 0,
        )

    def has_capacity(self) -> bool:
        return self.accepting and self.beds_available > 0

    def serialize(self) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "lat": self.lat,
            "lng": self.lng,
            "beds_total": self.beds_total,
            "beds_available": self.beds_available,
            "accepting": self.accepting,
            "languages": self.languages,
            "hours": self.hours,
            "walk_ins": self.walk_ins,
            "verified": self.verified,
        }
        if self.address is not None:
            data["address"] = self.address
        return data

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)
