"""User data access repository."""
from typing import Optional
from avenra.repositories.base import BaseRepository
from avenra.models.user import User


class UserRepository(BaseRepository):
    """Encapsulates SQL operations on the users table."""

    def get_by_id(self, user_id: int) -> Optional[User]:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return User.from_row(row)

    def get_by_email(self, email: str) -> Optional[User]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return User.from_row(row)

    def get_survivor_by_case(self, case_code: str) -> Optional[User]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE role = 'survivor' AND case_code = ?",
            (case_code.strip().upper(),),
        ).fetchone()
        return User.from_row(row)

    def get_active_staff(self, user_id: int, auth_version: int) -> Optional[User]:
        row = self.conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
              AND is_active = 1
              AND password_hash IS NOT NULL
              AND auth_version = ?
            """,
            (user_id, auth_version),
        ).fetchone()
        return User.from_row(row)

    def increment_auth_version(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET auth_version = auth_version + 1 WHERE id = ?",
            (user_id,),
        )
        self.conn.commit()

    def update_survivor_name(self, user_id: int, name: str) -> None:
        """Participate in the caller's transaction; never change another role."""
        self.conn.execute(
            "UPDATE users SET name = ? WHERE id = ? AND role = 'survivor'",
            (name, user_id),
        )
