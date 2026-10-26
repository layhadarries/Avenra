const {test} = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const vm = require('node:vm');
const {readFileSync} = require('node:fs');

function fixture(storage=new Map()) {
  const events={};
  const context={window:null, crypto:webcrypto, TextEncoder, TextDecoder, Blob, Uint8Array,
    navigator:{locks:{request:async (_,fn)=>fn()}},
    btoa:value=>Buffer.from(value,'binary').toString('base64'),atob:value=>Buffer.from(value,'base64').toString('binary'),
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    addEventListener:(name,fn)=>{events[name]=fn;},dispatchEvent:()=>{},CustomEvent:class {},
    document:{hidden:false,addEventListener:(name,fn)=>{events[name]=fn;}}};
  context.window=context;
  vm.runInNewContext(readFileSync('static/survivor/storage-vault.js','utf8'),context);
  return {vault:context.CWVault,storage,events};
}
const phrase='Cedar! private river vault 826';
const item={client_id:'fictional-diary',owner_id:7,note:'Fictional private diary text',photo_blob:new Blob(['fictional bytes'],{type:'image/jpeg'})};
test('strong passphrase protects notes/photos; only wrapped key persists, locked profile cannot decrypt',async()=>{
  const f=fixture(); await f.vault.setup(7,phrase);
  const sealed=await f.vault.seal(item);
  assert.equal(sealed.owner_id,7); assert.equal(sealed.note,undefined); assert.equal(sealed.photo_blob,undefined);
  assert.ok(!JSON.stringify(sealed).includes(item.note));
  assert.ok(!JSON.stringify([...f.storage.values()]).includes(phrase));
  const restored=await f.vault.open(sealed);
  assert.equal(restored.note,item.note); assert.equal(await restored.photo_blob.text(),'fictional bytes');
  f.vault.lock(); await assert.rejects(f.vault.open(sealed),/locked/);
  const stolen=fixture(f.storage);
  await assert.rejects(stolen.vault.unlock(7,'Wrong! strong phrase 927'),/unlock_failed/);
  await assert.rejects(stolen.vault.open(sealed),/locked/);
  await stolen.vault.unlock(7,phrase);
  assert.equal((await stolen.vault.open(sealed)).note,item.note);
});
test('owner/client tampering and ciphertext modification fail authentication',async()=>{
  const f=fixture(); await f.vault.setup(7,phrase); const sealed=await f.vault.seal(item);
  await assert.rejects(f.vault.open({...sealed,owner_id:8}));
  await assert.rejects(f.vault.open({...sealed,client_id:'another-entry'}));
  await assert.rejects(f.vault.open({...sealed,ciphertext:'AAAA'+sealed.ciphertext.slice(4)}));
});
test('setup cannot overwrite existing keys; page lifecycle locks without deleting records',async()=>{
  const f=fixture(); await f.vault.setup(7,phrase); const before=[...f.storage.values()];
  await assert.rejects(f.vault.setup(7,'Another! strong phrase 826'),/already_configured/);
  await assert.rejects(f.vault.setup(8,'1234'),/strong_passphrase_required/);
  const sealed=await f.vault.seal(item); f.events.pagehide();
  await assert.rejects(f.vault.open(sealed),/locked/); assert.deepEqual([...f.storage.values()],before);
});
test('maximum legacy photo is encrypted once and remains readable after reopen',async()=>{
  const f=fixture(); await f.vault.setup(7,phrase);
  const bytes=new Uint8Array(4*1024*1024); bytes[0]=19; bytes[bytes.length-1]=37;
  const large={...item,photo_blob:new Blob([bytes],{type:'image/jpeg'}),
    photo_data:'data:image/jpeg;base64,'+Buffer.from(bytes).toString('base64')};
  const sealed=await f.vault.seal(large);
  assert.ok(sealed.ciphertext.length<8000000);
  f.vault.lock(); await f.vault.unlock(7,phrase);
  const restored=await f.vault.open(sealed);
  assert.equal(restored.photo_data,undefined);
  assert.deepEqual(new Uint8Array(await restored.photo_blob.arrayBuffer()),bytes);
});
