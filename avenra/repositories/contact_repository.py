"""Contact data access repository."""
from typing import List, Tuple
from avenra.repositories.base import BaseRepository


class ContactRepository(BaseRepository):
    """Encapsulates SQL operations on the contacts table."""

    def get_for_user(self, user_id: int) -> List[dict]:
        rows = self.conn.execute(
            "SELECT id, name, phone FROM contacts WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [{"id": r["id"], "name": r["name"], "phone": r["phone"]} for r in rows]

    def replace_contacts(self, user_id: int, contacts: List[Tuple[str, str]]) -> None:
        self.conn.execute("DELETE FROM contacts WHERE user_id = ?", (user_id,))
        for name, phone in contacts:
            self.conn.execute(
                "INSERT OR IGNORE INTO contacts (user_id, name, phone) VALUES (?, ?, ?)",
                (user_id, name, phone),
            )
