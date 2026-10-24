"""Diary entry data access repository."""
from typing import Optional, List
from avenra.repositories.base import BaseRepository
from avenra.models.diary import DiaryEntry


class DiaryRepository(BaseRepository):
    """Encapsulates SQL operations on the diary_entries table."""

    def get_by_id(self, entry_id: int) -> Optional[DiaryEntry]:
        row = self.conn.execute("SELECT * FROM diary_entries WHERE id = ?", (entry_id,)).fetchone()
        return DiaryEntry.from_row(row)

    def get_by_client_id(self, client_id: str) -> Optional[DiaryEntry]:
        row = self.conn.execute("SELECT * FROM diary_entries WHERE client_id = ?", (client_id,)).fetchone()
        return DiaryEntry.from_row(row)

    def create(
            self,
            user_id: int,
            note: str,
            photo_path: Optional[str],
            file_hash: str,
            shared: int,
            client_id: str,
            created_at: str,
            captured_at: Optional[str] = None,
            received_at: Optional[str] = None,
    ) -> DiaryEntry:
        cur = self.conn.execute(
            """
            INSERT INTO diary_entries (
                user_id, note, photo_path, file_hash, shared,
                client_id, created_at, captured_at, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, note, photo_path, file_hash, shared,
                client_id, created_at, captured_at, received_at,
            ),
        )
        return self.get_by_id(cur.lastrowid)

    def list_for_survivor(self, user_id: int, limit: int = 30) -> List[DiaryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [DiaryEntry.from_row(r) for r in rows]

    def list_shared_for_case(self, user_id: int, limit: int = 50) -> List[DiaryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE user_id = ? AND shared = 1 ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [DiaryEntry.from_row(r) for r in rows]
