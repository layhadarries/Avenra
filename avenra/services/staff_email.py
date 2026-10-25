"""Configured SMTP delivery with TLS; never prints email bodies or credentials."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def send_staff_email(recipient, subject, body):
    host = os.environ.get('SMTP_HOST')
    sender = os.environ.get('SMTP_FROM')
    username = os.environ.get('SMTP_USERNAME')
    password = os.environ.get('SMTP_PASSWORD')
    if not host or not sender or not username or not password:
        raise RuntimeError('SMTP configuration is incomplete')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    port = int(os.environ.get('SMTP_PORT','587'))
    if os.environ.get('SMTP_TLS_MODE','starttls') == 'ssl':
        with smtplib.SMTP_SSL(host,port,timeout=15,context=context) as server:
            server.login(username,password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host,port,timeout=15) as server:
            server.ehlo(); server.starttls(context=context); server.ehlo()
            server.login(username,password)
            server.send_message(message)
