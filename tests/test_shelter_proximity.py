"""Nearby directory matching using fictional coordinates."""
import unittest
from types import SimpleNamespace

from avenra.models.shelter import Shelter
from avenra.services.shelter_service import ShelterService


class ShelterProximityTests(unittest.TestCase):
    def setUp(self):
        shelters = [
            Shelter(id=3, name="Outside both radii", lat=0.6, lng=0),
            Shelter(id=2, name="About 33 km away", lat=0.3, lng=0),
            Shelter(id=1, name="About 11 km away", lat=0.1, lng=0),
            Shelter(id=4, name="Location unknown"),
        ]
        repository = SimpleNamespace(get_all=lambda: shelters)
        self.service = ShelterService(shelter_repo=repository)

    def test_default_radius_is_25_km(self):
        entries = self.service.list_nearby_shelters(0, 0)

        self.assertEqual([entry["id"] for entry in entries], [1])
        self.assertGreater(entries[0]["distance_km"], 0)
        self.assertLess(entries[0]["distance_km"], 25)
        self.assertEqual(
            entries[0]["availability"],
            "contact_to_confirm",
        )
        self.assertNotIn("beds_available", entries[0])

    def test_50_km_radius_returns_nearest_first(self):
        entries = self.service.list_nearby_shelters(
            0, 0, radius_km=50
        )

        self.assertEqual([entry["id"] for entry in entries], [1, 2])
        self.assertLess(
            entries[0]["distance_km"],
            entries[1]["distance_km"],
        )

    def test_only_25_or_50_km_is_allowed(self):
        for radius in (0, -25, 30, 100, True, "25"):
            with self.subTest(radius=radius):
                with self.assertRaises(ValueError):
                    self.service.list_nearby_shelters(
                        0, 0, radius_km=radius
                    )

    def test_invalid_origin_does_not_return_an_unfiltered_directory(self):
        origins = (
            (None, None),
            (True, 0),
            ("0", 0),
            (91, 0),
            (0, 181),
            (float("nan"), 0),
            (0, float("inf")),
        )

        for lat, lng in origins:
            with self.subTest(lat=lat, lng=lng):
                with self.assertRaises(ValueError):
                    self.service.list_nearby_shelters(lat, lng)


if __name__ == "__main__":
    unittest.main()