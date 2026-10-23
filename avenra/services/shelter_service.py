"""Shelter and bed capacity service."""
from typing import Optional, Tuple, Dict, Any, List
from avenra.repositories.shelter_repository import ShelterRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.models.shelter import Shelter


class ShelterService:
    """Manages shelters and bed capacity allocation."""

    def __init__(
        self,
        shelter_repo: Optional[ShelterRepository] = None,
        audit_repo: Optional[AuditRepository] = None,
    ):
        self.shelter_repo = shelter_repo or ShelterRepository()
        self.audit_repo = audit_repo or AuditRepository()

    def list_shelters(self) -> List[Dict[str, Any]]:
        shelters = self.shelter_repo.get_all()
        return [s.serialize() for s in shelters]

    def update_capacity(
        self,
        shelter_id: int,
        user: User,
        data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], int]:
        self.shelter_repo.conn.execute('BEGIN IMMEDIATE')
        shelter = self.shelter_repo.get_by_id(shelter_id)
        if shelter is None:
            return {"error": "not_found"}, 404

        if user.role == "shelter" and user.shelter_id != shelter_id:
            return {"error": "forbidden"}, 403

        if not data or set(data) - {'delta', 'beds_available', 'accepting'}:
            return {"error": "invalid_capacity_update"}, 400
        for field in ('delta', 'beds_available'):
            if field in data and type(data[field]) is not int:
                return {"error": "capacity_must_be_integer"}, 400
        if 'delta' in data and 'beds_available' in data:
            return {"error": "ambiguous_capacity_update"}, 400
        if 'accepting' in data and type(data['accepting']) is not bool:
            return {"error": "accepting_must_be_boolean"}, 400
        beds = shelter.beds_available
        if "delta" in data:
            try:
                beds = beds + int(data["delta"])
            except (TypeError, ValueError):
                return {"error": "bad_delta"}, 400
        elif "beds_available" in data:
            try:
                beds = int(data["beds_available"])
            except (TypeError, ValueError):
                return {"error": "bad_beds_available"}, 400

        beds = max(0, min(shelter.beds_total, beds))

        accepting = 1 if shelter.accepting else 0
        if "accepting" in data:
            accepting = 1 if data["accepting"] else 0

        updated = self.shelter_repo.update_capacity(shelter_id, beds, accepting)
        self.audit_repo.log(
            user.name,
            "shelter_capacity_updated",
            detail=f"{shelter.name}: {beds}/{shelter.beds_total} beds, accepting={'yes' if accepting else 'no'}",
        )
        return {"shelter": updated.serialize()}, 200
