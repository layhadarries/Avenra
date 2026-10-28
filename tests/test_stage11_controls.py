"""Fail-closed local security/release checks; never touch hosted providers."""
import base64
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_avenra as fixtures


class BrowserPolicyTests(unittest.TestCase):
    setUp=fixtures.avenraStagesTestCase.setUp
    tearDown=fixtures.avenraStagesTestCase.tearDown

    def test_private_pwa_csp_allows_only_trusted_script_hashes_not_inline_handlers(self):
        response=self.client.get('/survivor/index.html')
        self.addCleanup(response.close)
        policy=response.headers.get('Content-Security-Policy','')
        self.assertIn("default-src 'none'",policy)
        self.assertIn("script-src-attr 'none'",policy)
        self.assertIn("frame-ancestors 'none'",policy)
        scripts=next(part for part in policy.split(';') if part.strip().startswith('script-src '))
        self.assertNotIn('unsafe-inline',scripts)
        self.assertNotIn('unsafe-eval',scripts)
        class Scripts(HTMLParser):
            def __init__(self): super().__init__(); self.script=False; self.parts=[]; self.values=[]
            def handle_starttag(self,tag,attrs):
                if tag=='script' and 'src' not in dict(attrs): self.script=True; self.parts=[]
            def handle_data(self,data):
                if self.script: self.parts.append(data)
            def handle_endtag(self,tag):
                if tag=='script' and self.script:
                    self.values.append(''.join(self.parts)); self.script=False
        parser=Scripts(); parser.feed(response.text)
        self.assertTrue(parser.values)
        for value in parser.values:
            self.assertIn("'sha256-"+base64.b64encode(sha256(value.encode()).digest()).decode()+"'",scripts)
        injected="alert('untrusted fictional probe')"
        self.assertNotIn(base64.b64encode(sha256(injected.encode()).digest()).decode(),scripts)

    def test_private_pages_have_no_inline_event_handlers(self):
        class Handlers(HTMLParser):
            def handle_starttag(parser,tag,attrs):
                self.assertFalse(any(name.lower().startswith('on') for name,_ in attrs),tag)
        for path in Path('static/survivor').glob('*.html'):
            with self.subTest(path=path.name): Handlers().feed(path.read_text())

    def test_https_hsts_and_http_local_development_boundary(self):
        secure=self.client.get('/login',base_url='https://localhost')
        self.assertEqual(secure.headers.get('Strict-Transport-Security'),'max-age=31536000')
        self.assertIn('upgrade-insecure-requests',secure.headers.get('Content-Security-Policy',''))
        local=self.client.get('/login')
        self.assertNotIn('Strict-Transport-Security',local.headers)
        self.assertNotIn('upgrade-insecure-requests',local.headers.get('Content-Security-Policy',''))

    def test_obsolete_sms_webhook_and_telegram_path_cannot_send_or_fallback(self):
        import sms
        with patch.dict('os.environ',{'SMS_WEBHOOK_URL':'https://fictional.invalid/sms','TELEGRAM_BOT_TOKEN':'fictional-not-a-token','TELEGRAM_CHAT_ID':'fictional'}),patch('urllib.request.urlopen') as transport:
            result=sms.send_single('Fictional contact','+27000000000','Fictional test','TEST')
        transport.assert_not_called()
        self.assertEqual(result,{'channel':'legacy_disabled','ok':False})


