/* Local screen disguise only. Server authority remains the paired HttpOnly cookie.
   WebAuthn verifies a fresh signed challenge; biometric data never reaches us. */
(function () {
  'use strict';
  var PIN_KEY = 'cs_pin_hash', DEVICE_KEY = 'cs_device_unlock', ATTEMPTS = 'cs_pin_attempts';
  var encoder = new TextEncoder();
  function encode(bytes) {
    return btoa(String.fromCharCode.apply(null, new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function decode(text) {
    return Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/')), function (c) { return c.charCodeAt(0); });
  }
  function random(size) { return crypto.getRandomValues(new Uint8Array(size)); }
  function legacy(pin) {
    var hash = 2166136261, text = 'safepath:' + pin;
    for (var i = 0; i < text.length; i++) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 16777619); }
    return (hash >>> 0).toString(16);
  }
  async function derive(pin, salt) {
    var key = await crypto.subtle.importKey('raw', encoder.encode(pin), 'PBKDF2', false, ['deriveBits']);
    return encode(await crypto.subtle.deriveBits({name:'PBKDF2', salt:salt, iterations:100000, hash:'SHA-256'}, key, 256));
  }
  async function setPin(pin, stillActive) {
    if (!/^\d{4}$/.test(pin)) throw new Error('invalid_pin');
    var salt = random(16);
    var hash = await derive(pin, salt);
    if (stillActive && !stillActive()) throw new Error('Setup was closed.');
    localStorage.setItem(PIN_KEY, JSON.stringify({version:2, salt:encode(salt), hash:hash}));
  }
  function hasPin() { try { return !!localStorage.getItem(PIN_KEY); } catch (_) { return false; } }
  async function verifyPin(pin) {
    var attempts = JSON.parse(localStorage.getItem(ATTEMPTS) || '{}');
    if (attempts.until > Date.now()) throw new Error('Wait a moment before trying your code again.');
    var saved = localStorage.getItem(PIN_KEY), valid = false;
    if (saved && saved.charAt(0) === '{') {
      var record = JSON.parse(saved);
      valid = record.version === 2 && await derive(pin, decode(record.salt)) === record.hash;
    } else if (saved) {
      valid = legacy(pin) === saved;
      if (valid) await setPin(pin);
    }
    if (valid) localStorage.removeItem(ATTEMPTS);
    else {
      var count = (attempts.count || 0) + 1;
      localStorage.setItem(ATTEMPTS, JSON.stringify({count:count % 5, until:count >= 5 ? Date.now() + 30000 : 0}));
    }
    return valid;
  }
  async function supported() {
    try {
      return !!(window.isSecureContext && window.PublicKeyCredential && crypto.subtle &&
        await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable());
    } catch (_) { return false; }
  }
  function deviceRecord() {
    try {
      var record = JSON.parse(localStorage.getItem(DEVICE_KEY) || 'null');
      return record && record.version === 1 && record.rpId === location.hostname ? record : null;
    } catch (_) { return null; }
  }
  async function checkResponse(response, challenge, type, authData) {
    var client = JSON.parse(new TextDecoder().decode(response.clientDataJSON));
    if (client.type !== type || client.challenge !== encode(challenge) || client.origin !== location.origin || client.crossOrigin === true) {
      throw new Error('Device response did not match this request.');
    }
    var data = new Uint8Array(authData);
    var rpHash = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(location.hostname)));
    if (data.length < 37 || !rpHash.every(function (byte, i) { return byte === data[i]; }) || (data[32] & 5) !== 5) {
      throw new Error('Device verification was not completed.');
    }
  }
  async function enrollDevice(signal) {
    if (!await supported()) throw new Error('Device unlock is unavailable here. Use a screen PIN instead.');
    var challenge = random(32);
    var credential = await navigator.credentials.create({signal:signal, publicKey:{
      challenge:challenge, rp:{name:'Clear Sky', id:location.hostname},
      user:{id:random(32), name:'clear-sky-device', displayName:'Clear Sky device'},
      pubKeyCredParams:[{type:'public-key', alg:-7}],
      authenticatorSelection:{authenticatorAttachment:'platform', userVerification:'required', residentKey:'discouraged'},
      attestation:'none', timeout:60000
    }});
    if (!credential || !credential.response.getPublicKey || credential.response.getPublicKeyAlgorithm() !== -7) {
      throw new Error('This browser cannot save device unlock. Use a screen PIN instead.');
    }
    var key = credential.response.getPublicKey();
    if (!key) throw new Error('This browser did not provide a device key.');
    await checkResponse(credential.response, challenge, 'webauthn.create', credential.response.getAuthenticatorData());
    await crypto.subtle.importKey('spki', key, {name:'ECDSA', namedCurve:'P-256'}, false, ['verify']);
    return {version:1, rpId:location.hostname, id:encode(credential.rawId), key:encode(key)};
  }
  // WebAuthn's DER ECDSA signature → Web Crypto's fixed-width P-256 format.
  function rawSignature(signature) {
    var bytes = new Uint8Array(signature), position = 2, result = new Uint8Array(64);
    if (bytes[0] !== 48 || bytes[1] !== bytes.length - 2) throw new Error('Invalid device signature.');
    for (var part = 0; part < 2; part++) {
      if (bytes[position++] !== 2) throw new Error('Invalid device signature.');
      var length = bytes[position++], integer = bytes.slice(position, position + length);
      position += length;
      if (integer.length === 33 && integer[0] === 0) integer = integer.slice(1);
      if (!integer.length || integer.length > 32) throw new Error('Invalid device signature.');
      result.set(integer, part * 32 + 32 - integer.length);
    }
    if (position !== bytes.length) throw new Error('Invalid device signature.');
    return result;
  }
  async function unlockDevice(signal) {
    var record = deviceRecord();
    if (!record) throw new Error('Device unlock has not been set up on this browser.');
    var challenge = random(32);
    var credential = await navigator.credentials.get({signal:signal, publicKey:{
      challenge:challenge, rpId:location.hostname, userVerification:'required', timeout:60000,
      allowCredentials:[{type:'public-key', id:decode(record.id), transports:['internal']}]
    }});
    if (!credential || encode(credential.rawId) !== record.id) throw new Error('Unexpected device credential.');
    var response = credential.response;
    await checkResponse(response, challenge, 'webauthn.get', response.authenticatorData);
    var auth = new Uint8Array(response.authenticatorData);
    var clientHash = new Uint8Array(await crypto.subtle.digest('SHA-256', response.clientDataJSON));
    var signed = new Uint8Array(auth.length + clientHash.length);
    signed.set(auth); signed.set(clientHash, auth.length);
    var key = await crypto.subtle.importKey('spki', decode(record.key), {name:'ECDSA', namedCurve:'P-256'}, false, ['verify']);
    if (!await crypto.subtle.verify({name:'ECDSA', hash:'SHA-256'}, key, rawSignature(response.signature), signed)) {
      throw new Error('Device signature could not be verified.');
    }
    return true;
  }
  window.CWUnlock = {
    hasPin:hasPin, setPin:setPin, verifyPin:verifyPin, supported:supported,
    hasDevice:function () { return !!deviceRecord(); }, enrollDevice:enrollDevice, unlockDevice:unlockDevice,
    saveDevice:function (record) { localStorage.setItem(DEVICE_KEY, JSON.stringify(record)); }
  };
})();
