/* Keep recovery secrets out of URLs, referrers and persistent browser storage. */
(function () {
  'use strict';
  var input = document.getElementById('reset-token');
  if (!input) return;
  var token = window.location.hash.slice(1);
  window.history.replaceState(null, '', window.location.pathname);
  if (token) input.value = /^[A-Za-z0-9_-]{43}$/.test(token) ? token : '';
}());
