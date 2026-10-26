"""Fail closed on scan errors, unreviewed medium/high issues or tracked secrets.

Reports and dependency-only SBOMs may be stored as CI artifacts. Never include
environment dumps, deployment credentials, test browser storage or runtime logs.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=(
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    re.compile(r'postgres(?:ql)?://[^\s\'\"]+:[^\s\'\"]+@'),
)


def fingerprint(issue):
    value=[issue['filename'].removeprefix('./'),issue['test_id'],issue['code']]
    return hashlib.sha256(json.dumps(value,separators=(',',':')).encode()).hexdigest()


def bandit_findings(report,reviewed):
    if not isinstance(report,dict) or not isinstance(report.get('errors'),list) or report['errors'] or not isinstance(report.get('results'),list):
        raise ValueError('Static scan failed or has incomplete coverage')
    if report.get('metrics',{}).get('_totals',{}).get('loc',0)<=0:
        raise ValueError('Static scanner reported no source coverage')
    approvals={}
    for approval in reviewed:
        if not approval.get('reason') or date.fromisoformat(approval['expires'])<date.today():
            raise ValueError('Static review missing a reason or expired')
        approvals[approval['fingerprint']]=approval
    for issue in report['results']:
        if issue['issue_severity'] not in {'LOW','MEDIUM','HIGH'}:
            raise ValueError('Invalid static scan severity')
        if issue['issue_severity']=='LOW': continue
        if issue['issue_severity']=='HIGH' or fingerprint(issue) not in approvals:
            raise ValueError('Unreviewed static finding: '+issue['filename']+':'+str(issue['line_number'])+':'+issue['test_id'])
    return len(report['results'])


def dependency_findings(report,expected=None):
    if not isinstance(report,dict) or not isinstance(report.get('dependencies'),list) or not report['dependencies']:
        raise ValueError('Dependency audit missing or empty')
    for entry in report['dependencies']:
        if 'skip_reason' in entry or not entry.get('name') or not entry.get('version') or entry.get('vulns')!=[]:
            raise ValueError('Dependency audit skipped a package or found an advisory')
    if expected is not None:
        found={re.sub(r'[-_.]+','-',entry['name']).lower():entry['version'] for entry in report['dependencies']}
        if found!=expected: raise ValueError('Dependency audit coverage does not match the complete runtime pins')
    return len(report['dependencies'])


def runtime_pins(path):
    pins={}
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)',line)
        if not match: raise ValueError('Runtime pins must be explicit exact versions')
        name=re.sub(r'[-_.]+','-',match[1]).lower()
        if name in pins: raise ValueError('Duplicate runtime pin')
        pins[name]=match[2]
    if not pins: raise ValueError('Runtime pins are empty')
    return pins


def resolution_findings(report,expected):
    if not isinstance(report,dict) or not isinstance(report.get('install'),list) or not report['install']:
        raise ValueError('Runtime dependency resolution missing')
    found={re.sub(r'[-_.]+','-',entry['metadata']['name']).lower():entry['metadata']['version'] for entry in report['install']}
    if found!=expected: raise ValueError('Runtime dependency closure differs from exact pins')
    return len(found)


def sbom_findings(report,expected):
    if report.get('bomFormat')!='CycloneDX' or not isinstance(report.get('components'),list) or report.get('vulnerabilities'):
        raise ValueError('SBOM missing, invalid or contains unresolved advisories')
    found={re.sub(r'[-_.]+','-',entry['name']).lower():entry['version'] for entry in report['components']}
    if found!=expected: raise ValueError('SBOM does not cover the exact runtime pins')
    return len(found)


def secret_findings(text):
    return [index for index,line in enumerate(text.splitlines(),1) if any(pattern.search(line) for pattern in PATTERNS)]


def scan_tracked():
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    checked=0
    for name in filter(None,paths):
        path=ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('Tracked symlink or outside path requires review: '+name)
        if not path.is_file() or path.stat().st_size>20*1024*1024:
            raise ValueError('Tracked file unavailable or exceeds scan budget: '+name)
        lines=secret_findings(path.read_bytes().decode('utf-8',errors='ignore'))
        if lines: raise ValueError('Possible tracked credential: '+name+':'+str(lines[0]))
        checked+=1
    if not checked: raise ValueError('No tracked source scanned')
    return checked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bandit-report',type=Path)
    parser.add_argument('--run-bandit',type=Path,help='Run this interpreter\'s pinned scanner and write a report.')
    parser.add_argument('--dependency-report',type=Path)
    parser.add_argument('--resolution-report',type=Path)
    parser.add_argument('--sbom',type=Path)
    parser.add_argument('--secret-scan',action='store_true')
    parser.add_argument('--reviewed',type=Path,default=ROOT/'security'/'bandit-reviewed.json')
    args=parser.parse_args()
    if not any((args.bandit_report,args.run_bandit,args.dependency_report,args.resolution_report,args.sbom,args.secret_scan)):
        parser.error('Choose at least one required check')
    try:
        if args.run_bandit:
            result=subprocess.run([sys.executable,'-m','bandit','-r','avenra','tools','app.py','db.py','sms.py','seed.py',
                '-f','json','-o',str(args.run_bandit)],cwd=ROOT,check=False)
            if result.returncode not in {0,1}: raise ValueError('Static scanner failed to execute')
            args.bandit_report=args.run_bandit
        if args.bandit_report:
            count=bandit_findings(json.loads(args.bandit_report.read_text()),json.loads(args.reviewed.read_text()))
            print('Static scan gate passed; reported findings:',count,'(reviewed medium findings and informational lows retained)')
        if args.dependency_report:
            print('Dependency gate passed; audited packages:',dependency_findings(json.loads(args.dependency_report.read_text()),runtime_pins(ROOT/'requirements-lock.txt')))
        if args.resolution_report:
            print('Runtime closure gate passed; packages:',resolution_findings(json.loads(args.resolution_report.read_text()),runtime_pins(ROOT/'requirements-lock.txt')))
        if args.sbom:
            print('CycloneDX coverage gate passed; components:',sbom_findings(json.loads(args.sbom.read_text()),runtime_pins(ROOT/'requirements-lock.txt')))
        if args.secret_scan: print('Tracked credential-pattern check passed; files:',scan_tracked())
    except (ValueError,OSError,KeyError,TypeError) as error:
        # The checks construct content-free messages; never echo scanner code or
        # a credential match. Raw JSON/IO exceptions are not displayed.
        message=str(error) if type(error) is ValueError and not isinstance(error,json.JSONDecodeError) else 'Required scan/report unavailable or malformed'
        parser.exit(1,'Security gate failed: '+message+'\n')


if __name__=='__main__': main()
