"""Synthetic browser tests for persistent alert ownership."""
from playwright.sync_api import expect
from stage0_browser import main


def exercise(page, context, base, env):
    page.goto(base + "/devices")
    page.get_by_role(
        "button", name="Create private pairing link", exact=True
    ).click()
    link = page.locator("#device-invite-link")
    expect(link).to_be_visible()
    invitation = link.get_attribute("href")

    phone_context = context.browser.new_context()
    try:
        phone = phone_context.new_page()
        phone.goto(invitation)
        phone.get_by_role(
            "button", name="Connect my device", exact=True
        ).click()
        expect(phone.locator("#status")).to_contain_text(
            "Device connected"
        )

        owner = phone_context.request.get(
            base + "/api/device"
        ).json()["account_id"]

        # Keep records local while checking their saved ownership.
        phone.route("**/api/alerts", lambda route: route.abort())
        phone.goto(base + "/survivor/")
        phone.wait_for_function("Boolean(window.CWQueue)")

        async_read = """async () => {
            return new Promise((resolve, reject) => {
                const request = indexedDB.open('clear-sky-queue', 1);
                request.onerror = () => reject(new Error('DB failed'));
                request.onsuccess = () => {
                    const db = request.result;
                    const tx = db.transaction('alerts', 'readonly');
                    let items;
                    tx.objectStore('alerts').getAll().onsuccess =
                        event => { items = event.target.result; };
                    tx.oncomplete = () => {
                        db.close();
                        resolve(items);
                    };
                    tx.onerror = tx.onabort = () => {
                        db.close();
                        reject(new Error('Read failed'));
                    };
                };
            });
        }"""

        phone.evaluate(
            "() => CWQueue.queueAlert({client_id:'owner-online'})"
        )
        records = phone.evaluate(async_read)
        online = next(
            item for item in records
            if item["client_id"] == "owner-online"
        )
        assert online.get("owner_id") == owner, (
            "New alerts must be bound when saved"
        )

        phone_context.set_offline(True)
        phone.evaluate(
            "() => CWQueue.queueAlert({client_id:'owner-offline'})"
        )
        records = phone.evaluate(async_read)
        offline = next(
            item for item in records
            if item["client_id"] == "owner-offline"
        )
        assert offline.get("owner_id") == owner, (
            "Offline capture must retain the established identity"
        )

        phone.evaluate(
            """async owner => {
                const db = await new Promise((resolve, reject) => {
                    const r = indexedDB.open('clear-sky-queue', 1);
                    r.onsuccess = () => resolve(r.result);
                    r.onerror = () => reject(new Error('DB failed'));
                });
                await new Promise((resolve, reject) => {
                    const tx = db.transaction('alerts', 'readwrite');
                    const store = tx.objectStore('alerts');
                    store.put({client_id:'legacy-unbound'});
                    store.put({
                        client_id:'foreign-owner',
                        owner_id:owner + 100000
                    });
                    tx.oncomplete = resolve;
                    tx.onerror = tx.onabort =
                        () => reject(new Error('Write failed'));
                });
                db.close();
            }""",
            owner,
        )

        sent = []

        def record_request(request):
            if (
                request.method == "POST"
                and request.url == base + "/api/alerts"
            ):
                sent.append((
                    request.post_data_json["client_id"],
                    request.headers.get("x-queue-owner"),
                ))

        phone.on("request", record_request)
        phone.unroute("**/api/alerts")
        phone_context.set_offline(False)
        phone.evaluate("() => CWQueue.flushQueue()")

        records = phone.evaluate(async_read)
        remaining = {item["client_id"]: item for item in records}

        assert "owner-online" not in remaining
        assert "owner-offline" not in remaining
        assert "legacy-unbound" in remaining
        assert remaining["foreign-owner"]["owner_id"] == owner + 100000

        assert {client_id for client_id, _ in sent} == {
            "owner-online", "owner-offline"
        }
        assert all(header == str(owner) for _, header in sent)

    finally:
        phone_context.close()

    page.goto(base + "/dashboard")
    print(
        "PASS: online/offline owner binding, matching upload headers, "
        "and preservation of blocked legacy/foreign alerts."
    )


if __name__ == "__main__":
    main(staff_check=exercise)