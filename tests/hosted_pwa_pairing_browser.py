"""Synthetic browser pairing; no email or hosted database is used."""
import uuid
from playwright.sync_api import expect
from stage0_browser import main


def exercise(page, context, base, env):
    page.goto(base+'/devices')
    page.get_by_role('button',name='Create private pairing link',exact=True).click()
    link=page.locator('#device-invite-link')
    expect(link).to_be_visible()
    pairing_url=link.get_attribute('href')
    phone_context=context.browser.new_context(viewport={'width':390,'height':844})
    try:
        phone=phone_context.new_page()
        errors=[]
        phone.on('pageerror',lambda error:errors.append(str(error)))
        phone.goto(pairing_url)
        assert '#' not in phone.url
        phone.get_by_role('button',name='Connect my device',exact=True).click()
        expect(phone.locator('#status')).to_contain_text('Device connected')
        assert 'avenra_device' not in phone.evaluate('document.cookie')
        status=phone_context.request.get(base+'/api/device')
        assert status.status==200
        result=phone.evaluate("""async id => {
          const r=await fetch('/api/alerts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_id:id})});
          return {status:r.status,body:await r.json()};
        }""",'pairing-browser-'+uuid.uuid4().hex)
        assert result['status']==201,result
        listing=context.request.get(base+'/api/alerts').json()
        assert any(item['id']==result['body']['id'] for item in listing['alerts'])
        phone.goto(base+'/survivor/install.html')
        expect(phone.get_by_role('heading',level=1)).to_be_visible()
        assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
    finally:
        phone_context.close()
    page.goto(base+'/dashboard')
    print('PASS: private pairing link, fragment removal, HttpOnly identity, individual alert reaches assigned dashboard, mobile install page.')

if __name__=='__main__':
    main(staff_check=exercise)
