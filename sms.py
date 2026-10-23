"""Trusted-contact SMS / push notification dispatcher for Stage 2.

In a crisis, one tap alerts both the verified responder dashboard.js AND the trusted contacts the survivor chose in advance

Configuration (all optional; falls back to simulated SMS gateway for demos):
  SMS_WEBHOOK_URL      POST JSON {"to", "name", "message", "case_code"} to any SMS gateway or webhook
  TELEGRAM_BOT_TOKEN   Optional Telegram bot stand-in (with TELEGRAM_CHAT_ID)
"""
import json
import os
import urllib.request
import urllib.error
from flask import current_app, has_app_context


def build_message(case_code, lat, lng, client_ts):
    """Build a concise, plain-text emergency SMS under 160 characters."""
    if lat is not None and lng is not None:
        loc_part = f"Location: https://maps.google.com/?q={lat:.5f},{lng:.5f}"
    else:
        loc_part = "Location unavailable."
    time_part = f" ({client_ts[11:16]} UTC)" if isinstance(client_ts, str) and len(client_ts) >= 16 else ""
    return f"Avenra Alert [{case_code}]{time_part}: Your trusted contact requested urgent check-in. {loc_part}"


def send_single(name, phone, message, case_code):
    """Send one message via configured gateway or simulated demo SMS."""
    if has_app_context() and current_app.config.get('EVALUATION_MODE'):
        return {'channel': 'evaluation_disabled', 'ok': False}
    webhook_url = os.environ.get("SMS_WEBHOOK_URL", "").strip()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if webhook_url:
        try:
            body = json.dumps({
                "to": phone,
                "name": name,
                "message": message,
                "case_code": case_code,
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return {"name": name, "phone": phone, "channel": "webhook_sms", "ok": 200 <= resp.status < 300}
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

    if tg_token and tg_chat:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            body = json.dumps({
                "chat_id": tg_chat,
                "text": f"[SMS -> {name} ({phone})]\n{message}",
            }).encode("utf-8")
            req = urllib.request.Request(
                tg_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return {"name": name, "phone": phone, "channel": "telegram_standin", "ok": 200 <= resp.status < 300}
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

    # Default demo mode: simulated SMS gateway
    return {"channel": "simulation_or_failed", "ok": False}


def notify_contacts(conn, survivor, alert_id, lat=None, lng=None, client_ts=None):
    """Notify all trusted contacts for `survivor` and return delivery results."""
    rows = conn.execute(
        "SELECT name, phone FROM contacts WHERE user_id = ? ORDER BY id",
        (survivor["id"],),
    ).fetchall()
    if not rows:
        return []

    msg = build_message(survivor["case_code"], lat, lng, client_ts)
    results = []
    for r in rows:
        res = send_single(r["name"], r["phone"], msg, survivor["case_code"])
        results.append(res)
    return results
