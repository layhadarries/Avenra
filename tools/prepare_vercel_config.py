"""Update the linked Flask service build, preserving a local config backup."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'vercel.json'
if path.exists():
    config=json.loads(path.read_text())
else:
    config={'services':{'avenra':{'root':'.'}},'rewrites':[{'source':'/(.*)','destination':{'type':'service','service':'avenra'}}]}
service=config.get('services',{}).get('avenra')
if not isinstance(service,dict) or service.get('root','.')!='.':
    raise SystemExit('Unexpected Vercel service configuration; no files changed.')
backup=root/'.vercel/vercel-config-before-dashboard.json'
backup.parent.mkdir(exist_ok=True)
if path.exists() and not backup.exists(): backup.write_text(path.read_text())
service['buildCommand']='pip install -r requirements.txt && python tools/build_vercel_assets.py'
path.write_text(json.dumps(config,indent=2)+'\n')
ignore=root/'.gitignore'
content=ignore.read_text() if ignore.exists() else ''
for pattern in ('/.vercel/','/.env*','/public/static/'):
    if pattern not in content.splitlines(): content+='\n'+pattern+'\n'
ignore.write_text(content)
print('PASS: Vercel Flask build configured; generated public assets and local credentials ignored by Git.')
