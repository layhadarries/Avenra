"""Deterministic public-weather checks. All external providers are mocked."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect
from stage0_browser import main


def viewing_time(is_day=1):
    return datetime.now(timezone(timedelta(hours=2))).replace(hour=12 if is_day else 22, minute=0, second=0, microsecond=0)


def forecast(code=2, is_day=1):
    local = viewing_time(is_day)
    now = local.astimezone(timezone.utc)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    days = [int((midnight + timedelta(days=index)).timestamp()) for index in range(7)]
    hour = int(now.replace(minute=0, second=0, microsecond=0).timestamp())
    return {
        'timezone': 'Africa/Johannesburg',
        'current': {'time': int(now.timestamp()), 'temperature_2m': 23.4, 'apparent_temperature': 24.6,
                    'relative_humidity_2m': 64, 'is_day': is_day, 'weather_code': code,
                    'wind_speed_10m': 12.3, 'wind_direction_10m': 225, 'wind_gusts_10m': 21.7},
        'hourly': {'time': [hour + index * 3600 for index in range(24)],
                   'temperature_2m': [23 - index % 7 for index in range(24)],
                   'weather_code': [code] * 24, 'is_day': [is_day] * 24,
                   'precipitation_probability': [0, 0, 20, 40, 70, 20] * 4},
        'daily': {'time': days, 'temperature_2m_min': [14, 13, 15, 14, 16, 17, 15],
                  'temperature_2m_max': [25, 26, 24, 27, 28, 25, 24],
                  'weather_code': [code, 0, 61, 3, 0, 2, 3], 'precipitation_probability_max': [40, 0, 70, 20, 0, 10, 10],
                  'uv_index_max': [6.4] * 7, 'sunrise': [day + 6 * 3600 for day in days],
                  'sunset': [day + 19 * 3600 for day in days]},
    }


def providers(context, state, calls):
    def route(request):
        url = request.request.url
        calls.append(url)
        if urlsplit(url).hostname == 'api.open-meteo.com':
            if state.get('fail'):
                request.fulfill(status=503, content_type='application/json', body='{}')
            else:
                request.fulfill(content_type='application/json', body=json.dumps(state['forecast']))
        elif 'api.bigdatacloud.net/' in url:
            request.fulfill(content_type='application/json', body=json.dumps({
                'lookupSource': 'reverseGeocoding', 'locality': 'Gardens', 'city': 'Cape Town',
                'countryName': 'South Africa', 'principalSubdivision': 'Western Cape',
            }))
        else:
            request.fulfill(content_type='application/json', body=json.dumps({'results': [{
                'name': 'Pretoria', 'latitude': -25.7479, 'longitude': 28.2293,
                'admin1': 'Gauteng', 'country': 'South Africa',
            }]}))
    for pattern in ('https://api.open-meteo.com/**', 'https://api.bigdatacloud.net/**', 'https://geocoding-api.open-meteo.com/**'):
        context.route(pattern, route)


def screenshot(page, name):
    if os.environ.get('AVENRA_SCREENSHOT_DIR'):
        page.screenshot(path=str(Path(os.environ['AVENRA_SCREENSHOT_DIR']) / (name + '.png')), full_page=True)


def exercise(page, context, base, env):
    weather = context.browser.new_context(viewport={'width': 390, 'height': 844},
        geolocation={'latitude': -33.935123, 'longitude': 18.409876}, permissions=['geolocation'])
    state, calls, errors = {'forecast': forecast()}, [], []
    providers(weather, state, calls)
    try:
        screen = weather.new_page()
        screen.clock.set_fixed_time(viewing_time())
        screen.on('pageerror', lambda error: errors.append(str(error)))
        screen.goto(base + '/survivor/cover.html')
        expect(screen.locator('#cv-place')).to_have_text('Gardens')
        expect(screen.locator('#cv-temp')).to_have_text('23°')
        expect(screen.locator('#cv-desc')).to_have_text('Partly cloudy')
        expect(screen.locator('#cv-feels')).to_have_text('25°')
        expect(screen.locator('#cv-hum')).to_have_text('64%')
        expect(screen.locator('#cv-wind')).to_have_text('SW 12 km/h')
        expect(screen.locator('#cv-sun')).to_have_text('06:00 / 19:00')
        assert screen.locator('.cv-hour').count() == 24
        assert screen.locator('#cv-days li').count() == 7
        assert screen.locator('[data-thursday="1"]').count() == 1
        assert screen.locator('.cv-area-chip').count() == 0
        assert screen.locator('body').get_attribute('data-sky') == 'clear'
        assert screen.locator('.sky-sun').is_visible()
        assert not screen.locator('.sky-stars').is_visible()
        assert screen.locator('.cv-sky-scene').evaluate("el => getComputedStyle(el).pointerEvents") == 'none'
        query = parse_qs(urlsplit(next(url for url in calls if 'api.open-meteo.com/' in url)).query)
        assert query['latitude'] == ['-33.94'] and query['longitude'] == ['18.41']
        reverse = parse_qs(urlsplit(next(url for url in calls if 'api.bigdatacloud.net/' in url)).query)
        assert reverse['latitude'] == ['-33.935'] and reverse['longitude'] == ['18.410']
        for width in (320, 390, 1280):
            screen.set_viewport_size({'width': width, 'height': 844})
            assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            screenshot(screen, f'weather-clear-{width}')
        screen.set_viewport_size({'width': 390, 'height': 844})
        initial_count = len(calls)
        screen.reload()
        expect(screen.locator('#cv-temp')).to_have_text('23°')
        expect(screen.locator('#cv-place')).to_have_text('Gardens')
        screen.wait_for_function("document.getElementById('cv-weather-status').textContent === ''")
        assert len(calls) == initial_count, 'Fresh forecasts/names must be reused'
        screen.wait_for_function('navigator.serviceWorker.controller !== null')
        weather.set_offline(True)
        screen.reload()
        expect(screen.locator('#cv-weather-status')).to_contain_text('Offline')
        expect(screen.locator('#cv-temp')).to_have_text('23°')
        assert 'downloaded' in screen.locator('#cv-foot').inner_text()
        # Hidden entry remains usable without weather/network access.
        screen.locator('[data-thursday="1"]').click()
        expect(screen.locator('#cv-modal')).to_be_visible()
        screen.locator('#cv-modal-close').click()
        weather.set_offline(False)
        for code, day, expected in ((3, 1, 'cloud'), (63, 1, 'rain'), (0, 0, 'night')):
            screen.clock.set_fixed_time(viewing_time(day))
            state['forecast'] = forecast(code, day)
            screen.locator('#cv-refresh').click()
            expect(screen.locator('body')).to_have_attribute('data-sky', expected)
            if expected == 'cloud':
                assert screen.locator('.sky-clouds').is_visible()
                assert not screen.locator('.sky-moon').is_visible()
            elif expected == 'rain':
                assert screen.locator('.sky-rain').is_visible()
                assert not screen.locator('.sky-stars').is_visible()
            else:
                assert screen.locator('.sky-moon').is_visible()
                assert screen.locator('.sky-stars').is_visible()
                assert not screen.locator('.sky-sun').is_visible()
            screenshot(screen, 'weather-' + expected)
        # A night observation must not leave the sky dark when viewed next in daylight.
        weather.set_offline(True)
        screen.clock.set_fixed_time(viewing_time(1) + timedelta(days=1))
        screen.reload()
        expect(screen.locator('body')).to_have_attribute('data-sky', 'clear')
        assert screen.locator('.sky-sun').is_visible()
        assert not screen.locator('.sky-moon').is_visible()
        weather.set_offline(False)
        state['fail'] = True
        screen.locator('#cv-refresh').click()
        expect(screen.locator('#cv-weather-status')).to_contain_text('showing saved weather')
        expect(screen.locator('#cv-temp')).to_have_text('23°')
        # Search only submits on demand; selecting a new failed location must not mislabel the old weather.
        screen.locator('#cv-loc-btn').click()
        screen.locator('#cv-search-input').fill('Pretoria')
        search_count = len([url for url in calls if 'geocoding-api' in url])
        assert search_count == 0
        screen.locator('#cv-search-submit').click()
        screen.locator('#cv-search-results button').first.click()
        expect(screen.locator('#cv-place')).to_have_text('Pretoria')
        expect(screen.locator('#cv-temp')).to_have_text('—°')
        expect(screen.locator('#cv-weather-status')).to_contain_text('unavailable')
        assert len([url for url in calls if 'api.bigdatacloud.net' in url]) == 1, 'No reverse lookup of manual or saved coordinates'
        # Real zero readings are not treated as missing, and missing data is never invented.
        state['fail'] = False
        screen.clock.set_fixed_time(viewing_time(1))
        state['forecast'] = forecast(71, 1)
        state['forecast']['current'].update(temperature_2m=0, apparent_temperature=None, relative_humidity_2m=0)
        state['forecast']['daily'].update(sunrise=[None]*7, sunset=[None]*7, uv_index_max=[None]*7, precipitation_probability_max=[None]*7)
        screen.locator('#cv-refresh').click()
        expect(screen.locator('#cv-temp')).to_have_text('0°')
        expect(screen.locator('#cv-desc')).to_have_text('Snow')
        assert screen.locator('.sky-snow').is_visible()
        expect(screen.locator('#cv-feels')).to_have_text('—°')
        expect(screen.locator('#cv-hum')).to_have_text('0%')
        expect(screen.locator('#cv-rain')).to_have_text('—')
        expect(screen.locator('#cv-sun')).to_have_text('— / —')
        state['forecast']['current']['temperature_2m'] = None
        screen.locator('#cv-refresh').click()
        expect(screen.locator('#cv-weather-status')).to_contain_text('showing saved weather')
        expect(screen.locator('#cv-temp')).to_have_text('0°')
        screen.evaluate("localStorage.setItem('cs_pin_hash', 'preserve-screen-pin')")
        screen.locator('.cv-data-info summary').click()
        screen.locator('#cv-forget').click()
        assert screen.evaluate("localStorage.getItem('cs_pin_hash')") == 'preserve-screen-pin'
        assert screen.evaluate("localStorage.getItem('cs_weather_forecast_v1')") is None
        assert not errors, errors
    finally:
        weather.close()

    boundary = context.browser.new_context(viewport={'width':390,'height':844},
        geolocation={'latitude':-33.935123,'longitude':18.409876},permissions=['geolocation'])
    boundary_calls = []
    providers(boundary, {'forecast':forecast(0,1)}, boundary_calls)
    try:
        screen = boundary.new_page()
        screen.clock.install(time=viewing_time().replace(hour=18,minute=59,second=50))
        screen.goto(base + '/survivor/cover.html')
        expect(screen.locator('#cv-temp')).to_have_text('23°')
        expect(screen.locator('#cv-place')).to_have_text('Gardens')
        assert screen.locator('.sky-sun').is_visible()
        before = len(boundary_calls)
        screen.clock.fast_forward(12000)
        expect(screen.locator('body')).to_have_attribute('data-sky','night')
        assert screen.locator('.sky-moon').is_visible()
        assert screen.locator('.sky-stars').is_visible()
        assert len(boundary_calls) == before, 'Sunset scene changes must not make extra provider requests'
        screen.locator('[data-thursday="1"]').click()
        expect(screen.locator('#cv-modal')).to_be_visible()
    finally:
        boundary.close()

    denied = context.browser.new_context(viewport={'width': 320, 'height': 740})
    calls = []
    providers(denied, {'forecast': forecast()}, calls)
    denied.add_init_script('''(() => {
        navigator.geolocation.getCurrentPosition = (_, fail) => {
            sessionStorage.setItem('fixture-gps-count', String(Number(sessionStorage.getItem('fixture-gps-count') || 0) + 1));
            fail({code:1});
        };
        navigator.permissions.query = async () => ({state:'denied'});
    })();''')
    try:
        screen = denied.new_page()
        screen.goto(base + '/survivor/cover.html')
        expect(screen.locator('#cv-location-message')).to_contain_text('Location access is off')
        expect(screen.locator('#cv-temp')).to_have_text('—°')
        assert screen.locator('[data-thursday="1"]').count() == 1
        screen.reload()
        assert screen.evaluate("sessionStorage.getItem('fixture-gps-count')") == '1'
        assert calls == [], 'Denied permission must not trigger IP-based location or invented weather'
        screenshot(screen, 'weather-location-denied')
        screen.locator('#cv-search-open').click()
        screen.locator('#cv-search-input').fill('Pretoria')
        screen.locator('#cv-search-submit').click()
        screen.locator('#cv-search-results button').first.click()
        expect(screen.locator('#cv-place')).to_have_text('Pretoria')
        expect(screen.locator('#cv-temp')).to_have_text('23°')
        assert not any('bigdatacloud' in url for url in calls)
        screen.reload()
        expect(screen.locator('#cv-place')).to_have_text('Pretoria')
        assert screen.evaluate("sessionStorage.getItem('fixture-gps-count')") == '1', 'Manual choice should survive reopening'
    finally:
        denied.close()
    page.goto(base + '/dashboard')
    print('PASS: real-data rendering, GPS locality, rounded coordinates, day/night/rain/cloud layouts, fresh/offline caching, denied permission, search, hidden entry and scoped forgetting.')


if __name__ == '__main__':
    main(staff_check=exercise)
