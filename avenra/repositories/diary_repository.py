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

    def get_by_owner_and_client_id(self, user_id: int, client_id: str) -> Optional[DiaryEntry]:
        row = self.conn.execute(
            "SELECT * FROM diary_entries WHERE user_id = ? AND client_id = ?",
            (user_id, client_id),
        ).fetchone()
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
            note_sha256: Optional[str] = None,
            photo_sha256: Optional[str] = None,
            entry_fingerprint: Optional[str] = None,
            contract_version: int = 1,
    ) -> DiaryEntry:
        cur = self.conn.execute(
            """
            INSERT INTO diary_entries (
                user_id, note, photo_path, file_hash, shared,
                client_id, created_at, captured_at, received_at,
                note_sha256, photo_sha256, entry_fingerprint, contract_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, note, photo_path, file_hash, shared,
                client_id, created_at, captured_at, received_at,
                note_sha256, photo_sha256, entry_fingerprint, contract_version,
            ),
        )
        return self.get_by_id(cur.lastrowid)

    def list_for_survivor(self, user_id: int, limit: int = 30) -> List[DiaryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [DiaryEntry.from_row(r) for r in rows]

    def get_page_for_survivor(
        self, user_id: int, limit: int, before=None
    ) -> List[DiaryEntry]:
        query = "SELECT * FROM diary_entries WHERE user_id = ?"
        params = [user_id]
        if before is not None:
            created_at, entry_id = before
            query += " AND (created_at < ? OR (created_at = ? AND id < ?))"
            params.extend([created_at, created_at, entry_id])
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [DiaryEntry.from_row(r) for r in rows]

    def update_shared(
        self, entry_id: int, user_id: int, shared: int
    ) -> Optional[DiaryEntry]:
        cur = self.conn.execute(
            "UPDATE diary_entries SET shared = ? WHERE id = ? AND user_id = ?",
            (shared, entry_id, user_id),
        )
        if cur.rowcount == 0:
            return None
        return self.get_by_id(entry_id)

    def list_shared_for_case(self, user_id: int, limit: int = 50) -> List[DiaryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM diary_entries WHERE user_id = ? AND shared = 1 ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [DiaryEntry.from_row(r) for r in rows]

    def list_all_photo_paths(self) -> set:
        rows = self.conn.execute(
            "SELECT photo_path FROM diary_entries WHERE photo_path IS NOT NULL"
        ).fetchall()
        return {r["photo_path"] for r in rows if r["photo_path"]}
