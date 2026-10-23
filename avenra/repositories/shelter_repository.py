"""Shelter data access repository."""
from typing import Optional, List
from avenra.repositories.base import BaseRepository
from avenra.models.shelter import Shelter


class ShelterRepository(BaseRepository):
    """Encapsulates SQL operations on the shelters table."""

    def get_all(self) -> List[Shelter]:
        rows = self.conn.execute("SELECT * FROM shelters ORDER BY id").fetchall()
        return [Shelter.from_row(r) for r in rows]

    def get_by_id(self, shelter_id: int) -> Optional[Shelter]:
        row = self.conn.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
        return Shelter.from_row(row)

    def update_capacity(self, shelter_id: int, beds_available: int, accepting: int) -> Optional[Shelter]:
        self.conn.execute(
            "UPDATE shelters SET beds_available = ?, accepting = ? WHERE id = ?",
            (beds_available, accepting, shelter_id),
        )
        return self.get_by_id(shelter_id)

    def decrement_bed(self, shelter_id: int) -> None:
        self.conn.execute(
            "UPDATE shelters SET beds_available = MAX(0, beds_available - 1) WHERE id = ?",
            (shelter_id,),
        )
