/* Survivor Incident Diary: Offline-first capture, canvas compression,
   SHA-256 integrity verification, and dual-gated privacy. */
(function (global) {
  'use strict';

  var DB_NAME = 'clear-sky-diary-queue';
  var STORE_NAME = 'diary_entries';
  var DEVICE_TOKEN = 'demo-device';

  var dbPromise = null;
  var currentPhotoBlob = null;
  var currentPhotoDataUrl = null;
  var currentPhotoHash = null;
  var currentObjectUrl = null;
  var originalFileSize = 0;
  var isUploading = false;

  // DOM elements
  var noteInput, charCount, addPhotoBtn, photoInput, previewWrap, photoPreview,
      photoSizeInfo, removePhotoBtn, shareToggle, consentBadge, saveBtn,
      statusBanner, entriesList, syncRefreshBtn, quickExitBtn;

  function $(id) {
    return document.getElementById(id);
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
          reject(new Error('IndexedDB unavailable'));
        };
        req.onsuccess = function () {
          var db = req.result;
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
        tx.onerror = tx.onabort = function () { reject(new Error('Queue save failed')); };
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
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(new Error('Queue delete failed')); };
      });
    });
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

  function computeTextHash(text) {
    var encoder = new TextEncoder();
    var bytes = encoder.encode(text.trim());
    return computeSha256(bytes.buffer);
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

  function cleanPreview() {
    if (currentObjectUrl) {
      URL.revokeObjectURL(currentObjectUrl);
      currentObjectUrl = null;
    }
    currentPhotoBlob = null;
    currentPhotoDataUrl = null;
    currentPhotoHash = null;
    originalFileSize = 0;
    if (photoInput) photoInput.value = '';
    if (photoPreview) photoPreview.src = '';
    if (previewWrap) previewWrap.hidden = true;
  }

  function quickExit() {
    if (noteInput) noteInput.value = '';
    cleanPreview();
    location.replace('/survivor/cover.html');
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

    originalFileSize = file.size;
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
      // Redrawing image onto canvas completely removes all EXIF/GPS/device metadata
      ctx.drawImage(img, 0, 0, width, height);

      canvas.toBlob(function (blob) {
        if (!blob) {
          showStatus('Compression failed. Please try another photo.', 'error');
          return;
        }

        currentPhotoBlob = blob;
        blob.arrayBuffer().then(function (buf) {
          return computeSha256(buf).then(function (hash) {
            currentPhotoHash = hash;

            // Convert to base64 Data URL for JSON payload
            var reader = new FileReader();
            reader.onloadend = function () {
              currentPhotoDataUrl = reader.result;

              // Display preview
              if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
              currentObjectUrl = URL.createObjectURL(blob);
              photoPreview.src = currentObjectUrl;
              photoSizeInfo.textContent = 'Size: ' + formatBytes(blob.size) +
                ' (' + width + '×' + height + 'px, EXIF metadata stripped)';
              previewWrap.hidden = false;
              hideStatus();
            };
            reader.readAsDataURL(blob);
          });
        }).catch(function (err) {
          showStatus('Error computing photo integrity digest.', 'error');
        });
      }, 'image/jpeg', 0.8);
    };
    img.src = tempUrl;
  }

  function fetchGlobalConsent() {
    return fetch('/api/consents', {
      headers: { 'X-Device-Token': DEVICE_TOKEN }
    })
    .then(function (res) { return res.ok ? res.json() : null; })
    .then(function (data) {
      if (!data || !consentBadge) return;
      var diaryConsent = (data.consents || {})['diary_sharing'];
      if (diaryConsent && diaryConsent.active) {
        consentBadge.hidden = false;
        consentBadge.className = 'consent-status-note consent-active';
        consentBadge.textContent = 'Diary sharing consent is active';
      } else {
        consentBadge.hidden = false;
        consentBadge.className = 'consent-status-note consent-revoked';
        consentBadge.textContent = 'Diary sharing consent is currently disabled';
      }
    })
    .catch(function () {});
  }

  function uploadSingleEntry(item) {
    var payload = {
      client_id: item.client_id,
      note: item.note,
      photo_data: item.photo_data,
      file_hash: item.file_hash,
      shared: item.shared,
      created_at: item.created_at
    };

    return fetch('/api/diary', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN
      },
      body: JSON.stringify(payload)
    })
    .then(function (res) {
      if (res.status === 201 || res.status === 200) {
        return res.json().then(function (receipt) {
          // Verify durable receipt integrity
          if (receipt && receipt.stored === true && receipt.id &&
              receipt.client_id === item.client_id &&
              receipt.file_hash === item.file_hash) {
            return removeQueuedItem(item.client_id).then(function () {
              return { success: true, receipt: receipt };
            });
          }
          throw new Error('Receipt verification failed');
        });
      }
      return res.json().catch(function () { return {}; }).then(function (errData) {
        throw new Error(errData.error || 'Server error ' + res.status);
      });
    });
  }

  function flushQueue() {
    if (isUploading) return Promise.resolve();
    isUploading = true;

    return getQueuedItems().then(function (items) {
      if (!items.length) {
        isUploading = false;
        return;
      }

      var sequence = Promise.resolve();
      items.forEach(function (item) {
        sequence = sequence.then(function () {
          return uploadSingleEntry(item).catch(function () {});
        });
      });

      return sequence.then(function () {
        isUploading = false;
        renderEntries();
      });
    }).catch(function () {
      isUploading = false;
    });
  }

  function saveEntry() {
    var note = (noteInput ? noteInput.value : '').trim();
    if (!note && !currentPhotoDataUrl) {
      showStatus('Please write a note or attach a photo before saving.', 'error');
      return;
    }

    saveBtn.disabled = true;
    showStatus('Saving on this phone…', 'saving');

    var clientId = (crypto.randomUUID ? crypto.randomUUID() : 'diary-' + Date.now() + '-' + Math.random().toString(36).slice(2));
    var createdAt = new Date().toISOString();
    var isShared = shareToggle ? shareToggle.checked : false;

    var hashPromise = currentPhotoHash
      ? Promise.resolve(currentPhotoHash)
      : computeTextHash(note);

    hashPromise.then(function (fileHash) {
      var entryRecord = {
        client_id: clientId,
        note: note,
        photo_data: currentPhotoDataUrl,
        file_hash: fileHash,
        shared: isShared,
        has_photo: Boolean(currentPhotoDataUrl),
        created_at: createdAt,
        status: 'queued'
      };

      // 1. Commit to IndexedDB first
      return queueItem(entryRecord).then(function () {
        showStatus('Saved on this phone. Open the app when you reconnect to upload.', 'local');
        
        // Reset form inputs immediately after local commit
        if (noteInput) noteInput.value = '';
        if (charCount) charCount.textContent = '0 / 4000';
        cleanPreview();
        renderEntries();

        // 2. Attempt immediate upload if connected
        return uploadSingleEntry(entryRecord).then(function (res) {
          if (res && res.success) {
            showStatus('Saved to your account (Verified receipt #' + res.receipt.id + ')', 'server');
            setTimeout(hideStatus, 4000);
            renderEntries();
          }
        }).catch(function (err) {
          // Stays safely in IndexedDB for retry
          showStatus('Still on this phone. We’ll retry when the app can connect.', 'local');
          renderEntries();
        });
      });
    }).catch(function (err) {
      showStatus('Failed to save entry: ' + (err.message || 'Storage error'), 'error');
    }).finally(function () {
      saveBtn.disabled = false;
    });
  }

  function renderEntries() {
    if (!entriesList) return;

    Promise.all([
      getQueuedItems().catch(function () { return []; }),
      fetch('/api/diary', { headers: { 'X-Device-Token': DEVICE_TOKEN } })
        .then(function (r) { return r.ok ? r.json() : { entries: [] }; })
        .catch(function () { return { entries: [] }; })
    ]).then(function (results) {
      var queued = results[0] || [];
      var serverEntries = (results[1] && results[1].entries) || [];

      if (!queued.length && !serverEntries.length) {
        entriesList.innerHTML = '<p style="font-size: 0.85rem; color: var(--dusty-blue); text-align: center; padding: 1rem 0;">No diary entries saved yet.</p>';
        return;
      }

      var html = '';

      // Render offline queued items first
      queued.forEach(function (q) {
        html += '<div class="entry-item">';
        html += '  <div class="entry-header">';
        html += '    <span class="entry-badge badge-queued">Saved on phone (Pending upload)</span>';
        html += '    <span class="entry-time">' + (q.created_at ? q.created_at.replace('T', ' ').slice(0, 16) : 'Just now') + '</span>';
        html += '  </div>';
        if (q.note) {
          var safeNote = q.note.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          html += '  <p class="entry-note-preview">' + safeNote + '</p>';
        }
        html += '  <div class="entry-meta-row">';
        html += '    <span>' + (q.has_photo ? '📷 Photo attached' : '📝 Note only') + '</span>';
        html += '    <span>• ' + (q.shared ? 'Shared with responder' : 'Private') + '</span>';
        html += '    <span>• SHA-256: ' + (q.file_hash ? q.file_hash.slice(0, 8) : '...') + '…</span>';
        html += '  </div>';
        html += '</div>';
      });

      // Render verified server receipts
      serverEntries.forEach(function (s) {
        html += '<div class="entry-item">';
        html += '  <div class="entry-header">';
        html += '    <span class="entry-badge badge-stored">Saved to account (Receipt #' + s.id + ')</span>';
        html += '    <span class="entry-time">' + (s.created_at ? s.created_at.replace('T', ' ').slice(0, 16) : '') + '</span>';
        html += '  </div>';
        html += '  <div class="entry-meta-row">';
        html += '    <span>' + (s.has_photo ? '📷 Photo stored' : '📝 Note stored') + '</span>';
        html += '    <span>• ' + (s.shared ? 'Shared with responder' : 'Private') + '</span>';
        html += '    <span>• SHA-256: ' + (s.file_hash ? s.file_hash.slice(0, 8) : '') + '…</span>';
        html += '  </div>';
        html += '</div>';
      });

      entriesList.innerHTML = html;
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

    if (saveBtn) {
      saveBtn.addEventListener('click', saveEntry);
    }

    if (syncRefreshBtn) {
      syncRefreshBtn.addEventListener('click', function () {
        syncRefreshBtn.disabled = true;
        flushQueue().finally(function () {
          syncRefreshBtn.disabled = false;
        });
      });
    }

    if (quickExitBtn) {
      quickExitBtn.addEventListener('click', quickExit);
    }

    // Refresh and auto-sync triggers
    window.addEventListener('online', flushQueue);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        flushQueue();
        fetchGlobalConsent();
      }
    });

    fetchGlobalConsent();
    renderEntries();
    flushQueue();
  }

  document.addEventListener('DOMContentLoaded', init);

  global.CWDiary = {
    quickExit: quickExit,
    flushQueue: flushQueue,
    saveEntry: saveEntry
  };
})(window);
