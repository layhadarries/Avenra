"""Local fictional-data checks for the lightweight PWA design and offline CSS."""
import os
from pathlib import Path

from playwright.sync_api import expect
from stage0_browser import main


def exercise(page, context, base, env):
    phone = context.browser.new_context(viewport={'width': 390, 'height': 844})
    errors = []
    try:
        screen = phone.new_page()
        screen.on('pageerror', lambda error: errors.append(str(error)))
        for theme in ('light', 'dark'):
            screen.emulate_media(color_scheme=theme)
            for width in (320, 390):
                screen.set_viewport_size({'width': width, 'height': 844})
                for name in ('index', 'help', 'diary', 'privacy', 'setup', 'device', 'enroll', 'install'):
                    screen.goto(f'{base}/survivor/{name}.html')
                    assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width, theme)
                    if name in ('index', 'help', 'diary', 'privacy', 'setup'):
                        assert screen.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == (
                            'rgb(245, 242, 235)' if theme == 'light' else 'rgb(28, 25, 30)'
                        ), (name, theme)
                        expect(screen.get_by_role('button', name='Quick exit', exact=True)).to_be_visible()
                        assert screen.locator('.quick-exit-pill').evaluate('(el) => el.getBoundingClientRect().height >= 44')
                    if os.environ.get('AVENRA_SCREENSHOT_DIR') and width == 390:
                        screen.screenshot(path=str(Path(os.environ['AVENRA_SCREENSHOT_DIR']) / f'pwa-{name}-{theme}.png'), full_page=True)

        # Explicit light overrides a dark device setting across all screens.
        screen.get_by_role('button', name='Switch to light theme', exact=True).click()
        for name in ('index', 'help', 'diary', 'privacy', 'setup', 'device', 'enroll', 'install', 'update'):
            screen.goto(f'{base}/survivor/{name}.html')
            expect(screen.get_by_role('button', name='Switch to dark theme', exact=True)).to_be_visible()
            assert screen.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(245, 242, 235)'
        # Explicit dark also overrides a light device and survives navigation/offline.
        screen.get_by_role('button', name='Switch to dark theme', exact=True).click()
        screen.emulate_media(color_scheme='light')
        assert screen.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(28, 25, 30)'
        screen.goto(base + '/survivor/#more')
        expect(screen.get_by_role('heading', name='Your settings')).to_be_visible()
        expect(screen.locator('.more-row[href="/survivor/device.html"]')).to_be_visible()
        screen.locator('[data-nav="home"]').click()
        expect(screen.locator('#view-ready')).to_be_visible()
        # The existing hold/countdown/undo flow must remain usable.
        screen.locator('#panic-btn').focus()
        screen.keyboard.down('Enter')
        expect(screen.locator('#view-countdown')).to_be_visible()
        screen.keyboard.up('Enter')
        screen.get_by_role('button', name='Undo', exact=True).click()
        expect(screen.locator('#view-ready')).to_be_visible()
        screen.wait_for_function('navigator.serviceWorker.controller !== null')
        phone.set_offline(True)
        for name in ('index', 'help', 'diary', 'privacy', 'setup', 'device', 'install'):
            screen.goto(f'{base}/survivor/{name}.html')
            assert screen.evaluate('document.styleSheets.length > 0'), name
            assert screen.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(28, 25, 30)', name
            expect(screen.get_by_role('button', name='Switch to light theme', exact=True)).to_be_visible()
        screen.get_by_role('button', name='Switch to light theme', exact=True).click()
        assert screen.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(245, 242, 235)'
        screen.goto(base + '/survivor/cover.html')
        assert screen.locator('#theme-toggle').count() == 0
        assert not errors, errors
    finally:
        phone.close()
    page.goto(base + '/dashboard')
    print('PASS: mobile light/dark layouts, Quick Exit targets, More navigation, alert undo, and offline styles.')


if __name__ == '__main__':
    main(staff_check=exercise)
