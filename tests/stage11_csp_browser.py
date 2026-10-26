"""CSP execution checks against an isolated fixture server, no external script."""
from playwright.sync_api import expect
from stage0_browser import main, wait_for_async


def exercise(page,staff,base,env):
    phone=staff.browser.new_context()
    try:
        screen=phone.new_page()
        screen.goto(base+'/survivor/')
        screen.evaluate("""()=>{
          window.stage11Violations=[];
          document.addEventListener('securitypolicyviolation',e=>stage11Violations.push(e.effectiveDirective));
          const script=document.createElement('script');
          script.textContent='window.stage11Injected=true';document.body.append(script);
          const button=document.createElement('button');button.id='injected-probe';
          button.setAttribute('onclick','window.stage11Handler=true');document.body.append(button);button.click();
        }""")
        wait_for_async(screen,"stage11Violations.includes('script-src-elem') && stage11Violations.includes('script-src-attr')")
        assert screen.evaluate('window.stage11Injected !== true && window.stage11Handler !== true')
        screen.locator('[data-nav="more"]').click()
        expect(screen.get_by_role('heading',name='Your settings')).to_be_visible()
        screen.goto(base+'/survivor/help.html')
        screen.get_by_role('button',name='Diary',exact=True).click()
        screen.wait_for_url('**/diary.html')
        screen.get_by_role('button',name='Find help',exact=True).click()
        screen.wait_for_url('**/help.html')
        screen.get_by_role('button',name='Quick exit',exact=True).click()
        screen.wait_for_url('**/cover.html')
        screen.goto(base+'/survivor/setup.html')
        expect(screen.get_by_role('button',name='Add contact',exact=True)).to_be_visible()
        screen.get_by_role('button',name='Quick exit',exact=True).click()
        screen.wait_for_url('**/cover.html')
    finally: phone.close()
    print('PASS: unauthorized inline scripts/handlers blocked; trusted PWA scripts, navigation and Quick Exit work under CSP.')


if __name__=='__main__': main(exercise)
