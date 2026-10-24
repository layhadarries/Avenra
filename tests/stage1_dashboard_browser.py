"""Dashboard browser checks using isolated fictional test data."""
import sqlite3

from playwright.sync_api import expect
from stage0_browser import main


def check_dashboard(page, context, base, env):
    created = context.request.post(
        base + "/api/alerts",
        headers={
            "X-Device-Token": env.get("DEVICE_TOKEN", "demo-device"),
        },
        data={
            "client_id": "stage1-browser-alert",
            "lat": -33.9249,
            "lng": 18.4241,
            "location_accuracy": 35.5,
            "location_recorded_at": "2026-10-23T12:00:00Z",
        },
    )
    assert created.status == 201, created.text()
    alert_id = created.json()["id"]

    card = page.get_by_role(
        "article",
        name=f"Alert {alert_id}",
        exact=True,
    )
    expect(card).to_be_visible(timeout=12000)
    expect(card).to_contain_text("SP-1042")
    expect(card.get_by_text("New", exact=True)).to_be_visible()
    location_map = page.get_by_role("region", name="Alert locations", exact=True)
    expect(location_map).to_be_visible()

    marker = location_map.get_by_role("button", name=f"Reported location for alert {alert_id}", exact=True)
    accuracy = location_map.get_by_role("img", name=f"Accuracy radius for alert {alert_id}: 35.5 metres", exact=True)

    expect(marker).to_be_visible(timeout=12000)
    expect(accuracy).to_be_visible()

    with page.expect_response(
        lambda response:
        response.url == f"{base}/api/alerts/{alert_id}/acknowledge"
        and response.request.method == "POST"
    ) as pending:
        card.get_by_role(
            "button",
            name="Acknowledge",
            exact=True,
        ).click()

    response = pending.value
    assert response.status == 200, response.text()
    assert response.request.header_value("x-csrftoken")
    assert response.json()["status"] == "acknowledged"

    expect(
        card.get_by_text("Acknowledged", exact=True)
    ).to_be_visible()
    credentials = {
        "X-Device-Token": env.get("DEVICE_TOKEN", "demo-device"),
    }

    revoked = context.request.post(
        base + "/api/consents",
        headers=credentials,
        data={"item": "location_sharing", "active": False},
    )
    assert revoked.status == 200, revoked.text()

    expect(marker).to_have_count(0, timeout=12000)
    expect(accuracy).to_have_count(0, timeout=12000)
    expect(card).to_be_visible()

    restored = context.request.post(
        base + "/api/consents",
        headers=credentials,
        data={"item": "location_sharing", "active": True},
    )
    assert restored.status == 200, restored.text()

    expect(marker).to_be_visible(timeout=12000)
    expect(accuracy).to_be_visible()

    # This is the test fixture's temporary database.
    with sqlite3.connect(env["DATABASE_PATH"]) as conn:
        conn.execute("DELETE FROM case_access")

    expect(card).to_have_count(0, timeout=12000)
    expect(marker).to_have_count(0, timeout=12000)
    expect(accuracy).to_have_count(0, timeout=12000)

    print(
        "PASS: alert appears, acknowledgement uses CSRF, "
        "and revoked access clears the card."
    )


if __name__ == "__main__":
    main(staff_check=check_dashboard)