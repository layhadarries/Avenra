"""HTTPS login/logout must work with token + public Origin, without Referer."""
import re
import unittest
from contextlib import closing
from unittest.mock import patch
import test_avenra as fixtures

class StaffHTTPSAuthTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    @patch.dict('os.environ', {'PUBLIC_BASE_URL':'https://localhost'})
    def test_https_login_and_global_logout_without_referer(self):
        with closing(fixtures.db.connect()) as conn:
            email=conn.execute("SELECT email FROM users WHERE role='responder' ORDER BY id LIMIT 1").fetchone()[0]
        page=self.client.get('/login',base_url='https://localhost')
        self.assertEqual(page.headers['Referrer-Policy'],'same-origin')
        token=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        data={'email':email,'password':self.staff_password,'csrf_token':token}
        self.assertEqual(self.client.post('/login',base_url='https://localhost',data=data,headers={'Origin':'https://foreign.example'}).status_code,403)
        self.assertEqual(self.client.post('/login',base_url='https://localhost',data=data,headers={'Origin':'https://localhost'}).status_code,302)
        self.assertEqual(self.client.get('/api/session',base_url='https://localhost').status_code,401)
        page=self.client.get('/mfa',base_url='https://localhost')
        token=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        self.assertEqual(self.client.post('/mfa',base_url='https://localhost',data={'csrf_token':token,'code':'000000'},headers={'Origin':'https://foreign.example'}).status_code,403)
        from mfa_fixture import complete_mfa
        complete_mfa(self,base_url='https://localhost')
        page=self.client.get('/dashboard',base_url='https://localhost')
        self.assertEqual(page.status_code,200)
        token=re.search(r'name="csrf_token"\s+value="([^"]+)"',page.text).group(1)
        self.assertEqual(self.client.get('/logout',base_url='https://localhost').status_code,405)
        self.assertEqual(self.client.post('/logout',base_url='https://localhost',data={'csrf_token':token},headers={'Origin':'https://foreign.example'}).status_code,403)
        self.assertEqual(self.client.post('/logout',base_url='https://localhost',headers={'Origin':'https://localhost'}).status_code,400)
        self.assertEqual(self.client.post('/logout',base_url='https://localhost',data={'csrf_token':token},headers={'Origin':'https://localhost'}).status_code,302)
        self.assertEqual(self.client.get('/api/alerts',base_url='https://localhost').status_code,401)
