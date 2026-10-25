/* Public weather only. No case IDs, account writes, tracking watch or alert gestures.
   Provider requests go directly from the browser; only approximate weather data is saved. */
(function () {
  'use strict';
  var PLACE = 'cs_weather_place_v1', CACHE = 'cs_weather_forecast_v1', ASKED = 'cs_weather_location_asked';
  var MAX_AGE = 30 * 60 * 1000, place = null, cached = null, forecastId = 0, interaction = 0;
  var weatherRequest = null, searchRequest = null, searchId = 0, locating = false;
  function $(id) { return document.getElementById(id); }
  function text(id, value) { $(id).textContent = value; }
  function number(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
  function rounded(value) { return number(value) === null ? '—' : String(Math.round(value)); }
  function degrees(value) { return rounded(value) + '°'; }
  function read(key) { try { var value = localStorage.getItem(key); return value && value.length < 80000 ? JSON.parse(value) : null; } catch (_) { return null; } }
  function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} }
  function validPlace(value) {
    return value && number(value.lat) !== null && Math.abs(value.lat) <= 90 &&
      number(value.lon) !== null && Math.abs(value.lon) <= 180 &&
      typeof value.name === 'string' && value.name.length > 0 && value.name.length <= 160 &&
      typeof value.region === 'string' && value.region.length <= 240 && ['gps','manual'].includes(value.mode);
  }
  function key(value) { return value.lat.toFixed(2) + ',' + value.lon.toFixed(2); }
  function matchingCache() { return place && cached && cached.placeKey === key(place); }
  function fresh() { return matchingCache() && Date.now() - cached.fetchedAt < MAX_AGE && Date.now() >= cached.fetchedAt; }
  function at(array, index) { return Array.isArray(array) ? number(array[index]) : null; }
  function normalize(data) {
    if (!data || !data.current || number(data.current.temperature_2m) === null || number(data.current.time) === null) throw new Error('invalid_forecast');
    var zone = data.timezone;
    new Intl.DateTimeFormat('en', {timeZone:zone}).format();
    if (typeof zone !== 'string') throw new Error('invalid_timezone');
    var current = data.current, hourly = data.hourly || {}, daily = data.daily || {};
    return {
      zone:zone, current:current,
      hours:(Array.isArray(hourly.time) ? hourly.time : []).slice(0, 24).map(function (time, index) {
        return {time:number(time), temp:at(hourly.temperature_2m,index), code:at(hourly.weather_code,index), rain:at(hourly.precipitation_probability,index), day:at(hourly.is_day,index)};
      }).filter(function (hour) { return hour.time !== null; }),
      days:(Array.isArray(daily.time) ? daily.time : []).slice(0,7).map(function (time, index) {
        return {time:number(time), low:at(daily.temperature_2m_min,index), high:at(daily.temperature_2m_max,index), code:at(daily.weather_code,index),
          rain:at(daily.precipitation_probability_max,index), uv:at(daily.uv_index_max,index), sunrise:at(daily.sunrise,index), sunset:at(daily.sunset,index)};
      }).filter(function (day) { return day.time !== null; })
    };
  }
  function condition(code, day) {
    var icon = 'unknown', label = 'Conditions unavailable', sky = 'cloud';
    if (code === 0 || code === 1) { icon = day === 0 ? 'moon' : 'sun'; label = code === 0 ? 'Clear' : 'Mostly clear'; sky = 'clear'; }
    else if (code === 2) { icon = day === 0 ? 'cloud' : 'partly'; label = 'Partly cloudy'; sky = 'clear'; }
    else if (code === 3) { icon = 'cloud'; label = 'Overcast'; }
    else if ([45,48].includes(code)) { icon = 'fog'; label = 'Fog'; }
    else if ([51,53,55].includes(code)) { icon = 'rain'; label = 'Drizzle'; sky = 'rain'; }
    else if ([56,57,66,67].includes(code)) { icon = 'rain'; label = 'Freezing rain'; sky = 'rain'; }
    else if ([61,63,65].includes(code)) { icon = 'rain'; label = 'Rain'; sky = 'rain'; }
    else if ([71,73,75,77,85,86].includes(code)) { icon = 'snow'; label = 'Snow'; }
    else if ([80,81,82].includes(code)) { icon = 'rain'; label = 'Rain showers'; sky = 'rain'; }
    else if ([95,96,99].includes(code)) { icon = 'storm'; label = 'Thunderstorms'; sky = 'rain'; }
    return {icon:icon, label:label, sky:day === 0 ? 'night' : sky};
  }
  function icon(type) {
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class','cv-wx-ico'); svg.setAttribute('aria-hidden','true'); svg.dataset.icon = type;
    var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href','#wx-' + type); svg.appendChild(use); return svg;
  }
  function element(tag, className, content) {
    var result = document.createElement(tag); result.className = className;
    if (content !== undefined) result.textContent = content;
    return result;
  }
  function dateKey(time, zone) {
    var parts = new Intl.DateTimeFormat('en', {timeZone:zone, year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(time));
    function part(type) { return parts.find(function (entry) { return entry.type === type; }).value; }
    return part('year') + '-' + part('month') + '-' + part('day');
  }
  function clock(seconds, zone) {
    return number(seconds) === null ? '—' : new Intl.DateTimeFormat('en-GB', {timeZone:zone,hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(seconds * 1000));
  }
  function renderDays(weather) {
    var zone = weather ? weather.zone : Intl.DateTimeFormat().resolvedOptions().timeZone;
    var today = dateKey(Date.now(), zone), start = Date.parse(today + 'T12:00:00Z');
    var days = weather ? weather.days : [], lows = days.map(function (day) { return day.low; }).filter(function (value) { return value !== null; });
    var highs = days.map(function (day) { return day.high; }).filter(function (value) { return value !== null; });
    var minimum = Math.min.apply(null, lows), maximum = Math.max.apply(null, highs), range = Math.max(1, maximum - minimum);
    $('cv-days').replaceChildren();
    for (var index = 0; index < 7; index++) {
      var calendar = new Date(start + index * 86400000), calendarKey = calendar.toISOString().slice(0,10);
      var day = days.find(function (entry) { return dateKey(entry.time * 1000, zone) === calendarKey; });
      var thursday = calendar.getUTCDay() === 4, label = index === 0 ? 'Today' : calendar.toLocaleDateString('en', {weekday:'short',timeZone:'UTC'});
      var row = element(thursday ? 'button' : 'div','cv-day-row');
      if (thursday) { row.type = 'button'; row.dataset.thursday = '1'; row.addEventListener('click', function () { window.CWOnboarding.open(); }); }
      row.appendChild(element('span','cv-day',label));
      var visual = element('span','cv-day-icon'); visual.appendChild(icon(condition(day ? day.code : null,1).icon));
      if (day && day.rain !== null && day.rain >= 20) visual.appendChild(element('small','',rounded(day.rain) + '%'));
      row.appendChild(visual);
      var temperatures = element('span','cv-rng'); temperatures.appendChild(element('span','',degrees(day ? day.low : null)));
      var track = element('span','cv-range-track');
      if (day && day.low !== null && day.high !== null && Number.isFinite(minimum) && Number.isFinite(maximum)) {
        var fill = element('span','cv-range-fill');
        fill.style.setProperty('--start', (day.low - minimum) / range * 100 + '%');
        fill.style.setProperty('--width', Math.max(3,(day.high - day.low) / range * 100) + '%'); track.appendChild(fill);
      }
      temperatures.appendChild(track); temperatures.appendChild(element('strong','',degrees(day ? day.high : null))); row.appendChild(temperatures);
      var item = document.createElement('li'); item.appendChild(row); $('cv-days').appendChild(item);
    }
    return days.find(function (day) { return dateKey(day.time * 1000, zone) === today; });
  }
  function renderHours(weather) {
    $('cv-hourly').replaceChildren();
    var hours = weather ? weather.hours.filter(function (hour) { return hour.time * 1000 > Date.now() - 3600000; }) : [];
    if (!hours.length) { $('cv-hourly').appendChild(element('p','cv-empty',weather ? 'Hourly forecast is out of date. Refresh when connected.' : 'Your hourly forecast will appear here.')); return; }
    hours.forEach(function (hour) {
      var item = element('div','cv-hour'), current = hour.time * 1000 <= Date.now() && hour.time * 1000 > Date.now() - 3600000;
      item.appendChild(element('span','',current ? 'Now' : clock(hour.time,weather.zone)));
      item.appendChild(icon(condition(hour.code,hour.day).icon)); item.appendChild(element('strong','',degrees(hour.temp)));
      item.appendChild(element('span','cv-hour-rain',hour.rain !== null && hour.rain >= 20 ? rounded(hour.rain) + '%' : ''));
      $('cv-hourly').appendChild(item);
    });
  }
  function renderLocation() {
    text('cv-place',place ? place.name : 'Your local sky');
    text('cv-region',place ? place.region : 'A little closer to the day ahead.');
    text('cv-location-note',!place ? 'WEATHER NEAR YOU' : place.mode === 'gps' ? 'CURRENT LOCATION' : 'CHOSEN LOCATION');
  }
  function render(weather) {
    var current = weather ? weather.current : {}, day = renderDays(weather);
    document.querySelector('.cv-details').hidden = !weather;
    renderHours(weather); renderLocation();
    text('cv-temp',degrees(current.temperature_2m));
    var conditions = condition(number(current.weather_code),current.is_day);
    text('cv-desc',weather ? conditions.label : place ? 'Waiting for weather' : 'Waiting for your location');
    $('cv-condition-icon').replaceChildren();
    if (weather) $('cv-condition-icon').appendChild(icon(conditions.icon));
    document.body.dataset.sky = weather ? conditions.sky : 'clear';
    document.querySelector('meta[name="theme-color"]').content = weather && conditions.sky === 'night' ? '#101b2e' : '#355c80';
    text('cv-hl','H: ' + degrees(day ? day.high : null) + '   L: ' + degrees(day ? day.low : null));
    text('cv-date',new Intl.DateTimeFormat('en', {weekday:'long',month:'long',day:'numeric',timeZone:weather ? weather.zone : undefined}).format(new Date()));
    text('cv-feels',degrees(current.apparent_temperature));
    var directions = ['N','NE','E','SE','S','SW','W','NW'];
    var direction = number(current.wind_direction_10m) === null ? '' : directions[Math.round(current.wind_direction_10m / 45) % 8] + ' ';
    text('cv-wind',number(current.wind_speed_10m) === null ? '—' : direction + rounded(current.wind_speed_10m) + ' km/h');
    text('cv-gusts',number(current.wind_gusts_10m) === null ? 'Gusts unavailable' : 'Gusts ' + rounded(current.wind_gusts_10m) + ' km/h');
    text('cv-hum',number(current.relative_humidity_2m) === null ? '—' : rounded(current.relative_humidity_2m) + '%');
    text('cv-uv',day && day.uv !== null ? rounded(day.uv) : '—');
    text('cv-rain',day && day.rain !== null ? rounded(day.rain) + '%' : '—');
    text('cv-sun',day ? clock(day.sunrise,weather.zone) + ' / ' + clock(day.sunset,weather.zone) : '— / —');
    var daylight = day && day.sunrise !== null && day.sunset !== null ? Math.round((day.sunset - day.sunrise) / 60) : null;
    text('cv-daylight',daylight !== null && daylight >= 0 ? Math.floor(daylight / 60) + ' hr ' + daylight % 60 + ' min daylight' : 'Daylight unavailable');
    text('cv-foot',weather ? 'Conditions at ' + clock(current.time,weather.zone) + ' · ' + weather.zone.replace(/_/g,' ') + '. Forecast downloaded ' + new Date(cached.fetchedAt).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) + '.' : 'No forecast downloaded for this location.');
  }
  async function request(url, controller) {
    controller = controller || new AbortController();
    var timer = setTimeout(function () { controller.abort(); },12000);
    try {
      var response = await fetch(url, {credentials:'omit', cache:'no-store', referrerPolicy:'no-referrer', signal:controller.signal});
      if (!response.ok) throw new Error('provider_unavailable');
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  function forecastUrl(selected) {
    var params = new URLSearchParams({latitude:selected.lat,longitude:selected.lon,timezone:'auto',timeformat:'unixtime',forecast_days:7,forecast_hours:24,
      temperature_unit:'celsius',wind_speed_unit:'kmh',precipitation_unit:'mm',
      current:'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m',
      hourly:'temperature_2m,weather_code,precipitation_probability,is_day',
      daily:'weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,uv_index_max,precipitation_probability_max'});
    return 'https://api.open-meteo.com/v1/forecast?' + params;
  }
  async function loadForecast(force) {
    if (!place) return;
    var id = ++forecastId;
    if (weatherRequest) weatherRequest.abort();
    $('cv-refresh').disabled = false;
    if (matchingCache()) render(normalize(cached.data)); else render(null);
    if (navigator.onLine === false) {
      text('cv-weather-status',matchingCache() ? 'Offline · showing saved weather. Check the download time below.' : 'You’re offline. Connect to download weather for this place.'); return;
    }
    if (!force && fresh()) { text('cv-weather-status',''); return; }
    text('cv-weather-status','Updating weather…'); $('cv-refresh').disabled = true;
    var selectedKey = key(place); weatherRequest = new AbortController();
    try {
      var data = await request(forecastUrl(place),weatherRequest), weather = normalize(data);
      if (id !== forecastId || !place || selectedKey !== key(place)) return;
      cached = {version:1,placeKey:selectedKey,fetchedAt:Date.now(),data:{current:data.current,hourly:data.hourly,daily:data.daily,timezone:data.timezone}};
      save(CACHE,cached); render(weather); text('cv-weather-status',''); $('cv-location-prompt').hidden = true;
    } catch (_) {
      if (id === forecastId) text('cv-weather-status',matchingCache() ? 'Couldn’t refresh · showing saved weather. Check the download time below.' : 'Weather is unavailable right now. Try refreshing when connected.');
    } finally { if (id === forecastId) $('cv-refresh').disabled = false; }
  }
  function choose(selected, force) {
    place = selected; save(PLACE,place); renderLocation();
    $('cv-location-prompt').hidden = true;
    loadForecast(force);
  }
  async function nameCurrentPosition(latitude, longitude, revision, selectedKey) {
    // This free endpoint is called only for a fresh browser geolocation result.
    // Never call it with saved/manual coordinates or use IP fallback after denial.
    try {
      var params = new URLSearchParams({latitude:latitude.toFixed(3),longitude:longitude.toFixed(3),localityLanguage:'en'});
      var data = await request('https://api.bigdatacloud.net/data/reverse-geocode-client?' + params);
      if (revision !== interaction || !place || key(place) !== selectedKey || /ip/i.test(data.lookupSource || '')) return;
      var name = data.locality || data.city;
      if (typeof name !== 'string' || !name.trim()) return;
      place.name = name.slice(0,160);
      place.region = [data.city !== name ? data.city : data.principalSubdivision,data.countryName].filter(function (part) { return typeof part === 'string' && part; }).join(', ').slice(0,240);
      save(PLACE,place); renderLocation();
    } catch (_) { /* Weather still uses the correct coordinates if naming fails. */ }
  }
  function locate() {
    if (locating) return;
    if (!navigator.geolocation || !window.isSecureContext) { text('cv-location-message','Location is unavailable in this browser. Search for a place instead.'); $('cv-location-prompt').hidden = false; return; }
    if (navigator.onLine === false) { text('cv-weather-status','You’re offline. Saved weather is still available; connect before changing location.'); return; }
    locating = true; var revision = ++interaction;
    save(ASKED,true); $('cv-gps-btn').disabled = true;
    text('cv-weather-status','Finding your location…');
    navigator.geolocation.getCurrentPosition(function (position) {
      locating = false; $('cv-gps-btn').disabled = false;
      if (revision !== interaction) return;
      var latitude = number(position.coords.latitude), longitude = number(position.coords.longitude);
      if (latitude === null || longitude === null || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
        text('cv-weather-status','Your location could not be read. Search for a place instead.'); return;
      }
      var selected = {lat:Math.round(latitude * 100) / 100,lon:Math.round(longitude * 100) / 100,name:'Current location',region:'Area name unavailable',mode:'gps'};
      var same = place && place.mode === 'gps' && key(place) === key(selected);
      if (same) { selected.name = place.name; selected.region = place.region; }
      choose(selected,false);
      if (!same || selected.name === 'Current location') nameCurrentPosition(latitude,longitude,revision,key(selected));
    }, function (error) {
      locating = false; $('cv-gps-btn').disabled = false;
      if (revision !== interaction) return;
      var message = error.code === 1 ? 'Location access is off. Search for a place, or enable location in your browser settings.' : 'Couldn’t find your location. Search for a place or try again.';
      text('cv-weather-status',place ? message + ' Your saved place is still selected.' : '');
      text('cv-location-message',message); $('cv-location-prompt').hidden = false;
    }, {enableHighAccuracy:false,timeout:8000,maximumAge:600000});
  }
  function openSearch() { $('cv-search-dialog').showModal(); $('cv-search-input').focus(); }
  $('cv-loc-btn').addEventListener('click',openSearch);
  $('cv-search-open').addEventListener('click',openSearch);
  $('cv-search-close').addEventListener('click',function () { $('cv-search-dialog').close(); });
  $('cv-search-current').addEventListener('click',function () { $('cv-search-dialog').close(); locate(); });
  $('cv-gps-btn').addEventListener('click',locate);
  $('cv-refresh').addEventListener('click',function () { if (place) loadForecast(true); else locate(); });
  $('cv-search-form').addEventListener('submit',async function (event) {
    event.preventDefault();
    var query = $('cv-search-input').value.trim();
    if (query.length < 2) return;
    var id = ++searchId;
    if (searchRequest) searchRequest.abort();
    searchRequest = new AbortController();
    $('cv-search-results').replaceChildren(); text('cv-search-status','Searching…'); $('cv-search-submit').disabled = true;
    try {
      var params = new URLSearchParams({name:query,count:5,language:'en',format:'json'});
      var data = await request('https://geocoding-api.open-meteo.com/v1/search?' + params,searchRequest);
      if (id !== searchId) return;
      var results = (Array.isArray(data.results) ? data.results : []).slice(0,5);
      var count = 0;
      results.forEach(function (result) {
        if (!result || number(result.latitude) === null || number(result.longitude) === null) return;
        var selected = {lat:Math.round(result.latitude * 100) / 100,lon:Math.round(result.longitude * 100) / 100,name:result.name,
          region:[result.admin1,result.country].filter(function (part) { return typeof part === 'string' && part; }).join(', ').slice(0,240),mode:'manual'};
        if (!validPlace(selected)) return;
        var item = document.createElement('li'), button = document.createElement('button'); button.type = 'button';
        button.appendChild(element('strong','',selected.name)); button.appendChild(element('span','',selected.region));
        button.addEventListener('click',function () { interaction++; $('cv-search-dialog').close(); choose(selected,false); });
        item.appendChild(button); $('cv-search-results').appendChild(item); count++;
      });
      text('cv-search-status',count ? 'Choose a place below.' : 'No places found. Try a nearby city or a different spelling.');
    } catch (_) { if (id === searchId) text('cv-search-status','Search is unavailable. Check your connection and try again.'); }
    finally { if (id === searchId) $('cv-search-submit').disabled = false; }
  });
  $('cv-forget').addEventListener('click',function () {
    interaction++; forecastId++;
    if (weatherRequest) weatherRequest.abort();
    place = cached = null;
    try { [PLACE,CACHE,'cs_area'].forEach(function (name) { localStorage.removeItem(name); }); } catch (_) {}
    save(ASKED,'paused');
    render(null); $('cv-refresh').disabled = false; $('cv-location-prompt').hidden = false;
    text('cv-weather-status','Saved weather location removed. Other app data has not been changed.');
  });
  function reconnect() { if (place && !document.hidden) loadForecast(false); }
  window.addEventListener('online',reconnect);
  window.addEventListener('offline',function () { if (place) { if (weatherRequest) weatherRequest.abort(); loadForecast(false); } });
  document.addEventListener('visibilitychange',function () { if (!document.hidden) reconnect(); });
  async function boot() {
    var savedPlace = read(PLACE), savedCache = read(CACHE);
    if (validPlace(savedPlace)) place = savedPlace;
    if (savedCache && savedCache.version === 1 && number(savedCache.fetchedAt) !== null && savedCache.fetchedAt <= Date.now() + 60000 && savedCache.fetchedAt > 0) {
      try { normalize(savedCache.data); cached = savedCache; } catch (_) {}
    }
    if (place) { $('cv-location-prompt').hidden = true; loadForecast(false); } else render(null);
    if (navigator.onLine === false || place && place.mode === 'manual') return;
    if (read(ASKED) === 'paused') return;
    var firstRequest = read(ASKED) !== true;
    if (firstRequest) { locate(); return; }
    try {
      var revision = interaction;
      var permission = await navigator.permissions.query({name:'geolocation'});
      if (revision !== interaction) return;
      if (permission.state === 'granted') locate();
      else if (!place && permission.state === 'denied') text('cv-location-message','Location access is off. Search for a place, or enable location in your browser settings.');
    } catch (_) { /* Unsupported Permissions API: use the explicit location button. */ }
  }
  boot();
})();
