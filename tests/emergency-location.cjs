const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');

function fixture() {
  let callback, grant = 'one', enabled = true;
  const posts = [], events = {};
  const context = {window:null, AbortController, setTimeout:(fn,ms)=>setTimeout(fn,ms).unref(), clearTimeout, Date,
    document:{hidden:false,visibilityState:'visible',hasFocus:()=>true,addEventListener:()=>{}},
    navigator:{onLine:true,geolocation:{getCurrentPosition:ok=>{callback=ok;}}},
    localStorage:{getItem:()=>JSON.stringify({enabled,location_enabled:true,owner_id:7})},
    fetch:async (url,options)=>{
      if (options.method === 'POST') posts.push(JSON.parse(options.body));
      return {ok:true,json:async()=>({allowed:true,owner_id:7,grant,token:'signed'})};
    },addEventListener:(name,fn)=>{events[name]=fn;}};
  context.window=context; vm.runInNewContext(readFileSync('static/survivor/emergency-location.js','utf8'),context);
  return {context,posts,events,finish:()=>callback({coords:{latitude:-33,longitude:18,accuracy:20},timestamp:Date.now()}),
    grant:value=>{grant=value;},disable:()=>{enabled=false;}};
}
const tick = () => new Promise(resolve=>setImmediate(resolve));
test('capture is synchronous and GPS-free; late fix waits for receipt and uses same client ID',async()=>{
  const f=fixture(); const initial=f.context.CWEmergencyLocation.start(7,'tap-test');
  assert.equal(initial,null); assert.equal(f.posts.length,0);
  await tick(); f.finish(); await tick(); assert.equal(f.posts.length,0);
  f.context.CWEmergencyLocation.received('tap-test'); await tick();
  assert.equal(f.posts.length,1); assert.equal(f.posts[0].lat,-33);
  const recent=f.context.CWEmergencyLocation.start(7,'tap-next');
  assert.equal(recent.location_accuracy,20);
});
for (const reason of ['regrant','disable','background']) test(reason+' defeats delayed GPS callback',async()=>{
  const f=fixture(); f.context.CWEmergencyLocation.start(7,'tap-test'); await tick();
  if(reason==='regrant') f.grant('two');
  if(reason==='disable') f.disable();
  if(reason==='background') f.events.pagehide();
  f.finish(); f.context.CWEmergencyLocation.received('tap-test'); await tick(); await tick();
  assert.equal(f.posts.length,0);
});
