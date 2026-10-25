"""SQL boundary tests never connect to production or use actual credentials."""
import unittest
from avenra.postgres import translate, Row

class PostgresAdapterTests(unittest.TestCase):
    def test_parameters_stay_bound_and_literals_are_preserved(self):
        result=translate("SELECT * FROM users WHERE email=? AND name='why?' AND org=?")
        self.assertEqual(result,"SELECT * FROM avenra.users WHERE email=%s AND name='why?' AND org=%s")
        self.assertNotIn("DROP TABLE",result)

    def test_case_grants_use_postgres_conflict_handling(self):
        self.assertEqual(translate('INSERT OR IGNORE INTO case_access(staff_id,survivor_id) VALUES(?,?)'),
                         'INSERT INTO avenra.case_access(staff_id,survivor_id) VALUES(%s,%s) ON CONFLICT DO NOTHING')

    def test_row_supports_existing_model_and_portal_contract(self):
        row=Row(id=12,name='Test')
        self.assertEqual(row[0],12)
        self.assertEqual(row['name'],'Test')
        self.assertEqual(tuple(row),(12,'Test'))
        self.assertEqual(dict(row),{'id':12,'name':'Test'})

    def test_time_and_text_functions_are_translated(self):
        result=translate("UPDATE push_invites SET used_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?")
        self.assertNotIn('strftime',result)
        self.assertIn('UPDATE avenra.push_invites',result)
        self.assertIn('avenra.instr(',translate('SELECT instr(name,?) FROM users'))
