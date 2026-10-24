"""Public shelter directory must not imply confirmed availability."""
import unittest
from types import SimpleNamespace

from avenra.models.shelter import Shelter
from avenra.services.shelter_service import ShelterService


class ShelterDirectoryTests(unittest.TestCase):
    def directory(self, shelters):
        repository = SimpleNamespace(get_all=lambda: shelters)
        service = ShelterService(shelter_repo=repository)
        return service.list_shelters()

    def test_directory_excludes_bed_counts_and_accepting_flag(self):
        shelter = Shelter(
            id=1,
            name="Test support service",
            beds_total=20,
            beds_available=8,
            accepting=1,
        )

        entry = self.directory([shelter])[0]

        for field in ("beds_total", "beds_available", "accepting"):
            with self.subTest(field=field):
                self.assertNotIn(field, entry)

    def test_availability_requires_confirmation_regardless_of_old_counts(self):
        for beds, accepting in ((8, 1), (0, 1), (0, 0)):
            with self.subTest(beds=beds, accepting=accepting):
                shelter = Shelter(
                    id=1,
                    name="Test support service",
                    beds_available=beds,
                    accepting=accepting,
                )

                entry = self.directory([shelter])[0]

                self.assertEqual(
                    entry.get("availability"),
                    "contact_to_confirm",
                )

    def test_directory_preserves_basic_service_details(self):
        shelter = Shelter(
            id=7,
            name="Test support service",
            hours="Monday to Friday, 09:00–17:00",
        )

        entry = self.directory([shelter])[0]

        self.assertEqual(entry["id"], 7)
        self.assertEqual(entry["name"], "Test support service")
        self.assertEqual(entry["hours"], "Monday to Friday, 09:00–17:00")


if __name__ == "__main__":
    unittest.main()