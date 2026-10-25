"""Web Push worker. Dry run unless --send is explicit. No SMS fallback."""
import argparse
import os
from pathlib import Path
import time

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send',action='store_true');parser.add_argument('--watch',action='store_true')
    parser.add_argument('--max-jobs',type=int,default=10)
    args=parser.parse_args(argv)
    if not args.send:print('DRY RUN: no jobs claimed, no network or messages.');return 0
    if not 1<=args.max_jobs<=100:parser.error('--max-jobs must be 1 to 100')
    if os.environ.get('APP_ENV') not in {'development','production'}:
        print('Push worker requires development or production mode; evaluation alerts cannot dispatch.');return 2
    path=os.environ.get('DATABASE_PATH')
    if not os.environ.get('DATABASE_URL') and (not path or not Path(path).is_file()):print('Push worker requires an explicit existing DATABASE_PATH.');return 2
    from avenra.services.push_service import PushSettings,PushError
    try:settings=PushSettings()
    except PushError:print('Push configuration unavailable.');return 2
    from avenra.services.webpush_sender import WebPushSender
    from avenra.services.push_worker import PushWorker
    from avenra.services.notification_worker import NotificationWorker
    import db
    conn=db.connect()
    try:
        if conn.execute("SELECT 1 FROM app_metadata WHERE key='evaluation_fixture'").fetchone():
            print('Push worker refused fictional evaluation jobs.');return 2
        worker=PushWorker(conn,WebPushSender(settings),settings,evaluation_mode=False)
        # Existing recovery marks stale claims unknown rather than blindly resending.
        recovery=NotificationWorker(conn,lambda **_:None,evaluation_mode=False)
        while True:
            recovery.recover_stale()
            count=0
            for _ in range(args.max_jobs):
                if not worker.run_once():break
                count+=1
            if not args.watch:print('Processed',count,'push job(s). Provider acceptance is not receipt.');return 0
            time.sleep(2)
    except KeyboardInterrupt:return 0
    except Exception:print('Push worker stopped. Uncertain jobs must not be blindly resent.');return 1
    finally:conn.close()

if __name__=='__main__':raise SystemExit(main())
