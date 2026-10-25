/* Survivor Incident Diary: Offline-first capture, canvas compression,
   SHA-256 integrity verification, and dual-gated privacy. */
(function (global) {
  'use strict';

  var DB_NAME = 'clear-sky-diary-queue';
  var STORE_NAME = 'diary_entries';
  var DEVICE_TOKEN = 'demo-device';
  var V2_MAX_PHOTO_BYTES = 2 * 1024 * 1024;

  var dbPromise = null;
  var currentPhotoBlob = null;
  var currentPhotoDataUrl = null;
  var currentPhotoHash = null;
  var currentObjectUrl = null;
  var detailObjectUrl = null;
  var activeDetailEntryId = null;
  var globalDiaryConsentActive = null;
  var isUploading = false;
  var retryTimer = null, retryDelay = 5000;
  var detailGeneration = 0;
  var cleanupPendingIds = new Set();

  // DOM elements
  var noteInput, charCount, addPhotoBtn, photoInput, previewWrap, photoPreview,
      photoSizeInfo, removePhotoBtn, shareToggle, consentBadge, saveBtn,
      statusBanner, entriesList, syncRefreshBtn, quickExitBtn,
      detailSection, detailTitle, detailCapturedAt, detailReceivedAt,
      detailShareStatus, detailConsentNote, detailHash, detailNote,
      detailPhotoWrap, detailPhotoImg, detailShareBtn, detailCloseBtn, detailStatus;

  function $(id) {
    return document.getElementById(id);
  }

  function canonicalNote(value) {
    if (typeof value !== 'string') return '';
    return value.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  }

  function bufferToHex(buffer) {
    var bytes = new Uint8Array(buffer);
    var hex = '';
    for (var i = 0; i < bytes.length; i++) {
      var h = bytes[i].toString(16);
      hex += (h.length === 1 ? '0' + h : h);
    }
    return hex;
  }

  function computeSha256(arrayBuffer) {
    if (crypto && crypto.subtle && crypto.subtle.digest) {
      return crypto.subtle.digest('SHA-256', arrayBuffer).then(bufferToHex);
    }
    return Promise.reject(new Error('Web Crypto API required for integrity hash'));
  }

  function computeNoteSha256(note) {
    var encoder = new TextEncoder();
    var bytes = encoder.encode(canonicalNote(note));
    return computeSha256(bytes.buffer);
  }

  function computeEntryFingerprint(contractVersion, noteSha256, photoSha256, capturedAt, shared) {
    var payload = JSON.stringify({
      captured_at: capturedAt || null,
      note_sha256: noteSha256,
      photo_sha256: photoSha256 || null,
      shared: Boolean(shared),
      v: Number(contractVersion)
    });
    var encoder = new TextEncoder();
    var bytes = encoder.encode(payload);
    return computeSha256(bytes.buffer);
  }

  function dataUrlToBlob(dataUrl) {
    if (!dataUrl || typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/jpeg;base64,')) {
      return null;
    }
    var base64 = dataUrl.split(',', 2)[1];
    var binary = atob(base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new Blob([bytes], { type: 'image/jpeg' });
  }

  function openDb() {
    if (!dbPromise) {
      dbPromise = new Promise(function (resolve, reject) {
        var req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = function () {
          if (!req.result.objectStoreNames.contains(STORE_NAME)) {
            req.result.createObjectStore(STORE_NAME, { keyPath: 'client_id' });
          }
        };
        req.onerror = req.onblocked = function () {
          dbPromise = null;
          reject(new Error('Local storage unavailable'));
        };
        req.onsuccess = function () {
          var db = req.result;
          if (typeof navigator !== 'undefined' && navigator.storage && navigator.storage.persist) {
            navigator.storage.persist().catch(function () {});
          }
          db.onversionchange = function () {
            db.close();
            dbPromise = null;
          };
          resolve(db);
        };
      });
    }
    return dbPromise;
  }

  function queueItem(item) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readwrite');
        var store = tx.objectStore(STORE_NAME);
        store.put(item);
        tx.oncomplete = function () { resolve(item); };
        tx.onerror = tx.onabort = function () { reject(new Error('Local storage unavailable')); };
      });
    });
  }

  function getQueuedItems() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readonly');
        var store = tx.objectStore(STORE_NAME);
        var req = store.getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(new Error('Queue read failed')); };
      });
    });
  }

  function removeQueuedItem(clientId) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readwrite');
        var store = tx.objectStore(STORE_NAME);
        store.delete(clientId);
        tx.oncomplete = function () {
          cleanupPendingIds.delete(clientId);
          resolve();
        };
        tx.onerror = function () { reject(new Error('Queue delete failed')); };
      });
    });
  }

  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  }

  function showStatus(message, type) {
    if (!statusBanner) return;
    statusBanner.hidden = false;
    statusBanner.className = 'status-banner status-' + (type || 'saving');
    statusBanner.textContent = message;
  }

  function hideStatus() {
    if (statusBanner) statusBanner.hidden = true;
  }

  function showDetailStatus(message, type) {
    if (!detailStatus) return;
    detailStatus.hidden = !message;
    detailStatus.className = 'status-banner status-' + (type || 'saving');
    detailStatus.textContent = message || '';
  }

  function cleanPreview() {
    if (currentObjectUrl) {
      URL.revokeObjectURL(currentObjectUrl);
      currentObjectUrl = null;
    }
    currentPhotoBlob = null;
    currentPhotoDataUrl = null;
    currentPhotoHash = null;
    if (photoInput) photoInput.value = '';
    if (photoPreview) photoPreview.removeAttribute('src');
    if (previewWrap) previewWrap.hidden = true;
  }

  function closeEntryDetail() {
    detailGeneration += 1;
    activeDetailEntryId = null;
    if (detailObjectUrl) {
      URL.revokeObjectURL(detailObjectUrl);
      detailObjectUrl = null;
    }
    if (detailPhotoImg) detailPhotoImg.removeAttribute('src');
    if (detailPhotoWrap) detailPhotoWrap.hidden = true;
    if (detailNote) detailNote.textContent = '';
    if (detailCapturedAt) detailCapturedAt.textContent = '';
    if (detailReceivedAt) detailReceivedAt.textContent = '';
    if (detailShareStatus) detailShareStatus.textContent = '';
    if (detailConsentNote) detailConsentNote.textContent = '';
    if (detailHash) detailHash.textContent = '';
    showDetailStatus('', 'saving');
    if (detailSection) detailSection.hidden = true;
  }

  function clearSensitiveView() {
    if (noteInput) noteInput.value = '';
    if (charCount) charCount.textContent = '0 / 4000';
    cleanPreview();
    closeEntryDetail();
    hideStatus();
    if (entriesList) entriesList.replaceChildren();
  }

  function quickExit(event) {
    if (event && event.preventDefault) event.preventDefault();
    clearSensitiveView();
    location.replace('/survivor/cover.html');
  }

  function stripJpegMetadataSegments(arrayBuffer) {
    var bytes = new Uint8Array(arrayBuffer);
    if (bytes.length < 4 || bytes[0] !== 0xFF || bytes[1] !== 0xD8) {
      return arrayBuffer;
    }
    var chunks = [bytes.subarray(0, 2)];
    var total = 2;
    var pos = 2;
    while (pos + 1 < bytes.length) {
      if (bytes[pos] !== 0xFF) {
        chunks.push(bytes.subarray(pos));
        total += bytes.length - pos;
        break;
      }
      while (pos + 1 < bytes.length && bytes[pos + 1] === 0xFF) {
        pos++;
      }
      var marker = bytes[pos + 1];
      if (marker === 0xD9 || marker === 0xDA) {
        chunks.push(bytes.subarray(pos));
        total += bytes.length - pos;
        break;
      }
      if ((marker >= 0xD0 && marker <= 0xD8) || marker === 0x01) {
        chunks.push(bytes.subarray(pos, pos + 2));
        total += 2;
        pos += 2;
        continue;
      }
      if (pos + 3 >= bytes.length) {
        chunks.push(bytes.subarray(pos));
        total += bytes.length - pos;
        break;
      }
      var segLen = (bytes[pos + 2] << 8) | bytes[pos + 3];
      if (segLen < 2 || pos + 2 + segLen > bytes.length) {
        chunks.push(bytes.subarray(pos));
        total += bytes.length - pos;
        break;
      }
      var isProhibited = (marker >= 0xE1 && marker <= 0xEF) || marker === 0xFE;
      if (!isProhibited) {
        chunks.push(bytes.subarray(pos, pos + 2 + segLen));
        total += 2 + segLen;
      }
      pos += 2 + segLen;
    }
    var out = new Uint8Array(total);
    var offset = 0;
    for (var i = 0; i < chunks.length; i++) {
      out.set(chunks[i], offset);
      offset += chunks[i].length;
    }
    return out.buffer;
  }

  function encodeCanvasJpeg(canvas, qualities, index, callback) {
    var q = qualities[index];
    canvas.toBlob(function (blob) {
      if (!blob) {
        callback(null);
        return;
      }
      blob.arrayBuffer().then(function (rawBuf) {
        var cleanBuf = stripJpegMetadataSegments(rawBuf);
        var cleanBlob = new Blob([cleanBuf], { type: 'image/jpeg' });
        if (cleanBlob.size <= V2_MAX_PHOTO_BYTES || index + 1 >= qualities.length) {
          callback(cleanBlob, cleanBuf);
          return;
        }
        encodeCanvasJpeg(canvas, qualities, index + 1, callback);
      }).catch(function () {
        callback(null);
      });
    }, 'image/jpeg', q);
  }

  function processImageFile(file) {
    if (!file) return;
    if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) {
      showStatus('Unsupported image format. Please select a JPEG, PNG, or WebP photo.', 'error');
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      showStatus('Photo file is too large (over 15 MB). Please select a smaller photo.', 'error');
      return;
    }

    showStatus('Processing and stripping photo metadata…', 'saving');

    var tempUrl = URL.createObjectURL(file);
    var img = new Image();
    img.onerror = function () {
      URL.revokeObjectURL(tempUrl);
      showStatus('Failed to read photo. The file may be corrupt.', 'error');
    };
    img.onload = function () {
      URL.revokeObjectURL(tempUrl);
      var maxEdge = 1280;
      var width = img.width;
      var height = img.height;

      if (width > maxEdge || height > maxEdge) {
        if (width > height) {
          height = Math.round((height * maxEdge) / width);
          width = maxEdge;
        } else {
          width = Math.round((width * maxEdge) / height);
          height = maxEdge;
        }
      }

      var canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, width, height);

      encodeCanvasJpeg(canvas, [0.8, 0.65, 0.5], 0, function (blob, cleanBuf) {
        if (!blob || !cleanBuf) {
          showStatus('Compression failed. Please try another photo.', 'error');
          return;
        }
        if (blob.size > V2_MAX_PHOTO_BYTES) {
          showStatus('Compressed photo exceeds the 2 MB limit. Please select a smaller photo.', 'error');
          return;
        }

        currentPhotoBlob = blob;
        computeSha256(cleanBuf).then(function (hash) {
          currentPhotoHash = hash;

          var reader = new FileReader();
          reader.onloadend = function () {
            currentPhotoDataUrl = reader.result;

            if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
            currentObjectUrl = URL.createObjectURL(blob);
            photoPreview.src = currentObjectUrl;
            photoSizeInfo.textContent = 'Size: ' + formatBytes(blob.size) +
              ' (' + width + '×' + height + 'px, EXIF metadata stripped)';
            previewWrap.hidden = false;
            hideStatus();
          };
          reader.readAsDataURL(blob);
        }).catch(function () {
          showStatus('Error computing photo integrity digest.', 'error');
        });
      });
    };
    img.src = tempUrl;
  }

  function extractDiaryConsent(data) {
    if (!data || !data.consents) return null;
    if (Array.isArray(data.consents)) {
      var found = data.consents.find(function (c) { return c && c.item === 'diary_sharing'; });
      return found || null;
    }
    return data.consents['diary_sharing'] || null;
  }

  function fetchGlobalConsent() {
    return fetch('/api/consents', {
      headers: { 'X-Device-Token': DEVICE_TOKEN },
      cache: 'no-store'
    })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (data) {
      if (!data) return;
      var diaryConsent = extractDiaryConsent(data);
      globalDiaryConsentActive = Boolean(diaryConsent && diaryConsent.active);
      if (!consentBadge) return;
      consentBadge.hidden = false;
      if (globalDiaryConsentActive) {
        consentBadge.className = 'consent-status-note consent-active';
        consentBadge.textContent = 'Diary sharing consent is active';
      } else {
        consentBadge.className = 'consent-status-note consent-revoked';
        consentBadge.textContent = 'Diary sharing consent is currently disabled';
      }
    })
    .catch(function () {});
  }

  function verifyReceipt(item, receipt) {
    if (!receipt || receipt.stored !== true) return false;
    if (!Number.isInteger(receipt.id) || receipt.id < 1) return false;
    if (receipt.client_id !== item.client_id) return false;
    if (receipt.file_hash !== item.file_hash) return false;
    if (typeof receipt.shared !== 'boolean') return false;
    if (typeof receipt.has_photo !== 'boolean' || receipt.has_photo !== Boolean(item.has_photo)) return false;
    if (typeof receipt.received_at !== 'string' || !receipt.received_at.length) return false;
    if (item.contract_version === 2) {
      if (receipt.contract_version !== 2) return false;
      if (receipt.note_sha256 !== item.note_sha256) return false;
      if ((receipt.photo_sha256 || null) !== (item.photo_sha256 || null)) return false;
      if (receipt.entry_fingerprint !== item.entry_fingerprint) return false;
      if (receipt.captured_at !== item.captured_at) return false;
    }
    return true;
  }

  function buildUploadRequest(item) {
    var version = item.contract_version || 1;
    if (version === 2 && item.has_photo) {
      var blob = (item.photo_blob instanceof Blob) ? item.photo_blob : dataUrlToBlob(item.photo_data);
      if (blob) {
        var form = new FormData();
        form.append('client_id', item.client_id);
        form.append('contract_version', '2');
        form.append('note', item.note || '');
        form.append('shared', item.shared ? 'true' : 'false');
        if (item.captured_at) form.append('captured_at', item.captured_at);
        if (item.file_hash) form.append('file_hash', item.file_hash);
        if (item.note_sha256) form.append('note_sha256', item.note_sha256);
        if (item.photo_sha256) form.append('photo_sha256', item.photo_sha256);
        if (item.entry_fingerprint) form.append('entry_fingerprint', item.entry_fingerprint);
        form.append('photo', blob, 'evidence.jpg');
        return {
          headers: { 'X-Device-Token': DEVICE_TOKEN },
          body: form
        };
      }
    }

    var payload = {
      client_id: item.client_id,
      contract_version: version,
      note: item.note || '',
      shared: Boolean(item.shared),
      file_hash: item.file_hash
    };
    if (version === 2) {
      payload.captured_at = item.captured_at;
      payload.note_sha256 = item.note_sha256;
      if (item.photo_sha256) payload.photo_sha256 = item.photo_sha256;
      payload.entry_fingerprint = item.entry_fingerprint;
      if (item.photo_data) payload.photo_data = item.photo_data;
    } else {
      payload.photo_data = item.photo_data;
      payload.created_at = item.created_at;
    }

    return {
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN
      },
      body: JSON.stringify(payload)
    };
  }

  function markQueuedItemStatus(item, status, errorMsg) {
    var updated = Object.assign({}, item, {
      status: status,
      last_error: errorMsg || null
    });
    if (status === 'upload_failed') {
      clearTimeout(retryTimer);
      retryTimer = setTimeout(function () { flushQueue(false); }, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 60000);
    }
    return queueItem(updated).catch(function () {});
  }

  function uploadSingleEntry(item) {
    if (item.status === 'cleanup_pending' || cleanupPendingIds.has(item.client_id)) {
      return removeQueuedItem(item.client_id).then(function () {
        return { success: true, receipt: item.verified_receipt || { id: 0 } };
      });
    }

    var reqInit = buildUploadRequest(item);
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 20000);
    return fetch('/api/diary', {
      signal: controller.signal,
      method: 'POST',
      headers: reqInit.headers,
      body: reqInit.body,
      cache: 'no-store'
    })
    .finally(function () { clearTimeout(timeout); })
    .then(function (res) {
      if (res.status === 201 || res.status === 200) {
        return res.json().then(function (receipt) {
          if (!verifyReceipt(item, receipt)) {
            return markQueuedItemStatus(item, 'upload_failed', 'Receipt verification failed').then(function () {
              throw new Error('Receipt verification failed');
            });
          }
          return removeQueuedItem(item.client_id).then(function () {
            return { success: true, receipt: receipt };
          }, function () {
            cleanupPendingIds.add(item.client_id);
            return markQueuedItemStatus(
              Object.assign({}, item, { verified_receipt: receipt }),
              'cleanup_pending',
              null
            ).then(function () {
              return { success: true, receipt: receipt };
            });
          });
        });
      }

      return res.json().catch(function () { return {}; }).then(function (errData) {
        var code = errData.error || ('Server error ' + res.status);
        if (res.status === 401) {
          return markQueuedItemStatus(item, 'auth_expired', 'Authentication expired').then(function () {
            throw new Error(code);
          });
        }
        if (res.status === 400 || res.status === 403 || res.status === 409 || res.status === 413 || res.status === 422) {
          return markQueuedItemStatus(item, 'needs_attention', code).then(function () {
            throw new Error(code);
          });
        }
        return markQueuedItemStatus(item, 'upload_failed', code).then(function () {
          throw new Error(code);
        });
      });
    }, function (networkErr) {
      return markQueuedItemStatus(item, 'upload_failed', 'Upload failed — will retry').then(function () {
        throw networkErr;
      });
    });
  }

  function flushQueue(forcePermanent) {
    if (isUploading) return Promise.resolve();
    isUploading = true;

    return getQueuedItems().then(function (items) {
      if (!items.length) {
        isUploading = false;
        return;
      }

      var sequence = Promise.resolve();
      items.forEach(function (item) {
        if (!forcePermanent && (item.status === 'auth_expired' || item.status === 'needs_attention')) {
          return;
        }
        sequence = sequence.then(function () {
          return uploadSingleEntry(item).catch(function () {});
        });
      });

      return sequence.then(function () {
        isUploading = false;
        return renderEntries();
      });
    }).catch(function () {
      isUploading = false;
    });
  }

  function saveEntry() {
    var note = canonicalNote(noteInput ? noteInput.value : '');
    if (!note && !currentPhotoDataUrl && !currentPhotoBlob) {
      showStatus('Please write a note or attach a photo before saving.', 'error');
      return;
    }

    saveBtn.disabled = true;
    showStatus('Saving on this phone…', 'saving');

    var clientId = (crypto.randomUUID ? crypto.randomUUID() : 'diary-' + Date.now() + '-' + Math.random().toString(36).slice(2));
    var capturedAt = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    var isShared = Boolean(shareToggle && shareToggle.checked);
    var photoBlobToSave = currentPhotoBlob;
    var photoDataUrlToSave = currentPhotoDataUrl;
    var photoSha256 = currentPhotoHash || null;

    computeNoteSha256(note).then(function (noteSha256) {
      return computeEntryFingerprint(2, noteSha256, photoSha256, capturedAt, isShared).then(function (fingerprint) {
        var fileHash = photoSha256 || noteSha256;
        var entryRecord = {
          client_id: clientId,
          contract_version: 2,
          note: note,
          photo_blob: photoBlobToSave,
          photo_data: photoDataUrlToSave,
          note_sha256: noteSha256,
          photo_sha256: photoSha256,
          file_hash: fileHash,
          entry_fingerprint: fingerprint,
          shared: isShared,
          has_photo: Boolean(photoSha256),
          captured_at: capturedAt,
          created_at: capturedAt,
          status: 'queued'
        };

        return queueItem(entryRecord).then(function () {
          showStatus('Saved on phone (Pending upload)', 'local');

          if (noteInput) noteInput.value = '';
          if (charCount) charCount.textContent = '0 / 4000';
          cleanPreview();
          renderEntries();

          showStatus('Uploading…', 'saving');
          return uploadSingleEntry(entryRecord).then(function (res) {
            if (res && res.success) {
              showStatus('Saved to account (Verified receipt #' + res.receipt.id + ')', 'server');
              setTimeout(hideStatus, 4000);
              return renderEntries();
            }
          }).catch(function () {
            showStatus('Upload failed — will retry when connected.', 'local');
            return renderEntries();
          });
        });
      });
    }).catch(function (err) {
      showStatus(err && err.message ? err.message : 'Local storage unavailable', 'error');
    }).finally(function () {
      saveBtn.disabled = false;
    });
  }

  function populateDetailSection(entry) {
    if (!detailSection || !entry) return;
    activeDetailEntryId = entry.id;
    detailSection.hidden = false;
    if (detailTitle) detailTitle.textContent = 'Saved Entry (Receipt #' + entry.id + ')';
    if (detailCapturedAt) detailCapturedAt.textContent = 'Captured: ' + (entry.captured_at || 'Unknown');
    if (detailReceivedAt) detailReceivedAt.textContent = 'Received by vault: ' + (entry.received_at || 'Unknown');
    if (detailShareStatus) {
      detailShareStatus.textContent = 'Entry visibility: ' + (entry.shared ? 'Shared with responder' : 'Private (Only you)');
    }
    if (detailConsentNote) {
      if (globalDiaryConsentActive === false) {
        detailConsentNote.textContent = 'Global diary sharing consent is currently off — responders cannot view any diary entries until global consent is enabled.';
      } else {
        detailConsentNote.textContent = 'Responders can view this entry only when both global diary sharing consent and this entry toggle are enabled.';
      }
    }
    if (detailHash) {
      detailHash.textContent = 'SHA-256: ' + (entry.file_hash || '');
    }
    if (detailNote) {
      detailNote.textContent = entry.note || '(No text note — photo entry)';
    }
    if (detailShareBtn) {
      detailShareBtn.textContent = entry.shared ? 'Make private' : 'Share with responder';
      detailShareBtn.onclick = function () {
        toggleEntryShare(entry.id, !entry.shared);
      };
    }

    if (detailObjectUrl) {
      URL.revokeObjectURL(detailObjectUrl);
      detailObjectUrl = null;
    }
    if (entry.has_photo && entry.photo_url) {
      fetch(entry.photo_url, {
        headers: { 'X-Device-Token': DEVICE_TOKEN },
        cache: 'no-store'
      })
      .then(function (r) {
        if (!r.ok) throw new Error('Photo unavailable');
        return r.blob();
      })
      .then(function (blob) {
        if (activeDetailEntryId !== entry.id) return;
        detailObjectUrl = URL.createObjectURL(blob);
        if (detailPhotoImg) detailPhotoImg.src = detailObjectUrl;
        if (detailPhotoWrap) detailPhotoWrap.hidden = false;
      })
      .catch(function () {
        if (detailPhotoWrap) detailPhotoWrap.hidden = true;
      });
    } else {
      if (detailPhotoImg) detailPhotoImg.removeAttribute('src');
      if (detailPhotoWrap) detailPhotoWrap.hidden = true;
    }
  }

  function openEntryDetail(entryId) {
    var generation = ++detailGeneration;
    showDetailStatus('Loading entry…', 'saving');
    return fetch('/api/diary/' + encodeURIComponent(entryId), {
      headers: { 'X-Device-Token': DEVICE_TOKEN },
      cache: 'no-store'
    })
    .then(function (res) {
      if (!res.ok) throw new Error('Could not load entry');
      return res.json();
    })
    .then(function (data) {
      showDetailStatus('', 'saving');
      if (generation === detailGeneration && !document.hidden && data && data.entry) {
        populateDetailSection(data.entry);
      }
    })
    .catch(function () {
      showDetailStatus('Could not load saved entry details. Reconnect and try again.', 'error');
    });
  }

  function toggleEntryShare(entryId, targetShared) {
    showDetailStatus('Updating sharing state…', 'saving');
    return fetch('/api/diary/' + encodeURIComponent(entryId) + '/share', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN
      },
      body: JSON.stringify({ shared: Boolean(targetShared) }),
      cache: 'no-store'
    })
    .then(function (res) {
      if (!res.ok) throw new Error('Share update failed');
      return res.json();
    })
    .then(function (data) {
      showDetailStatus('', 'saving');
      if (data && data.entry && activeDetailEntryId === entryId) {
        populateDetailSection(data.entry);
      }
      return renderEntries();
    })
    .catch(function () {
      // Uncertain timeout/network error: refresh authoritative server state before claiming outcome
      return fetch('/api/diary/' + encodeURIComponent(entryId), {
        headers: { 'X-Device-Token': DEVICE_TOKEN },
        cache: 'no-store'
      })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (refreshed) {
        if (refreshed && refreshed.entry) {
          if (activeDetailEntryId === entryId) {
            populateDetailSection(refreshed.entry);
          }
          showDetailStatus('Refreshed current sharing setting from server.', 'local');
        } else {
          showDetailStatus('Could not confirm sharing change. Reconnect and refresh.', 'error');
        }
        return renderEntries();
      })
      .catch(function () {
        showDetailStatus('Could not confirm sharing change. Reconnect and refresh.', 'error');
      });
    });
  }

  function describeQueuedBadge(item) {
    if (item.status === 'auth_expired') {
      return { text: 'Authentication expired — sign in / reconnect', cls: 'entry-badge badge-error' };
    }
    if (item.status === 'needs_attention') {
      return { text: 'Entry needs attention (' + (item.last_error || 'rejected') + ')', cls: 'entry-badge badge-error' };
    }
    if (item.status === 'upload_failed') {
      return { text: 'Saved on phone (Pending upload — will retry)', cls: 'entry-badge badge-queued' };
    }
    return { text: 'Saved on phone (Pending upload)', cls: 'entry-badge badge-queued' };
  }

  function renderEntries() {
    if (!entriesList) return Promise.resolve();

    return Promise.all([
      getQueuedItems().catch(function () { return []; }),
      fetch('/api/diary', { headers: { 'X-Device-Token': DEVICE_TOKEN }, cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : { entries: [] }; })
        .catch(function () { return { entries: [] }; })
    ]).then(function (results) {
      var queued = (results[0] || []).filter(function (q) {
        return q.status !== 'cleanup_pending' && !cleanupPendingIds.has(q.client_id);
      });
      var serverEntries = (results[1] && results[1].entries) || [];

      entriesList.replaceChildren();

      if (!queued.length && !serverEntries.length) {
        var empty = document.createElement('p');
        empty.style.fontSize = '0.85rem';
        empty.style.color = 'var(--dusty-blue)';
        empty.style.textAlign = 'center';
        empty.style.padding = '1rem 0';
        empty.textContent = 'No diary entries saved yet.';
        entriesList.appendChild(empty);
        return;
      }

      queued.forEach(function (q) {
        var card = document.createElement('div');
        card.className = 'entry-item';

        var header = document.createElement('div');
        header.className = 'entry-header';

        var badgeInfo = describeQueuedBadge(q);
        var badge = document.createElement('span');
        badge.className = badgeInfo.cls;
        badge.textContent = badgeInfo.text;

        var time = document.createElement('span');
        time.className = 'entry-time';
        var ts = q.captured_at || q.created_at;
        time.textContent = ts ? ts.replace('T', ' ').slice(0, 16) : 'Just now';

        header.appendChild(badge);
        header.appendChild(time);
        card.appendChild(header);

        if (q.note) {
          var noteP = document.createElement('p');
          noteP.className = 'entry-note-preview';
          noteP.textContent = q.note;
          card.appendChild(noteP);
        }

        var meta = document.createElement('div');
        meta.className = 'entry-meta-row';

        var sPhoto = document.createElement('span');
        sPhoto.textContent = q.has_photo ? '📷 Photo attached' : '📝 Note only';
        var sShare = document.createElement('span');
        sShare.textContent = '• ' + (q.shared ? 'Shared with responder' : 'Private (Only you)');
        var sHash = document.createElement('span');
        sHash.textContent = '• SHA-256: ' + (q.file_hash ? q.file_hash.slice(0, 8) : '...') + '…';

        meta.appendChild(sPhoto);
        meta.appendChild(sShare);
        meta.appendChild(sHash);
        card.appendChild(meta);

        entriesList.appendChild(card);
      });

      serverEntries.forEach(function (s) {
        var card = document.createElement('div');
        card.className = 'entry-item';
        card.dataset.entryId = String(s.id);

        var header = document.createElement('div');
        header.className = 'entry-header';

        var badge = document.createElement('span');
        badge.className = 'entry-badge badge-stored';
        badge.textContent = 'Saved to account (Receipt #' + s.id + ')';

        var time = document.createElement('span');
        time.className = 'entry-time';
        var ts = s.captured_at || s.created_at;
        time.textContent = ts ? ts.replace('T', ' ').slice(0, 16) : '';

        header.appendChild(badge);
        header.appendChild(time);
        card.appendChild(header);

        var meta = document.createElement('div');
        meta.className = 'entry-meta-row';

        var sPhoto = document.createElement('span');
        sPhoto.textContent = s.has_photo ? '📷 Photo stored' : '📝 Note stored';
        var sShare = document.createElement('span');
        sShare.textContent = '• ' + (s.shared ? 'Shared with responder' : 'Private (Only you)');
        var sHash = document.createElement('span');
        sHash.textContent = '• SHA-256: ' + (s.file_hash ? s.file_hash.slice(0, 8) : '') + '…';

        meta.appendChild(sPhoto);
        meta.appendChild(sShare);
        meta.appendChild(sHash);
        card.appendChild(meta);

        var actions = document.createElement('div');
        actions.className = 'entry-actions';

        var viewBtn = document.createElement('button');
        viewBtn.type = 'button';
        viewBtn.className = 'btn btn-outline btn-view-entry';
        viewBtn.textContent = 'View entry';
        viewBtn.addEventListener('click', function () {
          openEntryDetail(s.id);
        });

        var shareBtn = document.createElement('button');
        shareBtn.type = 'button';
        shareBtn.className = 'btn btn-outline btn-toggle-share';
        shareBtn.textContent = s.shared ? 'Make private' : 'Share with responder';
        shareBtn.addEventListener('click', function () {
          toggleEntryShare(s.id, !s.shared);
        });

        actions.appendChild(viewBtn);
        actions.appendChild(shareBtn);
        card.appendChild(actions);

        entriesList.appendChild(card);
      });
    });
  }

  function init() {
    noteInput = $('diary-note');
    charCount = $('char-count');
    addPhotoBtn = $('add-photo-btn');
    photoInput = $('diary-photo-input');
    previewWrap = $('photo-preview-wrap');
    photoPreview = $('photo-preview');
    photoSizeInfo = $('photo-size-info');
    removePhotoBtn = $('remove-photo-btn');
    shareToggle = $('diary-share-toggle');
    consentBadge = $('consent-status-badge');
    saveBtn = $('diary-save-btn');
    statusBanner = $('diary-status');
    entriesList = $('diary-entries-list');
    syncRefreshBtn = $('sync-refresh-btn');
    quickExitBtn = $('quick-exit-btn');

    detailSection = $('diary-entry-detail');
    detailTitle = $('detail-title');
    detailCapturedAt = $('detail-captured-at');
    detailReceivedAt = $('detail-received-at');
    detailShareStatus = $('detail-share-status');
    detailConsentNote = $('detail-consent-note');
    detailHash = $('detail-hash');
    detailNote = $('detail-note');
    detailPhotoWrap = $('detail-photo-wrap');
    detailPhotoImg = $('detail-photo-img');
    detailShareBtn = $('detail-share-btn');
    detailCloseBtn = $('detail-close-btn');
    detailStatus = $('detail-status');

    if (noteInput && charCount) {
      noteInput.addEventListener('input', function () {
        charCount.textContent = noteInput.value.length + ' / 4000';
      });
    }

    if (addPhotoBtn && photoInput) {
      addPhotoBtn.addEventListener('click', function () {
        photoInput.click();
      });
      photoInput.addEventListener('change', function () {
        if (photoInput.files && photoInput.files[0]) {
          processImageFile(photoInput.files[0]);
        }
      });
    }

    if (removePhotoBtn) {
      removePhotoBtn.addEventListener('click', function () {
        cleanPreview();
      });
    }

    if (detailCloseBtn) {
      detailCloseBtn.addEventListener('click', function () {
        closeEntryDetail();
      });
    }

    if (saveBtn) {
      saveBtn.addEventListener('click', saveEntry);
    }

    if (syncRefreshBtn) {
      syncRefreshBtn.addEventListener('click', function () {
        syncRefreshBtn.disabled = true;
        flushQueue(true).finally(function () {
          syncRefreshBtn.disabled = false;
        });
      });
    }

    if (quickExitBtn) {
      quickExitBtn.addEventListener('click', quickExit);
    }

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') quickExit(event);
    });

    window.addEventListener('pagehide', function () {
      clearSensitiveView();
    });

    window.addEventListener('pageshow', function (event) {
      if (event.persisted) {
        fetchGlobalConsent();
        renderEntries();
        flushQueue(false);
      }
    });

    window.addEventListener('online', function () {
      flushQueue(false);
    });

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        closeEntryDetail();
        cleanPreview();
      } else {
        fetchGlobalConsent();
        renderEntries();
        flushQueue(false);
      }
    });

    fetchGlobalConsent();
    renderEntries();
    flushQueue(false);
  }

  document.addEventListener('DOMContentLoaded', init);

  global.CWDiary = {
    quickExit: quickExit,
    flushQueue: flushQueue,
    saveEntry: saveEntry,
    getQueuedItems: getQueuedItems,
    canonicalNote: canonicalNote,
    computeNoteSha256: computeNoteSha256,
    computeEntryFingerprint: computeEntryFingerprint,
    verifyReceipt: verifyReceipt,
    openEntryDetail: openEntryDetail,
    toggleEntryShare: toggleEntryShare
  };
})(window);
