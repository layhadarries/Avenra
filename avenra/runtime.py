"""Supervise Gunicorn and the optional worker on the same SQLite host."""
import os
import signal
import subprocess
import sys
import threading

def main():
    # Initialise/upgrade the same database before either child starts.
    import app
    stopping=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:stopping.set())
    commands=[[sys.executable,'-m','gunicorn','app:app','--workers','1','--threads','4',
               '--bind','0.0.0.0:'+os.environ.get('PORT','5050')]]
    if os.environ.get('AVENRA_SMS_ENABLED')=='1':
        if app.app.config['EVALUATION_MODE']:
            raise RuntimeError('SMS cannot be enabled in evaluation.')
        from avenra.services.sms_sender import TwilioSender
        TwilioSender(os.environ)  # Validate before starting either child.
        commands.append([sys.executable,'-m','avenra.notification_runner','--send','--watch'])
    children=[]; result=0
    try:
        for command in commands:children.append(subprocess.Popen(command))
        while not stopping.wait(0.5):
            if any(child.poll() is not None for child in children):
                result=1;break
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:
            try:child.wait(timeout=12)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    return result
if __name__=='__main__':raise SystemExit(main())
