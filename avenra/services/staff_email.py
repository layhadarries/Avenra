"""Configured SMTP delivery with TLS; never prints email bodies or credentials."""
import os
import smtplib
import ssl
from html import escape
from pathlib import Path
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
    link = next(
        (line.strip() for line in body.splitlines()
         if line.strip().startswith("https://")),
        "",
    )
    html_body = (
        "<html><body style=\"font-family:Arial,sans-serif;color:#352b37\">"
        "<div style=\"max-width:560px;margin:24px auto;padding:28px\">"
        "<img src=\"cid:avenra-logo\" alt=\"Avenra\" width=\"190\">"
        "<h1>Welcome to Avenra</h1>"
        "<p>Your organisation has invited you to its staff workspace.</p>"
        "<p>Create your password and activate your account using this link:</p>"
        + (f"<p><a href=\"{escape(link, quote=True)}\">Set up your account</a></p>" if link else "")
        + "<p>This invitation expires in 24 hours and works once. "
        "If you were not expecting it, contact your organisation.</p>"
        "</div></body></html>"
    )
    message.add_alternative(html_body, subtype="html")

    logo = Path(__file__).resolve().parents[2] / "static" / "images" / "avenra-logo.png"
    if logo.is_file():
        message.get_payload()[-1].add_related(
            logo.read_bytes(),
            maintype="image",
            subtype="png",
            cid="<avenra-logo>",
            filename="avenra-logo.png",
        )
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
