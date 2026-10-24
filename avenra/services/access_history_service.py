"""Build a minimal access-history response for the survivor."""
from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from avenra.repositories.access_history_repository import (
    AccessHistoryRepository,
)


class AccessHistoryService:
    CURSOR_SALT = "avenra-survivor-access-history-v1"
    CURSOR_MAX_AGE = 900

    def __init__(self, repository=None):
        self.repository = (
            repository
            if repository is not None
            else AccessHistoryRepository()
        )

    def _serializer(self):
        return URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"],
            salt=self.CURSOR_SALT,
        )

    def list_history(self, survivor, args):
        # No client-supplied ownership selectors or unknown parameters.
        if set(args) - {"limit", "cursor"}:
            return {"error": "invalid_history_parameters"}, 400

        if any(len(args.getlist(key)) != 1 for key in args):
            return {"error": "invalid_history_parameters"}, 400

        raw_limit = args.get("limit", "20")
        if (
            not isinstance(raw_limit, str)
            or not 1 <= len(raw_limit) <= 2
            or not raw_limit.isascii()
            or not raw_limit.isdigit()
        ):
            return {"error": "invalid_history_limit"}, 400

        limit = int(raw_limit)
        if not 1 <= limit <= 50:
            return {"error": "invalid_history_limit"}, 400

        before = None

        if "cursor" in args:
            token = args["cursor"]

            if not token or len(token) > 2048:
                return {"error": "invalid_history_cursor"}, 400

            try:
                cursor = self._serializer().loads(
                    token,
                    max_age=self.CURSOR_MAX_AGE,
                )
            except BadData:
                return {"error": "invalid_history_cursor"}, 400

            if (
                not isinstance(cursor, dict)
                or set(cursor) != {"survivor_id", "ts", "id"}
                or type(cursor["survivor_id"]) is not int
                or cursor["survivor_id"] != survivor.id
                or not isinstance(cursor["ts"], str)
                or not 1 <= len(cursor["ts"]) <= 64
                or type(cursor["id"]) is not int
                or cursor["id"] < 1
            ):
                return {"error": "invalid_history_cursor"}, 400

            before = (cursor["ts"], cursor["id"])

        rows = self.repository.get_page(
            survivor.id,
            limit + 1,
            before=before,
        )
        visible = rows[:limit]

        # Explicit allowlist: never serialize the internal audit object.
        events = [
            {
                "id": row["id"],
                "viewed_at": row["ts"],
                "actor_name": (
                    row["actor_name"]
                    or "Staff member (name unavailable)"
                ),
                "actor_role": row["actor_role"] or "staff",
                "action": row["action"],
            }
            for row in visible
        ]

        next_cursor = None

        if len(rows) > limit:
            last = visible[-1]
            next_cursor = self._serializer().dumps({
                "survivor_id": survivor.id,
                "ts": last["ts"],
                "id": last["id"],
            })

        return {
            "events": events,
            "next_cursor": next_cursor,
        }, 200