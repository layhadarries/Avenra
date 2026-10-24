"""Staff directory must not present unverified availability."""
import unittest
from contextlib import closing

import test_avenra


class ShelterDirectoryPageTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def test_page_excludes_capacity_claims(self):
        with closing(test_avenra.db.connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE shelters
                    SET beds_total = 29, beds_available = 17
                    """
                )

        self._login_staff("responder")
        response = self.client.get("/shelters")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertNotIn("Available beds", html)
        self.assertNotIn("17 / 29", html)
        self.assertNotIn("Accepting referrals", html)
        self.assertNotIn("Not accepting", html)
        self.assertIn("Contact to confirm", html)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_stored_accepting_flag_does_not_change_availability_message(self):
        self._login_staff("responder")

        for accepting in (0, 1):
            with self.subTest(accepting=accepting):
                with closing(test_avenra.db.connect()) as conn:
                    with conn:
                        conn.execute(
                            "UPDATE shelters SET accepting = ?",
                            (accepting,),
                        )

                response = self.client.get("/shelters")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)

                self.assertIn("Contact to confirm", html)
                self.assertNotIn("Accepting referrals", html)
                self.assertNotIn("Not accepting", html)


if __name__ == "__main__":
    unittest.main()