/* Display preference only; matches the partner portal's session setting. */
(function () {
  'use strict';
  var system = window.matchMedia('(prefers-color-scheme: dark)');
  var root = document.documentElement;
  try {
    var saved = sessionStorage.getItem('avenra-theme');
    if (saved === 'light' || saved === 'dark') root.dataset.theme = saved;
  } catch (_) {}

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.createElement('button');
    button.type = 'button';
    button.id = 'theme-toggle';
    button.className = 'theme-toggle';
    var header = document.querySelector('.pwa-header');
    if (header) {
      var actions = document.createElement('div');
      actions.className = 'pwa-actions';
      actions.appendChild(button);
      var exit = header.querySelector('.quick-exit-pill');
      if (exit) actions.appendChild(exit);
      header.appendChild(actions);
    } else {
      document.querySelector('main').prepend(button);
    }

    function update() {
      var dark = root.dataset.theme ? root.dataset.theme === 'dark' : system.matches;
      button.textContent = dark ? 'Light theme' : 'Dark theme';
      button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
      var color = document.querySelector('meta[name="theme-color"]');
      if (color) color.content = dark ? '#1c191e' : '#f5f2eb';
    }
    button.addEventListener('click', function () {
      var dark = root.dataset.theme ? root.dataset.theme === 'dark' : system.matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      try { sessionStorage.setItem('avenra-theme', root.dataset.theme); } catch (_) {}
      update();
    });
    if (system.addEventListener) system.addEventListener('change', update);
    else system.addListener(update);
    update();
  });
})();
