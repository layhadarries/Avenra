"""Audit browser checks using isolated fictional data."""
import sqlite3
from contextlib import closing

from playwright.sync_api import expect
from stage0_browser import main


def check_audit(page, context, base, env):
    marker = "stage4-browser-event"
    unsafe_text = '<img src=x onerror="window.auditXss=true">'

    # This is the temporary database created by the browser harness.
    with closing(sqlite3.connect(env["DATABASE_PATH"])) as conn:
        with conn:
            staff_id = conn.execute(
                """
                SELECT id FROM users
                WHERE role = 'responder'
                ORDER BY id LIMIT 1
                """
            ).fetchone()[0]

            case_code = conn.execute(
                """
                SELECT case_code FROM users
                WHERE role = 'survivor'
                ORDER BY id LIMIT 1
                """
            ).fetchone()[0]

            for number in range(28):
                detail = f"{marker}-{number}"
                if number == 27:
                    detail += " " + unsafe_text

                conn.execute(
                    """
                    INSERT INTO audit_log
                        (actor, action, case_code, detail)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        f"user:{staff_id}",
                        "consent_revoked",
                        case_code,
                        detail,
                    ),
                )

            conn.execute(
                """
                INSERT INTO audit_log
                    (actor, action, case_code, detail)
                VALUES (?, ?, ?, ?)
                """,
                (
                    f"user:{staff_id}",
                    "consent_revoked",
                    "UNASSIGNED-CASE",
                    "FOREIGN-AUDIT-EVENT",
                ),
            )

    page.goto(base + "/audit-log")
    rows = page.locator("#audit-rows")
    status = page.locator("#audit-status")

    expect(rows).to_contain_text(marker, timeout=12000)
    expect(rows).not_to_contain_text("FOREIGN-AUDIT-EVENT")

    page.get_by_label("Case code", exact=True).fill(case_code)
    page.get_by_label("Event category", exact=True).select_option("consent")
    page.get_by_role("button", name="Apply filters", exact=True).click()

    expect(status).to_have_text("28 matching recorded event(s).")
    expect(rows.locator("tr")).to_have_count(25)
    expect(page.locator("#audit-page")).to_have_text("Page 1")

    # HTML-like audit content must remain text.
    expect(rows).to_contain_text(unsafe_text)
    expect(rows.locator("img")).to_have_count(0)
    assert page.evaluate("window.auditXss === undefined")

    page.get_by_role("button", name="Next", exact=True).click()
    expect(page.locator("#audit-page")).to_have_text("Page 2")
    expect(rows.locator("tr")).to_have_count(3)
    expect(page.get_by_role("button", name="Next", exact=True)).to_be_disabled()

    page.get_by_role("button", name="Previous", exact=True).click()
    expect(page.locator("#audit-page")).to_have_text("Page 1")
    expect(rows.locator("tr")).to_have_count(25)

    # A filter must not grant access to another case.
    page.get_by_label("Case code", exact=True).fill("UNASSIGNED-CASE")
    page.get_by_role("button", name="Apply filters", exact=True).click()

    expect(rows.locator("tr")).to_have_count(0)
    expect(status).to_have_text(
        "No recorded events match these filters."
    )

    page.get_by_label("Case code", exact=True).fill(case_code)
    page.get_by_role("button", name="Apply filters", exact=True).click()
    expect(rows.locator("tr")).to_have_count(25)

    # Failed refreshes must clear old sensitive results.
    def block_audit(route):
        route.abort()

    page.route("**/api/audit-log?*", block_audit)
    page.get_by_role("button", name="Refresh", exact=True).click()

    expect(status).to_contain_text("could not be loaded")
    expect(rows.locator("tr")).to_have_count(0)

    page.unroute("**/api/audit-log?*", block_audit)
    page.get_by_role("button", name="Refresh", exact=True).click()
    expect(rows.locator("tr")).to_have_count(25)

    # Case-grant withdrawal must remove the case's events automatically.
    with closing(sqlite3.connect(env["DATABASE_PATH"])) as conn:
        with conn:
            conn.execute(
                "DELETE FROM case_access WHERE staff_id = ?",
                (staff_id,),
            )

    expect(rows).not_to_contain_text(marker, timeout=15000)
    expect(rows).not_to_contain_text("FOREIGN-AUDIT-EVENT")

    # Leave an accessible page for the remaining shared checks.
    page.goto(base + "/dashboard")
    expect(
        page.get_by_role("link", name="Shelters", exact=True)
    ).to_be_visible()

    print(
        "PASS: audit filters, pagination, text-safe rendering, "
        "failed-refresh clearing and revoked case access."
    )


if __name__ == "__main__":
    main(staff_check=check_audit)