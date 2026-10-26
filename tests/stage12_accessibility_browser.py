"""Automated accessibility/reflow probes, not independent or physical-phone review."""
import os
from pathlib import Path
from playwright.sync_api import expect
from stage0_browser import main,wait_for_async
from stage9_vault_browser import unlock

AXE=Path(os.environ.get('AVENRA_AXE_SOURCE','tools/a11y/node_modules/axe-core/axe.min.js'))


def exercise(page,staff,base,env):
    if not AXE.is_file(): raise AssertionError('Install pinned fixture tooling with npm ci --prefix tools/a11y --ignore-scripts')
    source=AXE.read_text(); scans=0; manual=set()
    phone=staff.browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
    try:
        screen=phone.new_page()
        def audit(name,theme,width):
            nonlocal scans
            # CDP instruments the fixture page only; app CSP remains enforced.
            screen.evaluate(source)
            assert screen.evaluate('axe.version')=='4.14.0'
            result=screen.evaluate("""async()=>{
              const result=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
              return {violations:result.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})),
                incomplete:result.incomplete.map(v=>v.id)};
            }""")
            assert not result['violations'],(name,theme,width,result['violations'])
            manual.update(result['incomplete']); scans+=1
        for theme in ('light','dark'):
            screen.emulate_media(color_scheme=theme)
            for width in (320,390,768):
                screen.set_viewport_size({'width':width,'height':844})
                for name in ('index','help','diary','privacy','setup','device','install','enroll'):
                    screen.goto(base+'/survivor/'+name+'.html')
                    if name=='privacy': expect(screen.locator('#consent-location_sharing')).to_be_enabled()
                    audit(name,theme,width)
                    assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth'),(name,theme,width)
                screen.goto(base+'/survivor/diary.html'); unlock(screen)
                expect(screen.locator('#diary-private')).to_be_visible()
                audit('unlocked-diary',theme,width)
        screen.goto(base+'/survivor/')
        # Reflow with enlarged text and WCAG text-spacing overrides.
        screen.set_viewport_size({'width':320,'height':844})
        screen.evaluate("""()=>{
          document.documentElement.style.fontSize='200%';
          const style=document.createElement('style');
          style.textContent='* {line-height:1.5 !important;letter-spacing:.12em !important;word-spacing:.16em !important;}';
          document.head.append(style);
        }""")
        assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Enlarged/space-adjusted text must reflow'
        screen.goto(base+'/survivor/privacy.html')
        screen.locator('#consent-location_sharing').focus()
        assert screen.locator('#consent-location_sharing').evaluate('(el)=>document.activeElement===el')
        # Merely focusing a privacy control cannot change its permission.
        initial=screen.locator('#consent-location_sharing').is_checked()
        screen.keyboard.press('Tab')
        assert screen.locator('#consent-location_sharing').is_checked()==initial
        screen.get_by_role('button',name='Quick exit',exact=True).focus()
        screen.keyboard.press('Enter'); screen.wait_for_url('**/cover.html')
    finally: phone.close()
    print('PASS:',scans,'axe-core WCAG-tag scans, light/dark 320/390/768px, enlarged text/reflow, keyboard consent and Quick Exit.')
    print('MANUAL REVIEW STILL REQUIRED: axe incomplete rule IDs:',','.join(sorted(manual)) or 'none reported')


if __name__=='__main__': main(exercise)
