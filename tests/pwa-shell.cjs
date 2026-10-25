const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function worker() {
  const handlers = {}, deleted = [], assets = [], skipped = [];
  const self = {location:{origin:'https://avenra.test'}, clients:{claim:async()=>{}},
    skipWaiting:()=>skipped.push(true), addEventListener:(name,fn)=>{handlers[name]=fn;}};
  const cache = {addAll:async urls=>assets.push(...urls), match:async()=>new Response('shell')};
  const caches = {open:async()=>cache, match:async()=>new Response('shell'),
    keys:async()=>['avenra-pwa-shell-v0','clear-sky-shell-v1','other-app-cache','avenra-private-cache'],
    delete:async key=>{deleted.push(key);return true;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/survivor/service-worker.js'),'utf8'),
    {self,caches,URL,Promise,fetch:async()=>new Response('network')});
  return {handlers,deleted,assets,skipped};
}
async function intercepted(worker, url, options={}) {
  let promise;
  worker.handlers.fetch({request:new Request(url,options),respondWith:value=>{promise=Promise.resolve(value);}});
  if(promise) await promise;
  return Boolean(promise);
}

test('private routes, writes and cross-origin requests bypass shell cache', async()=>{
  const w=worker();
  for(const url of ['/api/alerts','/login','/dashboard','/cases/SP-1042','/survivor/?token=secret'])
    assert.equal(await intercepted(w,'https://avenra.test'+url),false,url);
  assert.equal(await intercepted(w,'https://avenra.test/survivor/',{method:'POST'}),false);
  assert.equal(await intercepted(w,'https://elsewhere.test/survivor/'),false);
});
test('only public shell requests without Authorization use cache',async()=>{
  const w=worker();
  assert.equal(await intercepted(w,'https://avenra.test/survivor/'),true);
  assert.equal(await intercepted(w,'https://avenra.test/survivor/',{headers:{Authorization:'Bearer synthetic'}}),false);
});
test('activation deletes only owned old shell caches',async()=>{
  const w=worker(); let pending;
  w.handlers.activate({waitUntil:p=>{pending=p;}}); await pending;
  assert.deepEqual(w.deleted.sort(),['avenra-pwa-shell-v0','clear-sky-shell-v1'].sort());
});
test('installation includes both icons, direct entry and offline script without forcing updates',async()=>{
  const w=worker();let pending;
  w.handlers.install({waitUntil:p=>{pending=p;}});await pending;
  for(const asset of ['/survivor/index.html','/survivor/shell.js','/survivor/icons/icon-192.png','/survivor/icons/icon-512.png'])
    assert.ok(w.assets.includes(asset),asset);
  assert.ok(w.assets.includes('/survivor/pwa.css'));
  assert.ok(w.assets.includes('/survivor/theme.js'));
  assert.ok(w.assets.includes('/survivor/weather.js'));
  assert.ok(w.assets.includes('/survivor/weather.css'));
  assert.equal(new Set(w.assets).size,w.assets.length,'Duplicate assets can break cache installation');
  assert.ok(!w.assets.includes('/static/css/style.css'), 'PWA must not download dashboard CSS');
  assert.equal(w.skipped.length,0);
});

test('support screens share a small local stylesheet with no remote assets',()=>{
  const root=path.join(__dirname,'../static/survivor');
  const css=fs.readFileSync(path.join(root,'pwa.css'),'utf8');
  assert.ok(require('node:zlib').gzipSync(css).length < 4096, 'Shared CSS budget: 4 KiB gzipped');
  assert.doesNotMatch(css, /@import|url\(|@font-face/i);
  for(const name of ['index','diary','help','privacy','setup']) {
    const html=fs.readFileSync(path.join(root,name+'.html'),'utf8');
    assert.ok(html.includes('href="/survivor/pwa.css"'), name);
    assert.ok(!html.includes('href="/static/css/style.css"'), name);
    assert.ok(html.includes('Quick exit'), name);
  }
  assert.ok(!fs.readFileSync(path.join(root,'cover.html'),'utf8').includes('/survivor/pwa.css'));
});

test('worker activation requires an explicit public-shell update message', async()=>{
  const w=worker(); let pending;
  w.handlers.message({data:{type:'unrelated'},waitUntil:p=>{pending=p;}});
  assert.equal(w.skipped.length,0);
  w.handlers.message({data:{type:'ACTIVATE_PUBLIC_SHELL_UPDATE'},waitUntil:p=>{pending=p;}});
  await pending;
  assert.equal(w.skipped.length,1);
  const script=fs.readFileSync(path.join(__dirname,'../static/survivor/update.js'),'utf8');
  assert.doesNotMatch(script,/localStorage\s*\.|indexedDB\s*\.|document\.cookie|location\.reload/);
});

test('weather uses a small standalone shell with no remote visual assets or dummy readings',()=>{
  const root=path.join(__dirname,'../static/survivor');
  const html=fs.readFileSync(path.join(root,'cover.html'),'utf8');
  const css=fs.readFileSync(path.join(root,'weather.css'),'utf8');
  const script=fs.readFileSync(path.join(root,'weather.js'),'utf8');
  const gzip=require('node:zlib').gzipSync;
  assert.ok(gzip(css).length + gzip(script).length < 12*1024,'Weather CSS + JS budget: 12 KiB gzipped');
  assert.doesNotMatch(css,/@import|url\(|@font-face/i);
  assert.ok(!html.includes('href="/survivor/survivor.css"'),'Do not download the legacy full-app CSS');
  assert.doesNotMatch(html,/\bAREAS\b|Clean coastal air|06:14|cv-areas/);
  assert.doesNotMatch(script,/watchPosition|\/api\/alerts|\/api\/consents|indexedDB|document\.cookie/);
});
