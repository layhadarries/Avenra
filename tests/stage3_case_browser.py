"""Browser checks using an isolated, fictional evaluation database."""
import sqlite3
from contextlib import closing

from playwright.sync_api import expect
from stage0_browser import main


def check_case_workspace(page, context, base, env):
    credentials = {
        "X-Device-Token": env.get("DEVICE_TOKEN", "demo-device"),
    }

    # Change only the temporary database created by the browser harness.
    with closing(sqlite3.connect(env["DATABASE_PATH"])) as conn:
        with conn:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM shelters ORDER BY id"
                )
            ]
            assert len(ids) >= 3

            conn.execute("UPDATE shelters SET lat = NULL, lng = NULL")
            for shelter_id, latitude in zip(ids[:3], (0.1, 0.3, 0.6)):
                conn.execute(
                    "UPDATE shelters SET lat = ?, lng = 0 WHERE id = ?",
                    (latitude, shelter_id),
                )

    created = context.request.post(
        base + "/api/alerts",
        headers=credentials,
        data={
            "client_id": "stage3-case-browser",
            "lat": 0,
            "lng": 0,
        },
    )
    assert created.status == 201, created.text()
    receipt = created.json()

    page.goto(
        f"{base}/cases/{receipt['case_code']}"
        f"?alert_id={receipt['id']}"
    )

    results = page.locator("#nearby-services")
    status = page.locator("#nearby-status")

    expect(page.locator("#case-alert-select")).to_have_value(
        str(receipt["id"])
    )
    expect(results.locator("li")).to_have_count(1, timeout=12000)
    expect(results).to_contain_text("11.12 km")
    expect(results).to_contain_text("Contact to confirm")

    page.get_by_label("Search radius", exact=True).select_option("50")

    expect(results.locator("li")).to_have_count(2, timeout=12000)
    expect(results.locator("li").nth(0)).to_contain_text("11.12 km")
    expect(results.locator("li").nth(1)).to_contain_text("33.36 km")

    # Staff requests a referral from the first nearby-service result.
    first_service = results.locator("li").first

    with page.expect_response(
        lambda response:
        response.url == base + "/api/referrals"
        and response.request.method == "POST"
    ) as pending:
        first_service.get_by_role(
            "button",
            name="Request referral",
            exact=True,
        ).click()

    referral_response = pending.value
    assert referral_response.status == 201, referral_response.text()
    assert referral_response.request.header_value("x-csrftoken")

    referral = referral_response.json()["referral"]
    assert referral["alert_id"] == receipt["id"]
    assert referral["status"] == "sent"

    expect(page.locator("#referral-status")).to_contain_text(
        "Referral requested"
    )
    expect(page.locator("#referral-status")).to_contain_text(
        "does not confirm a place"
    )

    # Continue the handover through the staff Referrals page.
    page.goto(base + "/referrals")
    row = page.locator(
        f'tr[data-referral-id="{referral["id"]}"]'
    )

    with page.expect_response(
        lambda response:
        response.url ==
        f"{base}/api/referrals/{referral['id']}/status"
        and response.request.method == "POST"
    ) as accepted:
        row.get_by_role("button", name="Accept", exact=True).click()

    assert accepted.value.status == 200, accepted.value.text()
    assert accepted.value.request.header_value("x-csrftoken")
    assert accepted.value.json()["referral"]["status"] == "accepted"

    # Recording placement requires an explicit confirmation dialog.
    dialogs = []

    def confirm_placement(dialog):
        dialogs.append(dialog.message)
        dialog.accept()

    page.once("dialog", confirm_placement)

    with page.expect_response(
        lambda response:
        response.url ==
        f"{base}/api/referrals/{referral['id']}/status"
        and response.request.method == "POST"
    ) as placed:
        row.get_by_role(
            "button",
            name="Record confirmed placement",
            exact=True,
        ).click()

    assert dialogs, "Placement must require explicit confirmation"
    assert placed.value.status == 200, placed.value.text()
    assert placed.value.request.header_value("x-csrftoken")
    assert placed.value.json()["referral"]["status"] == "placed"

    expect(row.locator('[data-referral-status]')).to_have_text("Placed")
    expect(row.get_by_role("button")).to_have_count(0)

    # Create a second alert/referral to exercise the decline form.
    second_alert = context.request.post(
        base + "/api/alerts",
        headers=credentials,
        data={"client_id": "stage3-decline-browser"},
    )
    assert second_alert.status == 201, second_alert.text()

    csrf_token = page.locator(
        'meta[name="csrf-token"]'
    ).get_attribute("content")

    second_referral = context.request.post(
        base + "/api/referrals",
        headers={"X-CSRFToken": csrf_token},
        data={
            "alert_id": second_alert.json()["id"],
            "shelter_id": referral["shelter_id"],
        },
    )
    assert second_referral.status == 201, second_referral.text()
    decline_id = second_referral.json()["referral"]["id"]

    page.reload()
    decline_row = page.locator(
        f'tr[data-referral-id="{decline_id}"]'
    )
    reason = decline_row.get_by_label(
        "Reason for declining", exact=True
    )

    # An empty reason must be blocked by the form.
    decline_row.get_by_role(
        "button", name="Decline", exact=True
    ).click()
    assert reason.evaluate("(el) => el.validity.valueMissing")
    expect(
        decline_row.locator("[data-referral-status]")
    ).to_have_text("Sent")

    reason.fill("Service cannot assist this referral.")

    with page.expect_response(
        lambda response:
        response.url ==
        f"{base}/api/referrals/{decline_id}/status"
        and response.request.method == "POST"
    ) as declined:
        decline_row.get_by_role(
            "button", name="Decline", exact=True
        ).click()

    assert declined.value.status == 200, declined.value.text()
    assert declined.value.request.header_value("x-csrftoken")
    assert declined.value.json()["referral"]["status"] == "declined"

    expect(
        decline_row.locator("[data-referral-status]")
    ).to_have_text("Declined")
    expect(
        decline_row.locator("[data-referral-reason]")
    ).to_have_text("Service cannot assist this referral.")
    expect(decline_row.get_by_role("button")).to_have_count(0)

    # Return to the case for the existing consent/access checks.
    page.goto(
        f"{base}/cases/{receipt['case_code']}"
        f"?alert_id={receipt['id']}"
    )
    expect(results.locator("li")).to_have_count(1, timeout=12000)

    # No manual refresh: shared session checks must detect revocation.
    revoked = context.request.post(
        base + "/api/consents",
        headers=credentials,
        data={"item": "location_sharing", "active": False},
    )
    assert revoked.status == 200, revoked.text()

    expect(results.locator("li")).to_have_count(0, timeout=15000)
    expect(status).to_contain_text(
        "no usable, consented location",
        timeout=15000,
    )

    # Restore consent and verify normal lookup resumes after revalidation.
    restored = context.request.post(
        base + "/api/consents",
        headers=credentials,
        data={"item": "location_sharing", "active": True},
    )
    assert restored.status == 200, restored.text()

    expect(results.locator("li")).to_have_count(1, timeout=15000)

    # Removing the staff grant must also remove the case workspace.
    with closing(sqlite3.connect(env["DATABASE_PATH"])) as conn:
        with conn:
            conn.execute("DELETE FROM case_access")

    expect(page.locator("[data-case-view]")).to_have_count(
        0, timeout=15000
    )

    # Return to an accessible page for the remaining shared checks.
    page.goto(base + "/dashboard")
    expect(
        page.get_by_role("link", name="Shelters", exact=True)
    ).to_be_visible()

    print(
        "PASS: nearby lookup, radius change, consent revocation/restoration, "
        "and revoked case access."
    )


if __name__ == "__main__":
    main(staff_check=check_case_workspace)