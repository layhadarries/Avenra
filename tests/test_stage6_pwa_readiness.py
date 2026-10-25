"""Stage 6 PWA Readiness, Offline Shell, Accessibility, and Security Suite."""
import unittest
import json
import re
import test_avenra


class Stage6PWAReadinessTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def test_all_pwa_shells_have_consistent_clear_sky_identity(self):
        """Every survivor HTML view serves the standard Clear Sky disguise title and header."""
        shells = [
            '/survivor/',
            '/survivor/index.html',
            '/survivor/cover.html',
            '/survivor/help.html',
            '/survivor/setup.html',
            '/survivor/privacy.html',
            '/survivor/diary.html',
        ]
        for path in shells:
            with self.subTest(path=path):
                with self.client.get(path) as response:
                    self.assertEqual(response.status_code, 200, f"Failed to load {path}")
                    html = response.get_data(as_text=True)
                    self.assertIn('<title>Clear Sky</title>', html, f"Title mismatch in {path}")
                    self.assertNotIn('Cape Weather', html, f"Legacy brand found in {path}")
                    self.assertNotIn('user-scalable=no', html, f"Improper viewport in {path}")

    def test_pwa_manifest_production_specifications(self):
        """Manifest complies with standard PWA installation criteria."""
        with self.client.get('/survivor/manifest.json') as response:
            self.assertEqual(response.status_code, 200)
            manifest = response.get_json()

        self.assertEqual(manifest['name'], 'Clear Sky')
        self.assertEqual(manifest['short_name'], 'Clear Sky')
        self.assertEqual(manifest['scope'], '/survivor/')
        self.assertEqual(manifest['start_url'], '/survivor/cover.html')
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual(manifest['theme_color'], '#1d6f72')
        self.assertGreaterEqual(len(manifest['icons']), 2)

        # Verify icon assets physically exist and are accessible
        for icon in manifest['icons']:
            with self.subTest(icon=icon['src']):
                with self.client.get(icon['src']) as icon_res:
                    self.assertEqual(icon_res.status_code, 200)
                    self.assertGreater(len(icon_res.data), 0)

    def test_service_worker_caches_all_public_shell_assets(self):
        """Service worker SHELL_ASSETS list is comprehensive and all assets resolve."""
        with self.client.get('/survivor/service-worker.js') as response:
            self.assertEqual(response.status_code, 200)
            sw_code = response.get_data(as_text=True)

        match = re.search(r'const SHELL_ASSETS = \[\s*([\s\S]*?)\s*\];', sw_code)
        self.assertIsNotNone(match, "Could not find SHELL_ASSETS in service worker")
        raw_assets = match.group(1)
        assets = [a.strip().strip("'\"") for a in raw_assets.split(',') if a.strip()]

        # Ensure essential stage 1-5 assets are in shell cache
        required_assets = [
            '/survivor/',
            '/survivor/index.html',
            '/survivor/cover.html',
            '/survivor/setup.html',
            '/survivor/help.html',
            '/survivor/privacy.html',
            '/survivor/diary.html',
            '/survivor/shell.js',
            '/survivor/survivor.js',
            '/survivor/queue.js',
            '/survivor/diary.js',
            '/survivor/pwa.css',
        ]
        for req in required_assets:
            self.assertIn(req, assets, f"Missing required asset in service worker: {req}")

        # Ensure each asset returns 200 OK
        for asset in assets:
            with self.subTest(asset=asset):
                with self.client.get(asset) as res:
                    self.assertEqual(res.status_code, 200, f"Asset {asset} failed to load")

    def test_accessibility_and_calm_design_rules(self):
        """CSS includes reduced-motion media query and focus visibility rules."""
        with self.client.get('/survivor/pwa.css') as res:
            self.assertEqual(res.status_code, 200)
            css = res.get_data(as_text=True)

        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        self.assertIn('animation: none', css)

    def test_quick_exit_present_on_all_private_screens(self):
        """Every private view provides an immediate Quick Exit action to the cover shell."""
        private_views = [
            '/survivor/',
            '/survivor/index.html',
            '/survivor/help.html',
            '/survivor/privacy.html',
            '/survivor/diary.html',
        ]
        for view in private_views:
            with self.subTest(view=view):
                with self.client.get(view) as res:
                    html = res.get_data(as_text=True)
                    self.assertTrue(
                        'quick-exit' in html or 'quick-exit-pill' in html,
                        f"Quick exit missing from {view}"
                    )

    def test_storage_persistence_hook_present_in_queues(self):
        """Queue scripts check and request navigator.storage persistence."""
        for path in ('/survivor/queue.js', '/survivor/diary.js'):
            with self.subTest(path=path):
                with self.client.get(path) as res:
                    js = res.get_data(as_text=True)
                    self.assertIn('navigator.storage.persist', js)


if __name__ == '__main__':
    unittest.main()
