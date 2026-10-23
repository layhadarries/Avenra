"""Explicit case grants; account administration alone grants no case access."""
from avenra.repositories.base import BaseRepository


class CaseAccessRepository(BaseRepository):
    def allows(self, staff_id, survivor_id):
        return self.conn.execute(
            'SELECT 1 FROM case_access WHERE staff_id = ? AND survivor_id = ?',
            (staff_id, survivor_id),
        ).fetchone() is not None

    def candidates(self, survivor_id):
        return [dict(row) for row in self.conn.execute(
            """SELECT u.id, u.name FROM users u JOIN case_access c ON c.staff_id=u.id
               WHERE c.survivor_id=? AND u.role IN ('responder','admin') AND u.is_active=1
               ORDER BY u.name, u.id""", (survivor_id,))]

    def grant(self, staff_id: int, survivor_id: int) -> bool:
        self.conn.execute(
            "INSERT OR IGNORE INTO case_access (staff_id, survivor_id) VALUES (?, ?)",
            (staff_id, survivor_id),
        )
        return True

    def revoke(self, staff_id: int, survivor_id: int) -> bool:
        self.conn.execute(
            "DELETE FROM case_access WHERE staff_id = ? AND survivor_id = ?",
            (staff_id, survivor_id),
        )
        return True

    def list_grants(self, survivor_id: int):
        return [dict(row) for row in self.conn.execute(
            """SELECT u.id, u.name, u.email, u.role, u.org
               FROM users u JOIN case_access c ON c.staff_id=u.id
               WHERE c.survivor_id=?
               ORDER BY u.role, u.name""", (survivor_id,))]

    def available_staff(self, survivor_id: int):
        return [dict(row) for row in self.conn.execute(
            """SELECT u.id, u.name, u.email, u.role, u.org
               FROM users u
               WHERE u.role IN ('responder', 'admin') AND u.is_active=1
                 AND u.id NOT IN (SELECT staff_id FROM case_access WHERE survivor_id=?)
               ORDER BY u.name, u.id""", (survivor_id,))]
