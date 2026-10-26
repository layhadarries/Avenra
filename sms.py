"""Message formatting and disabled legacy synchronous notification compatibility.

Actual dispatch belongs exclusively to authenticated, explicit outbox workers.
Old webhook/Telegram environment settings never enable a fallback send.
"""
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
    """Legacy callers receive a truthful disabled result, never contact details."""
    if has_app_context() and current_app.config.get('EVALUATION_MODE'):
        return {'channel': 'evaluation_disabled', 'ok': False}
    return {'channel':'legacy_disabled','ok':False}


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
