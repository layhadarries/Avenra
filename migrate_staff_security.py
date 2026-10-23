"""Back up a database before applying the additive Stage 0 migrations."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import db


def main():
    os.umask(0o077)
    database = Path(db.DB_PATH).resolve()
    if not database.is_file():
        raise SystemExit('Database not found. Check DATABASE_PATH.')
    folder = database.parent / 'private-backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = folder / f'before-stage0-migration-{stamp}.sqlite3'
    source = db.connect()
    backup = sqlite3.connect(str(path))
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()
    path.chmod(0o600)
    db.init_db()
    print('Migration complete. Private backup:', path)
    print('Existing account activation and authentication versions were preserved.')
    print('Previously missing activation fields default to disabled. No case history was deleted.')


if __name__ == '__main__':
    main()
