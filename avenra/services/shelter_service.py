"""Shelter and bed capacity service."""
from typing import Optional, Tuple, Dict, Any, List
from avenra.repositories.shelter_repository import ShelterRepository
from avenra.repositories.audit_repository import AuditRepository
from avenra.models.user import User
from avenra.models.shelter import Shelter
import math

from avenra.repositories.alert_repository import AlertRepository
from avenra.repositories.case_access_repository import CaseAccessRepository
from avenra.repositories.consent_repository import ConsentRepository

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
        """Return directory information without claiming live capacity."""
        public_fields = (
            "id",
            "name",
            "lat",
            "lng",
            "languages",
            "hours",
            "walk_ins",
            "verified",
            "address",
        )

        directory = []

        for shelter in self.shelter_repo.get_all():
            serialized = shelter.serialize()

            entry = {
                field: serialized[field]
                for field in public_fields
                if field in serialized
            }
            entry["availability"] = "contact_to_confirm"
            directory.append(entry)

        return directory

    def list_nearby_shelters(
        self,
        lat: float,
        lng: float,
        radius_km: int = 25,
    ) -> List[Dict[str, Any]]:
        """Return nearby services ordered by straight-line distance."""

        def valid_coordinate(value, limit):
            return (
                type(value) in (int, float)
                and -limit <= value <= limit
                and math.isfinite(value)
            )

        if not valid_coordinate(lat, 90):
            raise ValueError("A valid latitude is required.")

        if not valid_coordinate(lng, 180):
            raise ValueError("A valid longitude is required.")

        if type(radius_km) is not int or radius_km not in (25, 50):
            raise ValueError("Radius must be 25 or 50 kilometres.")

        nearby = []

        for entry in self.list_shelters():
            shelter_lat = entry.get("lat")
            shelter_lng = entry.get("lng")

            if not (
                valid_coordinate(shelter_lat, 90)
                and valid_coordinate(shelter_lng, 180)
            ):
                continue

            latitude_delta = math.radians(shelter_lat - lat)
            longitude_delta = math.radians(shelter_lng - lng)

            haversine = (
                math.sin(latitude_delta / 2) ** 2
                + math.cos(math.radians(lat))
                * math.cos(math.radians(shelter_lat))
                * math.sin(longitude_delta / 2) ** 2
            )
            haversine = max(0.0, min(1.0, haversine))

            distance = (
                6371.0088
                * 2
                * math.asin(math.sqrt(haversine))
            )

            # Filter using the full distance before rounding for display.
            if distance <= radius_km:
                entry["distance_km"] = round(distance, 2)
                nearby.append((distance, entry))

        nearby.sort(key=lambda item: (item[0], item[1]["id"]))

        return [entry for _, entry in nearby]

    def update_capacity(
        self,
        shelter_id: int,
        user: User,
        data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], int]:
        conn = self.shelter_repo.conn
        committed = False
        try:
            conn.execute('BEGIN IMMEDIATE')
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
                commit=False,
            )
            conn.commit()
            committed = True
            return {"shelter": updated.serialize()}, 200
        finally:
            if not committed:
                conn.rollback()

    def nearby_for_alert(self, alert_id, user, radius_values):
        """Match services only against an authorised, consented location."""
        conn = self.shelter_repo.conn
        alert = AlertRepository(conn).get_by_id(alert_id)

        # Use the same response for missing and inaccessible alerts.
        if alert is None or not CaseAccessRepository(conn).allows(
            user.id, alert.user_id
        ):
            return {"error": "not_found"}, 404

        # Reject repeated parameters as well as unsupported values.
        if not radius_values:
            radius_km = 25
        elif len(radius_values) == 1 and radius_values[0] in ("25", "50"):
            radius_km = int(radius_values[0])
        else:
            return {"error": "invalid_radius"}, 400

        location_allowed = ConsentRepository(conn).is_active(
            alert.user_id, "location_sharing"
        )
        if not location_allowed or not alert.has_coordinates():
            return {"error": "location_unavailable"}, 409

        try:
            entries = self.list_nearby_shelters(
                alert.lat,
                alert.lng,
                radius_km=radius_km,
            )
        except ValueError:
            return {"error": "location_unavailable"}, 409

        return {
            "radius_km": radius_km,
            "shelters": entries,
        }, 200
