"""Weather GPS/search stays outside first-party alerts, diary and audit records."""
import sqlite3
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async
from stage9_vault_browser import unlock
from weather_browser import providers, forecast


def exercise(page, staff, base, env):
    phone = staff.browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True,
        geolocation={'latitude':-33.935123,'longitude':18.409876}, permissions=['geolocation'])
    calls, first_party = [], []
    providers(phone, {'forecast':forecast()}, calls)
    phone.on('request', lambda request: first_party.append(request.url+' '+(request.post_data or ''))
             if request.url.startswith(base+'/api/') else None)
    def snapshot():
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            return {table:conn.execute('SELECT * FROM '+table).fetchall()
                    for table in ('users','alerts','diary_entries','audit_log')}
    try:
        before = snapshot()
        p = phone.new_page(); p.goto(base+'/survivor/cover.html')
        expect(p.locator('#cv-place')).to_have_text('Gardens')
        p.locator('#cv-loc-btn').click(); p.locator('#cv-search-input').fill('Pretoria')
        p.locator('#cv-search-submit').click(); p.locator('#cv-search-results button').first.click()
        expect(p.locator('#cv-place')).to_have_text('Pretoria')
        assert snapshot() == before, 'Normal weather must not mutate cases, alerts, diary or audit'
        p.goto(base+'/survivor/')
        p.locator('#panic-btn').dispatch_event('pointerdown', {'pointerType':'touch'})
        expect(p.locator('#view-countdown')).to_be_visible()
        expect(p.locator('#view-sent')).to_be_visible(timeout=15000)
        p.goto(base+'/survivor/diary.html'); unlock(p)
        p.locator('#diary-note').fill('Fictional weather separation note')
        p.locator('#diary-save-btn').click()
        expect(p.locator('#diary-entries-list')).to_contain_text('Fictional weather separation note')
        wait_for_async(p, 'async()=> (await CWDiary.getQueuedItems()).length === 0')
        with sqlite3.connect(env['DATABASE_PATH']) as conn:
            alert = conn.execute('SELECT lat,lng,location_accuracy,location_recorded_at FROM alerts ORDER BY id DESC LIMIT 1').fetchone()
            assert alert == (None,None,None,None), 'HELP must not inherit weather GPS or manual coordinates'
            assert conn.execute("SELECT COUNT(*) FROM diary_entries WHERE note='Fictional weather separation note'").fetchone()[0] == 1
            audit = str(conn.execute('SELECT detail FROM audit_log').fetchall())
        for coordinate in ('-33.935','18.410','-33.94','18.41','-25.7479','28.2293'):
            assert coordinate not in '\n'.join(first_party), 'Weather coordinates leaked into a first-party API'
            assert coordinate not in audit, 'Weather coordinates leaked into staff audit detail'
        assert any('api.bigdatacloud.net' in url for url in calls)
        assert any('geocoding-api.open-meteo.com' in url for url in calls)
        print('PASS: real weather GPS/provider/search flow unchanged; no first-party coordinate transport or weather mutations; HELP/diary and audit stay separate.')
    finally:
        phone.close()


if __name__ == '__main__': main(exercise)
