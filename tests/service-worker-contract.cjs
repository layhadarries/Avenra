'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const handlers = {};
const deleted = [];
let matches = 0;
let network = 0;
const context = {
  URL, Set, Promise,
  self: {location:{origin:'https://avenra.example.test'},
    addEventListener:(name,fn)=>handlers[name]=fn,
    skipWaiting:()=>Promise.resolve(),clients:{claim:()=>Promise.resolve()}},
  caches: {
    open:async()=>({addAll:async()=>{}, match:async()=>{matches++;return 'public shell';}}),
    keys:async()=>['cape-weather-shell-v3','clear-sky-shell-v1','unrelated-app-cache'],
    delete:async key=>{deleted.push(key);return true;}
  },
  fetch:async()=>{network++;return 'network';}
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/survivor/service-worker.js'),'utf8'),context);
async function fetchCase(pathname,method='GET') {
  let handled=false;let result;
  handlers.fetch({request:{url:new URL(pathname,'https://avenra.example.test').href,method},
    respondWith:promise=>{handled=true;result=promise;}});
  if(result)await result;
  return handled;
}
(async()=>{
  for(const url of ['/api/alerts','/api/contacts','/dashboard','/survivor/index.html?private=1','https://other.example.test/survivor/']) {
    assert.equal(await fetchCase(url),false,url);
  }
  assert.equal(await fetchCase('/survivor/','POST'),false);
  assert.equal(await fetchCase('/survivor/index.html'),true);
  assert.equal(matches,1);assert.equal(network,0);
  let activation;
  handlers.activate({waitUntil:promise=>activation=promise});
  await activation;
  assert.deepEqual(deleted.sort(),['cape-weather-shell-v3','clear-sky-shell-v1'].sort());
  console.log('PASS: public shell served; APIs, staff routes, writes, query URLs and external URLs excluded; unrelated caches preserved.');
})().catch(error=>{console.error(error);process.exitCode=1;});
