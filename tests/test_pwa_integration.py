"""Merged PWA/backend contracts. Isolated records, no messages sent."""
import unittest
import test_avenra

class PWAIntegrationTests(unittest.TestCase):
    setUp = test_avenra.avenraStagesTestCase.setUp
    tearDown = test_avenra.avenraStagesTestCase.tearDown
    _login_staff = test_avenra.avenraStagesTestCase._login_staff

    def contacts(self):
        response=self.client.get('/api/contacts',headers=self.survivor_headers)
        self.assertEqual(response.status_code,200)
        return response.json['contacts']

    def add(self,name='New Contact',phone='0821234567'):
        return self.client.post('/api/contacts',json={'name':name,'phone':phone},headers=self.survivor_headers)

    def test_single_add_preserves_existing_contacts_and_masks_number(self):
        before=self.contacts()
        response=self.add()
        self.assertEqual(response.status_code,201)
        saved=response.json['contacts']
        self.assertTrue({r['id'] for r in before}<={r['id'] for r in saved})
        row=next(r for r in saved if r['name']=='New Contact')
        self.assertEqual(row['phone_masked'],'••••4567')
        self.assertNotIn('phone',row)

    def test_single_add_uses_same_five_contact_limit(self):
        self.assertEqual(self.client.post('/api/contacts',json={'contacts':[]},headers=self.survivor_headers).status_code,200)
        for i in range(5):self.assertEqual(self.add(str(i),f'+2782123456{i}').status_code,201)
        response=self.add('six','+27832345678')
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json['error'],'contact_limit')
        self.assertEqual(len(self.contacts()),5)

    def test_duplicate_add_is_rejected_without_changing_saved_list(self):
        self.assertEqual(self.add().status_code,201)
        before=self.contacts()
        self.assertEqual(self.add('Other Name','+27821234567').status_code,400)
        self.assertEqual(self.contacts(),before)

    def test_single_delete_removes_only_selected_owned_contact(self):
        self.assertEqual(self.add().status_code,201)
        before=self.contacts()
        selected=next(r for r in before if r['name']=='New Contact')
        response=self.client.delete(f"/api/contacts/{selected['id']}",headers=self.survivor_headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual({r['id'] for r in response.json['contacts']},
            {r['id'] for r in before}-{selected['id']})

    def test_delete_other_survivor_contact_returns_not_found(self):
        conn=test_avenra.db.connect()
        try:
            user=conn.execute("INSERT INTO users(name,role,email,case_code) VALUES('Other','survivor','other@example.test','OTHER')").lastrowid
            contact=conn.execute("INSERT INTO contacts(user_id,name,phone) VALUES(?, 'Other Contact', '+27832345678')",(user,)).lastrowid
            conn.commit()
        finally:conn.close()
        response=self.client.delete(f'/api/contacts/{contact}',headers=self.survivor_headers)
        self.assertEqual(response.status_code,404)
        conn=test_avenra.db.connect()
        try:self.assertIsNotNone(conn.execute('SELECT id FROM contacts WHERE id=?',(contact,)).fetchone())
        finally:conn.close()

    def test_staff_cookie_does_not_authorise_contact_deletion(self):
        selected=self.contacts()[0]['id']
        self._login_staff()
        self.assertEqual(self.client.delete(f'/api/contacts/{selected}').status_code,401)

    def test_shell_and_manifest_use_same_identity_and_offline_assets(self):
        with self.client.get('/survivor/manifest.json',buffered=True) as response:
            manifest=response.json
        self.assertEqual(manifest['name'],'Cape Weather')
        with self.client.get('/survivor/',buffered=True) as response:
            html=response.get_data(as_text=True)
        self.assertIn('<title>'+manifest['name']+'</title>',html)
        self.assertIn('id="offline-state"',html)
        self.assertIn('id="connection-state"',html)
        self.assertNotIn('user-scalable=no',html)
        for path in ('shell.js','queue.js','survivor.js','setup.html'):
            with self.subTest(path=path), self.client.get('/survivor/'+path,buffered=True) as response:
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.data)

    def test_cross_origin_contact_deletion_is_rejected(self):
        selected=self.contacts()[0]['id']
        before=self.contacts()
        response=self.client.delete(f'/api/contacts/{selected}',headers={
            **self.survivor_headers,'Origin':'https://other.example.test'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.contacts(),before)
