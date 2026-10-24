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
  assert.equal(w.skipped.length,0);
});