class ReleaseGateTests(unittest.TestCase):
    def test_runtime_hash_lock_rejects_unhashed_or_unsafe_requirements(self):
        from tools.security_gate import runtime_pins
        digest = 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text('--require-hashes\nfictional-package==1.0 \\\n'
                            '    --hash=sha256:' + digest + '\n')
            self.assertEqual(runtime_pins(path), {'fictional-package': '1.0'})
            for entry in ('fictional==1.0',
                          'fictional>=1.0 --hash=sha256:' + digest,
                          'fictional==1.0 --hash=sha256:invalid',
                          'fictional==1.0 --hash=sha1:' + digest,
                          '--no-require-hashes', '--trusted-host example.invalid',
                          '-r unreviewed.txt', 'fictional @ https://example.invalid/pkg.whl'):
                with self.subTest(entry=entry):
                    path.write_text(entry + '\n')
                    with self.assertRaises(ValueError):
                        runtime_pins(path)

    def test_runtime_hash_lock_rejects_duplicate_names(self):
        from tools.security_gate import runtime_pins
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text('fictional-package==1.0 --hash=sha256:' + 'a' * 64 + '\n'
                            'Fictional_Package==2.0 --hash=sha256:' + 'b' * 64 + '\n')
            with self.assertRaises(ValueError):
                runtime_pins(path)

    def test_development_lock_must_include_only_the_expected_runtime_lock(self):
        from tools.security_gate import runtime_pins
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            pin = 'fictional==1.0 --hash=sha256:' + 'a' * 64 + '\n'
            path.write_text('-r requirements-lock.txt\n' + pin)
            self.assertEqual(runtime_pins(path, include='requirements-lock.txt'), {'fictional': '1.0'})
            for prefix in ('', '-r unreviewed.txt\n', '-r requirements-lock.txt\n-r requirements-lock.txt\n'):
                path.write_text(prefix + pin)
                with self.assertRaises(ValueError):
                    runtime_pins(path, include='requirements-lock.txt')

    def test_followup_browser_checks_run_without_removing_csp_acceptance(self):
        workflow = Path('.github/workflows/verify.yml').read_text()
        for name in ('stage11_csp_browser.py','followup_privacy_browser.py','weather_data_boundary_browser.py'):
            self.assertIn('python tests/'+name, workflow)

    def test_scanner_error_or_unreviewed_finding_fails_even_when_process_succeeded(self):
        from tools.security_gate import bandit_findings
        with self.assertRaises(ValueError): bandit_findings({'errors':[{'filename':'synthetic'}],'results':[]},[])
        issue={'filename':'avenra/synthetic.py','line_number':1,'test_id':'B608','issue_severity':'MEDIUM','code':'synthetic'}
        with self.assertRaises(ValueError): bandit_findings({'errors':[],'results':[issue],'metrics':{'_totals':{'loc':1}}},[])
        with self.assertRaises(ValueError): bandit_findings({'errors':[],'results':[]},[])
        self.assertEqual(bandit_findings({'errors':[],'results':[],'metrics':{'_totals':{'loc':1}}},[]),0)

    def test_tracked_credential_detection_does_not_need_to_print_matches(self):
        from tools.security_gate import secret_findings
        self.assertEqual(secret_findings('ordinary source text'),[])
        private_header='-----BEGIN '+'PRIVATE KEY-----'
        self.assertEqual(secret_findings('safe line\n'+private_header),[2])

    def test_review_cannot_waive_high_findings_or_survive_its_expiry(self):
        from datetime import date
        from tools.security_gate import bandit_findings,fingerprint
        issue={'filename':'avenra/synthetic.py','line_number':1,'test_id':'B608','issue_severity':'MEDIUM','code':'synthetic'}
        report={'errors':[],'results':[issue],'metrics':{'_totals':{'loc':1}}}
        approval={'fingerprint':fingerprint(issue),'reason':'Synthetic review test','expires':date.today().isoformat()}
        self.assertEqual(bandit_findings(report,[approval]),1)
        approval['expires']='2000-01-01'
        with self.assertRaises(ValueError): bandit_findings(report,[approval])
        approval['expires']=date.today().isoformat(); issue['issue_severity']='HIGH'
        with self.assertRaises(ValueError): bandit_findings(report,[approval])

    def test_dependency_scan_skips_or_advisories_cannot_pass(self):
        from tools.security_gate import dependency_findings
        for entry in ({'name':'fictional','skip_reason':'unavailable'}, {'name':'fictional','vulns':[{'id':'fictional-advisory'}]}):
            with self.subTest(entry=entry),self.assertRaises(ValueError): dependency_findings({'dependencies':[entry]})
        self.assertEqual(dependency_findings({'dependencies':[{'name':'fictional','version':'1.0','vulns':[]}]}),1)
        with self.assertRaises(ValueError):
            dependency_findings({'dependencies':[{'name':'fictional','version':'1.0','vulns':[]}]},{'fictional':'1.0','omitted':'2.0'})

    def test_runtime_closure_and_sbom_must_match_the_audited_pins(self):
        from tools.security_gate import resolution_findings,sbom_findings
        expected={'fictional':'1.0'}
        self.assertEqual(resolution_findings({'install':[{'metadata':{'name':'fictional','version':'1.0'}}]},expected),1)
        self.assertEqual(sbom_findings({'bomFormat':'CycloneDX','components':[{'name':'fictional','version':'1.0'}]},expected),1)
        with self.assertRaises(ValueError): resolution_findings({'install':[]},expected)
        with self.assertRaises(ValueError): sbom_findings({'bomFormat':'CycloneDX','components':[]},expected)

    def test_ci_is_unprivileged_and_has_no_deployment_or_live_secrets(self):
        content=Path('.github/workflows/verify.yml').read_text()
        self.assertIn('contents: read',content)
        self.assertNotIn('pull_request_target',content)
        self.assertNotRegex(content,r'(?i)\$\{\{[^}]*\bsecrets\s*(?:\.|\[)')
        for marker in ('security_gate.py','pip-audit','bandit','cyclonedx-json','node --test','unittest discover'):
            self.assertIn(marker,content)
