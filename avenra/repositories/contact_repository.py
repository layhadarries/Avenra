"""Trusted-contact persistence. Preserve unchanged recipients and their jobs."""
import secrets
from avenra.repositories.base import BaseRepository
class ContactRepository(BaseRepository):
    def get_for_user(self,user_id):
        return [dict(r) for r in self.conn.execute(
            'SELECT id,name,phone FROM contacts WHERE user_id=? ORDER BY id',(user_id,))]
    def replace_contacts(self,user_id,contacts):
        existing=self.get_for_user(user_id)
        by_phone={row['phone']:row for row in existing}
        phones={phone for name,phone in contacts}
        for row in existing:
            if row['phone'] not in phones:
                self.conn.execute('DELETE FROM contacts WHERE id=? AND user_id=?',(row['id'],user_id))
        # Avoid temporary unique-name conflicts during a rename/swap.
        for row in existing:
            if row['phone'] in phones:
                self.conn.execute('UPDATE contacts SET name=? WHERE id=? AND user_id=?',
                    ('_avenra_'+secrets.token_hex(16),row['id'],user_id))
        for name,phone in contacts:
            row=by_phone.get(phone)
            if row:
                self.conn.execute('UPDATE contacts SET name=? WHERE id=? AND user_id=?',(name,row['id'],user_id))
            else:
                self.conn.execute('INSERT INTO contacts(user_id,name,phone) VALUES(?,?,?)',(user_id,name,phone))
