"""Run queued SMS work. Default is a dry run with no DB or network access."""
import argparse
import os
from pathlib import Path
import sqlite3
import time
from avenra.services.sms_sender import TwilioSender,SenderConfigurationError

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true')
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--max-jobs',type=int,default=10)
    args=parser.parse_args(argv)
    if not args.send:
        print('DRY RUN: no jobs claimed, no database opened, no messages sent.')
        return 0
    if not 1<=args.max_jobs<=100:parser.error('--max-jobs must be 1–100')
    try:
        sender=TwilioSender(os.environ)
        path=os.environ.get('DATABASE_PATH')
        if not path or not Path(path).is_file():
            raise SenderConfigurationError('Start the backend with an explicit DATABASE_PATH first.')
    except SenderConfigurationError as error:
        print('Worker configuration error:',error)
        return 2
    import db
    from avenra.services.notification_worker import NotificationWorker
    conn=db.connect()
    try:
        if conn.execute("SELECT 1 FROM app_metadata WHERE key='evaluation_fixture'").fetchone():
            print('Worker refused: fictional evaluation database. No messages sent.')
            return 2
        worker=NotificationWorker(conn,sender,evaluation_mode=False)
        while True:
            recovered=worker.recover_stale()
            processed=0
            for _ in range(args.max_jobs):
                if not worker.run_once():break
                processed+=1
            if not args.watch:
                print(f'Processed {processed} job(s); recovered {recovered} uncertain claim(s). Delivery is not implied.')
                return 0
            time.sleep(2)
    except KeyboardInterrupt:
        return 0
    except Exception:
        # Do not print provider bodies, message contents, credentials or recipient data.
        print('Worker stopped after an operational error. Inspect protected state; uncertain jobs must not be blindly resent.')
        return 1
    finally:
        conn.close()
if __name__=='__main__':raise SystemExit(main())
