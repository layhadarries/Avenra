# Clear Sky weather interface

**Follow-up:** the historical entry-only gesture description below predates the
experimental, paired, explicit-opt-in four-tap alert. Its optional one-shot GPS
path is separate from all weather locations and never delays queue capture; see
[current limits and evidence](stage-6-release.md#weather-tap-location-follow-up-local-verification-no-deployment).

The start page is `/survivor/cover.html`. It uses a single location, system fonts,
inline SVG symbols and restrained day/cloud/rain/night sky colours. There are no
background videos, map widgets, external fonts, icon libraries or build dependencies.
An inline, non-interactive SVG scene adds a sun, light clouds, a moon/stars, rain,
snow, fog or a static storm accent as appropriate. There are no particle engines,
image downloads, animation loops or flashing lightning. These are decorative
illustrations, not measurements of moon phase or sun/moon position.

Day/night is determined at viewing time using that location's forecast sunrise
and sunset, with the API's `is_day` flag as fallback for missing/polar data. A
single timer at the next known sunrise, sunset or date boundary updates the scene
without an API request. It is stopped while hidden and checked again on return.
Precipitation/clouds remain based on the most recently fetched conditions;
cached/offline status and observation/download times remain visible.
`weather.css` is standalone: the legacy full-app `survivor.css` is no longer loaded
or precached. Both weather assets are in the public-only service-worker allowlist.

## Weather and location providers

- **Open-Meteo forecast API:** current conditions, 24 hourly entries and seven daily
  entries in one request, metric units and the forecast location's timezone.
- **Open-Meteo geocoding / GeoNames:** manual place search, submitted explicitly
  instead of requesting suggestions on every keystroke.
- **BigDataCloud free client-side reverse geocoding:** the current GPS locality.
  Requests originate directly from the browser following a fresh Geolocation API
  result. Never send saved/manual coordinates to this endpoint, proxy it through
  Vercel, or use IP fallback after permission is denied. Its free service uses
  GPS/IP pairings to improve location data; the weather page discloses this.

These keyless services suit this non-commercial demonstration. Their availability
is not guaranteed, and commercial use, scaling or changed provider terms require
review. Provider attribution and location-data explanations are included in the UI.

## Consent and privacy

On the first online visit, show the location explanation and request browser
location permission. Where permission is already granted, reopen using the current
browser location; where it is denied, offer search without repeated prompts or
IP geolocation. A chosen manual place stays selected until the user changes it.
No continuous `watchPosition` or polling loop is used.

Forecast coordinates are rounded to two decimals (roughly kilometre scale).
Locality lookup receives three decimals from the current GPS result. Only the
rounded forecast coordinates, locality label and forecast snapshot are stored
locally. All weather requests omit cookies and referrers. Coordinates never enter
app navigation URLs, Avenra's database or its server logs through this weather flow.
Providers necessarily receive the request IP and requested weather coordinates.

Browser location permission for weather does **not** change alert-sharing consent.
No new alert activation or account-write endpoint is added. The existing alert queue
still runs on the weather page so committed alerts keep their previous retry behaviour.

The "Forget saved weather location" control removes only weather-specific data
(including the unused legacy `cs_area` record) and pauses automatic location until
the user explicitly requests it again. It does not touch PINs, device credentials,
contacts, IndexedDB or pending alert/diary queues.

## Caching and honest failure states

Reuse the last successful, matching-coordinate forecast for 30 minutes. Refresh
when stale on reopening, reconnecting or becoming visible; the refresh control
also permits an explicit request. No automatic polling or per-keystroke API calls.
The single local weather snapshot is separate from the public service-worker cache.

Offline and provider-failure states identify saved weather and show its download
time. The original observation time and timezone remain visible. Hourly/day entries
which no longer cover the current date are not recycled as today's forecast.
Never apply an old place's readings to a newly selected place after a failed fetch.
Missing readings display a dash. There are no preset cities, artificial forecasts,
fabricated air quality, estimated "feels like", or unsupported severe-weather claims.

## Hidden entry remains unchanged

Holding the temperature still opens the existing PIN/device-unlock sheet; tapping
Thursday's forecast does the same. A real calendar-based Thursday remains present
even with no forecast, denied location or an expired cache. Neither gesture sends
an alert. Rapid-tap activation is explicitly deferred.

## Checks

- `python tests/weather_browser.py`: deterministic external-provider fixtures,
  current GPS locality, approximate coordinates, mobile/desktop sky variants,
  caching, offline behaviour, denial, search and scoped location forgetting.
- `python tests/weather_onboarding_browser.py`: hidden entry, PIN, WebAuthn and setup.
- `python tests/stage2_pwa_browser.py`: alert queues, consent and Quick Exit.
- `node --test tests/pwa-shell.cjs tests/service-worker-contract.cjs`: public cache
  boundaries, asset uniqueness and the 12 KiB gzipped weather CSS/JS budget.

Physical phone location permission and provider availability still require actual
device checks. Mocked weather tests establish rendering/state behaviour, not the
accuracy of weather models or the availability of a free provider.
