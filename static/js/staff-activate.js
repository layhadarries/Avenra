/* Secret fragments are never sent in HTTP URLs or retained in browser history. */
(function () {
  'use strict';
  var field = document.getElementById('invite-token');
  if (field && location.hash) {
    var token = location.hash.slice(1);
    history.replaceState(null, '', location.pathname);
    if (/^[A-Za-z0-9_-]{43}$/.test(token)) field.value = token;
  }
})();
