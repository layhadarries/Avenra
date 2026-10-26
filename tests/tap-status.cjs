'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {webcrypto} = require('node:crypto');

async function fixture(phase = 'queued') {
  const handlers = {}, output = {textContent: '', hidden: true};
  const storage = new Map([
    ['clear-sky-weather-tap-v1', JSON.stringify({version:1, setup_version:1, enabled:true, owner_id:1})],
    ['clear-sky-alert-owner-v1', '1'],
    ['clear-sky-weather-tap-status-v1', JSON.stringify({owner_id:1, client_id:'tap-'+'a'.repeat(32), phase, alert_id:12})]
  ]);
  if (phase === null) storage.delete('clear-sky-weather-tap-status-v1');
  const records = [{client_id:'tap-'+'a'.repeat(32), owner_id:1}], before = JSON.stringify(records);
  let activate, flushed, mutation;
  const listen = (name, fn) => (handlers[name] ||= []).push(fn);
  const document = {hidden:false, visibilityState:'visible', hasFocus:()=>true,
    body:{classList:{contains:()=>true, add(){}, remove(){}}}, getElementById:()=>output,
    querySelectorAll:()=>[], addEventListener:listen};
  const window = {PointerEvent:function(){}, addEventListener:listen,
    CWTapDetector:options => {activate=options.activate; return {reset(){}};},
    CWQueue:{ready:Promise.resolve(), onFlushed:fn=>{flushed=fn;}, flushQueue(){},
      queueAlert:async record=>{records.push(record);}}};
  const context = {window, document, crypto:webcrypto, Number, performance,
    localStorage:{getItem:key=>storage.get(key)??null, setItem:(k,v)=>storage.set(k,v), removeItem:k=>storage.delete(k)},
    navigator:{onLine:false}, MutationObserver:class {constructor(fn){mutation=fn;} observe(){}}, AbortController,
    setTimeout:()=>1, clearTimeout(){}, fetch:async()=>{throw Error('offline');}};
  vm.runInNewContext(fs.readFileSync('static/survivor/tap-alert.js','utf8'), context);
  await Promise.resolve(); await Promise.resolve();
  return {output, storage, records, before, activate:()=>activate(),
    emit:async(name,event={})=>{for(const fn of handlers[name]||[]) await fn({persisted:true,...event});},
    modal:()=>mutation([{target:{matches:()=>true}}]),
    receipt:()=>flushed({type:'sent',receipt:{id:99,client_id:records.at(-1).client_id,status:'new'}})};
}

for (const phase of ['queued','received','acknowledged','resolved']) {
  test('fresh/reopened weather does not restore '+phase+' status or mutate durable records', async()=>{
    const f=await fixture(phase);
    assert.equal(f.output.textContent,'');
    assert.equal(JSON.stringify(f.records),f.before);
    await f.emit('pageshow');
    assert.equal(f.output.textContent,'');
  });
}
test('active feedback distinguishes local save and server receipt; return hides it without losing queue',async()=>{
  const f=await fixture(null); await f.activate();
  assert.match(f.output.textContent,/Saved on this phone/);
  f.receipt(); assert.match(f.output.textContent,/Received by Avenra/);
  const queued=JSON.stringify(f.records);
  await f.emit('pagehide'); await f.emit('pageshow');
  assert.equal(f.output.textContent,'');
  f.receipt(); assert.equal(f.output.textContent,'');
  assert.equal(JSON.stringify(f.records),queued);
});
test('a new gesture after reopening retries the existing queued tap instead of creating a duplicate', async()=>{
  const f = await fixture('queued');
  await f.activate();
  assert.match(f.output.textContent,/Saved on this phone/);
  assert.equal(JSON.stringify(f.records),f.before);
});
for (const interaction of ['weather-control','modal']) {
  test('return to ordinary weather after '+interaction+' hides active feedback without changing records', async()=>{
    const f=await fixture(null); await f.activate(); f.receipt();
    const before=JSON.stringify(f.records);
    if (interaction==='modal') f.modal();
    else await f.emit('click',{target:{closest:()=>({})}});
    assert.equal(f.output.textContent,'');
    assert.equal(JSON.stringify(f.records),before);
  });
}
