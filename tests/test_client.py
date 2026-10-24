"""Stage 0 integration gates for staff templates and the public PWA shell."""
import re
from html import unescape
import unittest
import test_avenra

class ClientIntegrationTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def test_login_has_real_password_form_and_csrf(self):
        response = self.client.get('/login')
        html = response.get_data(as_text=True)
        self.assertIn('name="csrf_token"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('method="post"', html)
        self.assertNotIn('quick_role', html)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_login_rejects_missing_csrf(self):
        self.assertEqual(self.client.post('/login', data={'email':'nomsa@avenra.demo','password':self.staff_password}).status_code, 400)

    def test_bad_password_has_generic_visible_error(self):
        html = self.client.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)
        result = self.client.post('/login', data={'email':'unknown@example.test','password':'wrong','csrf_token':token})
        self.assertEqual(result.status_code, 401)
        self.assertIn("don't match", unescape(result.get_data(as_text=True)))

    def test_staff_pages_render_identity_and_post_logout(self):
        self._login_staff()
        for path in ('/dashboard','/shelters','/referrals','/cases','/cases/SP-1042','/audit-log'):
            with self.subTest(path=path):
                response = self.client.get(path)
                html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn('Nomsa D', html)
                self.assertIn('Nomsa D', html)
                self.assertIn('action="/logout"', html)
                self.assertIn('name="csrf_token"', html)
                self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.client.get('/logout').status_code, 405)
        self.assertEqual(self.client.post('/logout').status_code, 400)

    def test_valid_logout_ends_access(self):
        self._login_staff()
        html = self.client.get('/dashboard').get_data(as_text=True)
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)
        self.assertEqual(self.client.post('/logout',data={'csrf_token':token}).status_code,302)
        self.assertEqual(self.client.get('/api/alerts').status_code,401)

    def test_shelter_navigation_does_not_offer_private_case_routes(self):
        self._login_staff('shelter')
        html = self.client.get('/shelters').get_data(as_text=True)
        self.assertNotIn('href="/cases"', html)
        self.assertNotIn('href="/audit-log"', html)
        self.assertEqual(self.client.get('/cases').status_code,403)

    def test_pwa_has_consistent_identity_and_all_local_assets(self):
        with self.client.get('/survivor/', buffered=True) as response:
            html = response.get_data(as_text=True)
        with self.client.get('/survivor/manifest.json', buffered=True) as response:
            manifest = response.json
        self.assertIn('<title>' + manifest['name'] + '</title>', html)
        self.assertEqual(manifest['short_name'], manifest['name'])
        self.assertNotIn('user-scalable=no', html)
        self.assertNotIn('maximum-scale=1', html)
        self.assertNotIn('demo-device', html)
        self.assertEqual(manifest['scope'], '/survivor/')
        self.assertEqual(manifest['display'], 'standalone')
        for path in ('/survivor/index.html','/survivor/setup.html','/survivor/shell.js',
                     '/survivor/queue.js','/survivor/survivor.js','/static/css/style.css',
                     *[i['src'] for i in manifest['icons']]):
            with self.subTest(path=path), self.client.get(path, buffered=True) as response:
                self.assertEqual(response.status_code,200)
                self.assertGreater(len(response.data),0)

if __name__ == '__main__':
    unittest.main()
