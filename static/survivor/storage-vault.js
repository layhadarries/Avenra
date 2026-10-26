/* Offline diary encryption primitive. Integration/migration must not bypass locks.
   AES-256-GCM; random per-record nonce; passphrase-wrapped random data key.
   This does not protect unlocked memory, same-origin scripts or OS screenshots. */
(function () {
  'use strict';
  var PREFIX = 'clear-sky-private-vault-v1:', ITERATIONS = 600000;
  var key = null, owner = null, generation = 0, encoder = new TextEncoder();
  function ownerId(value) { if (!Number.isSafeInteger(value) || value < 1) throw new Error('invalid_owner'); return value; }
  function random(length) { return crypto.getRandomValues(new Uint8Array(length)); }
  function encode(bytes) {
    bytes = new Uint8Array(bytes); var result = '';
    for (var offset = 0; offset < bytes.length; offset += 8192) result += String.fromCharCode.apply(null,bytes.subarray(offset,offset+8192));
    return btoa(result);
  }
  function decode(value) {
    if (typeof value !== 'string' || value.length > 8000000) throw new Error('invalid_ciphertext');
    return Uint8Array.from(atob(value),function (character) { return character.charCodeAt(0); });
  }
  function metadata(id) { return JSON.parse(localStorage.getItem(PREFIX+ownerId(id)) || 'null'); }
  function associated(id, clientId, purpose) { return encoder.encode(JSON.stringify([1,id,clientId,purpose])); }
  function check(revision) { if (generation !== revision) throw new Error('vault_locked'); }
  async function derive(phrase,salt) {
    if (typeof phrase !== 'string' || phrase.length < 15 || phrase.length > 128) throw new Error('strong_passphrase_required');
    var material = await crypto.subtle.importKey('raw',encoder.encode(phrase),'PBKDF2',false,['deriveKey']);
    return crypto.subtle.deriveKey({name:'PBKDF2',salt:salt,iterations:ITERATIONS,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
  }
  async function setup(id,phrase) {
    ownerId(id);
    if (metadata(id)) throw new Error('already_configured');
    if (typeof phrase !== 'string' || phrase.length < 15 || phrase.length > 128) throw new Error('strong_passphrase_required');
    if (!navigator.locks) throw new Error('secure_storage_lock_unavailable');
    return navigator.locks.request(PREFIX+id,async function () {
      if (metadata(id)) throw new Error('already_configured');
      var revision = ++generation, salt = random(16), iv = random(12), raw = random(32);
      try {
        var wrappingKey = await derive(phrase,salt); check(revision);
        var wrapped = await crypto.subtle.encrypt({name:'AES-GCM',iv:iv,additionalData:associated(id,'key','wrap')},wrappingKey,raw);
        var imported = await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt','decrypt']); check(revision);
        var record = JSON.stringify({version:1,owner_id:id,iterations:ITERATIONS,salt:encode(salt),iv:encode(iv),wrapped_key:encode(wrapped)});
        localStorage.setItem(PREFIX+id,record);
        if (localStorage.getItem(PREFIX+id) !== record) throw new Error('storage_unavailable');
        key = imported; owner = id;
      } finally { raw.fill(0); }
    });
  }
  async function unlock(id,phrase) {
    generation++; key = null; owner = null;
    var revision = generation, record = metadata(id);
    if (!record || record.version !== 1 || record.owner_id !== id || record.iterations !== ITERATIONS) throw new Error('vault_not_configured');
    try {
      var wrappingKey = await derive(phrase,decode(record.salt)); check(revision);
      var raw = new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(record.iv),additionalData:associated(id,'key','wrap')},wrappingKey,decode(record.wrapped_key)));
      try {
        var imported = await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt','decrypt']); check(revision);
        key = imported; owner = id;
      } finally { raw.fill(0); }
    } catch (_) { throw new Error('vault_unlock_failed'); }
  }
  async function seal(item) {
    if (!key || item.owner_id !== owner) throw new Error('vault_locked');
    var revision = generation, workingKey = key, data = Object.assign({},item), iv = random(12);
    if (data.photo_blob instanceof Blob) {
      data._vault_photo = {type:data.photo_blob.type,bytes:encode(await data.photo_blob.arrayBuffer())};
      delete data.photo_blob;
      delete data.photo_data; // Same derivative bytes; avoid a redundant second copy.
    }
    var encrypted = await crypto.subtle.encrypt({name:'AES-GCM',iv:iv,additionalData:associated(owner,item.client_id,'diary')},workingKey,encoder.encode(JSON.stringify(data)));
    check(revision);
    return {vault_version:1,owner_id:owner,client_id:item.client_id,iv:encode(iv),ciphertext:encode(encrypted)};
  }
  async function sealLegacy(item,publicRecord) {
    if (!publicRecord) throw new Error('legacy_protection_requires_public_key');
    var data = Object.assign({},item), bindingOwner = Number.isSafeInteger(item.owner_id) && item.owner_id > 0 ? item.owner_id : 0;
    if (data.photo_blob instanceof Blob) {
      data._vault_photo = {type:data.photo_blob.type,bytes:encode(await data.photo_blob.arrayBuffer())};
      delete data.photo_blob; delete data.photo_data;
    }
    var rsa = await crypto.subtle.importKey('spki',decode(publicRecord.spki),{name:'RSA-OAEP',hash:'SHA-256'},false,['wrapKey']);
    var aes = await crypto.subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
    var iv = random(12), wrapped = await crypto.subtle.wrapKey('raw',aes,rsa,{name:'RSA-OAEP'});
    var ciphertext = await crypto.subtle.encrypt({name:'AES-GCM',iv:iv,additionalData:associated(bindingOwner,item.client_id,'legacy-diary')},aes,encoder.encode(JSON.stringify(data)));
    var result = {client_id:item.client_id,legacy_public:1,sealed_payload:{version:1,kid:publicRecord.kid,owner_id:bindingOwner,
      iv:encode(iv),wrapped_key:encode(wrapped),ciphertext:encode(ciphertext)}};
    if (Object.prototype.hasOwnProperty.call(item,'owner_id')) result.owner_id = item.owner_id;
    return result;
  }
  function restoreRecord(item) {
    if (item._vault_photo) {
      item.photo_blob = new Blob([decode(item._vault_photo.bytes)],{type:item._vault_photo.type}); delete item._vault_photo;
    }
    return item;
  }
  async function open(record) {
    if (!key || record.owner_id !== owner) throw new Error('vault_locked');
    if (record.vault_version !== 1) throw new Error('vault_migration_required');
    var revision = generation;
    var raw = await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(record.iv),additionalData:associated(owner,record.client_id,'diary')},key,decode(record.ciphertext));
    check(revision);
    var item = JSON.parse(new TextDecoder().decode(raw));
    if (item.owner_id !== owner || item.client_id !== record.client_id) throw new Error('invalid_ciphertext');
    return restoreRecord(item);
  }
  function lock() {
    generation++; key = null; owner = null;
    window.dispatchEvent(new CustomEvent('vault-locked'));
  }
  window.CWVault = {setup:setup,unlock:unlock,seal:seal,open:open,lock:lock,
    sealLegacy:sealLegacy,restoreRecord:restoreRecord,
    configured:function (id) { return !!metadata(id); },unlocked:function (id) { return !!key && owner === id; }};
  window.addEventListener('pagehide',lock);
  window.addEventListener('storage',function (event) {
    if (event.key === null || event.key === 'clear-sky-alert-owner-v1' || event.key && event.key.indexOf(PREFIX) === 0) lock();
  });
  document.addEventListener('visibilitychange',function () { if (document.hidden) lock(); });
})();
