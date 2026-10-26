# Private PWA visual follow-up

The inside screens now use the dashboard's existing cream/plum/teal palette with
a clearer mobile hierarchy: support card, diary/directory shortcuts, grouped
directory controls, consistent page labels, vault form cards and selected tabs.
Light/dark display settings, system fonts and offline-local assets are retained.
Weather files, emergency timing, consent, vault authority and payloads are unchanged.

Verification (local fictional data):

- Failing-first `pwa_design_browser.py` exposed the missing support card/shortcuts
  and selected-tab semantics. It now passes light/dark layouts at 320/390 pixels,
  offline styling, navigation, Quick Exit and keyboard Undo.
- Stage 2 HELP and Stage 5 encrypted diary Chromium regression scripts pass.
- All 34 Node checks pass, including the 4 KiB gzipped shared stylesheet budget.
- Inspected Chromium screenshots of the mobile Home, directory and locked diary
  in light/dark themes. Screenshots stay outside Git; they are synthetic fixture
  captures, not physical-phone acceptance or independent accessibility review.

Public shell cache advances to v23 via the existing explicit-update flow. No
forced activation, private API caching, deployment or live DB/provider change.
