'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const crypto = require('node:crypto');

function fixture(mode = 'valid') {
  const keys = crypto.generateKeyPairSync('ec', {namedCurve:'prime256v1'});
  const id = Buffer.from('synthetic-local-screen-key');
  const storage = new Map();
  const context = {
    TextEncoder, TextDecoder, Uint8Array, JSON, Date, Error,
    crypto:crypto.webcrypto, btoa, atob,
    location:{origin:'https://avenra.test', hostname:'avenra.test'},
    localStorage:{getItem:key=>storage.get(key)||null, setItem:(key,value)=>storage.set(key,value), removeItem:key=>storage.delete(key)},
    navigator:{credentials:{get:async request=>{
      const challenge = Buffer.from(request.publicKey.challenge).toString('base64url');
      const client = Buffer.from(JSON.stringify({
        type:'webauthn.get', challenge:mode==='replay'?'previous-challenge':challenge,
        origin:mode==='foreign-origin'?'https://elsewhere.test':'https://avenra.test', crossOrigin:false
      }));
      const auth = Buffer.alloc(37);
      crypto.createHash('sha256').update(mode==='wrong-rp'?'elsewhere.test':'avenra.test').digest().copy(auth);
      auth[32] = mode==='no-user-verification'?1:5;
      const signed = Buffer.concat([auth, crypto.createHash('sha256').update(client).digest()]);
      const signature = crypto.sign('sha256', signed, keys.privateKey);
      if (mode==='bad-signature') signature[signature.length - 1] ^= 1;
      return {rawId:id, response:{clientDataJSON:client, authenticatorData:auth, signature}};
    }}},
  };
  context.window = {isSecureContext:true, PublicKeyCredential:{isUserVerifyingPlatformAuthenticatorAvailable:async()=>true}};
  context.PublicKeyCredential = context.window.PublicKeyCredential;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/survivor/unlock.js'),'utf8'), context);
  context.window.CWUnlock.saveDevice({version:1, rpId:'avenra.test', id:id.toString('base64url'),
    key:keys.publicKey.export({type:'spki',format:'der'}).toString('base64url')});
  return {unlock:context.window.CWUnlock, storage};
}

test('local device unlock verifies a fresh signed challenge', async()=>{
  const {unlock}=fixture();
  assert.equal(await unlock.unlockDevice(),true);
});
for(const mode of ['replay','foreign-origin','wrong-rp','no-user-verification','bad-signature']) {
  test('local device unlock rejects '+mode, async()=>{
    await assert.rejects(fixture(mode).unlock.unlockDevice());
  });
}
test('PIN storage is salted; correct and incorrect PINs are distinguished', async()=>{
  const {unlock,storage}=fixture();
  await unlock.setPin('2468');
  const first=storage.get('cs_pin_hash');
  assert.equal(JSON.parse(first).version,2);
  assert.ok(!first.includes('2468'));
  assert.equal(await unlock.verifyPin('0000'),false);
  assert.equal(await unlock.verifyPin('2468'),true);
  await unlock.setPin('2468');
  assert.notEqual(storage.get('cs_pin_hash'),first);
});
test('PIN attempts are cooled down and cancelled setup cannot persist a PIN', async()=>{
  const {unlock,storage}=fixture();
  await unlock.setPin('2468');
  for(let i=0;i<5;i++) assert.equal(await unlock.verifyPin('0000'),false);
  await assert.rejects(unlock.verifyPin('2468'),/Wait a moment/);
  const before=storage.get('cs_pin_hash');
  await assert.rejects(unlock.setPin('1357',()=>false));
  assert.equal(storage.get('cs_pin_hash'),before);
});
