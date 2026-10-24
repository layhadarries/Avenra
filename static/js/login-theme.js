/* Theme preference only; no account data is stored. */
(function () {
  "use strict";

  const button = document.getElementById("theme-toggle");
  if (!button) return;

  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  let manualChoice = false;

  try {
    const saved = sessionStorage.getItem("avenra-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.dataset.theme = saved;
      manualChoice = true;
    }
  } catch (_) {
    // Theme switching still works if storage is unavailable.
  }

  function updateLabel() {
    const selected = document.documentElement.dataset.theme;
    const dark = selected
      ? selected === "dark"
      : systemTheme.matches;

    button.textContent = dark ? "Light theme" : "Dark theme";
    button.setAttribute(
      "aria-label",
      dark ? "Switch to light theme" : "Switch to dark theme"
    );
  }

  button.hidden = false;
  updateLabel();

  button.addEventListener("click", function () {
    const selected = document.documentElement.dataset.theme;
    const dark = selected
      ? selected === "dark"
      : systemTheme.matches;

    manualChoice = true;
    document.documentElement.dataset.theme = dark ? "light" : "dark";

    try {
      sessionStorage.setItem(
        "avenra-theme",
        document.documentElement.dataset.theme
      );
    } catch (_) {
      // No account or case information is stored.
    }
    updateLabel();
  });

  function followSystem() {
    if (!manualChoice) updateLabel();
  }

  if (systemTheme.addEventListener) {
    systemTheme.addEventListener("change", followSystem);
  } else {
    systemTheme.addListener(followSystem);
  }
})();