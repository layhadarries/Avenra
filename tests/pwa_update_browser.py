"""Upgrade a stale offline shell with an old tab open; preserve pending data."""
from pathlib import Path

from playwright.sync_api import expect
from stage0_browser import main, wait_for_async


def exercise(page, context, base, env):
    phone = context.browser.new_context(viewport={'width': 390, 'height': 844})
    try:
        screen = phone.new_page()
        screen.goto(base + '/survivor/update.html')
        source = (Path(__file__).resolve().parents[1] / 'static/survivor/service-worker.js').read_text()
        import re
        current_cache = re.search(r"const CACHE_NAME = '([^']+)'", source).group(1)
        legacy = source.replace(current_cache, 'clear-sky-shell-v13')
        phone.route('**/survivor/service-worker.js', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=legacy,
            headers={'Service-Worker-Allowed': '/survivor/'}))
        screen.evaluate("navigator.serviceWorker.register('/survivor/service-worker.js', {scope:'/survivor/'})")
        wait_for_async(screen,'navigator.serviceWorker.controller !== null')
        screen.evaluate('''async () => {
            const cache = await caches.open('clear-sky-shell-v13');
            await cache.put('/survivor/', new Response('<h1>Old cached screens</h1>', {
                headers: {'Content-Type': 'text/html'}
            }));
            localStorage.setItem('clear-sky-alert-owner-v1', '123');
            await new Promise((resolve, reject) => {
                const request = indexedDB.open('clear-sky-queue', 1);
                request.onupgradeneeded = () => request.result.createObjectStore('alerts', {keyPath:'client_id'});
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    const db = request.result;
                    const tx = db.transaction('alerts', 'readwrite');
                    tx.objectStore('alerts').put({client_id:'saved-before-update', owner_id:123});
                    tx.oncomplete = () => {db.close(); resolve();};
                    tx.onerror = () => reject(tx.error);
                };
            });
        }''')
        old_tab = phone.new_page()
        old_tab.goto(base + '/survivor/')
        expect(old_tab.get_by_role('heading', name='Old cached screens')).to_be_visible()
        phone.unroute('**/survivor/service-worker.js')
        screen.get_by_role('button', name='Update app files', exact=True).click()
        expect(screen.locator('#open-app')).to_be_visible(timeout=45000)
        expect(old_tab.get_by_role('heading', name='Old cached screens')).to_be_visible()
        assert screen.evaluate("localStorage.getItem('clear-sky-alert-owner-v1')") == '123'
        assert screen.evaluate('''() => new Promise((resolve, reject) => {
            const request = indexedDB.open('clear-sky-queue', 1);
            request.onerror = () => reject(request.error);
            request.onsuccess = () => {
                const db = request.result;
                const tx = db.transaction('alerts', 'readonly');
                const saved = tx.objectStore('alerts').get('saved-before-update');
                saved.onsuccess = () => resolve(saved.result.owner_id);
                tx.oncomplete = () => db.close();
            };
        })''') == 123
        assert await_cache_version(screen) == [current_cache]
        screen.locator('#open-app').click()
        expect(screen.get_by_role('heading', name='Get support', exact=True)).to_be_visible()
    finally:
        phone.close()
    page.goto(base + '/dashboard')
    print('PASS: stale shell updated with another tab open; pending alert and owner retained; no forced reload.')


def await_cache_version(page):
    return page.evaluate('caches.keys()')


if __name__ == '__main__':
    main(staff_check=exercise)
