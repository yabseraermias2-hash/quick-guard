// Part C — browser location (asks permission) and DEMO MODE city picker.
// Exact GPS never leaves the browser: coordinates are rounded to 1 decimal
// (≈11 km) here, and rounded again on the server.
(function () {
  'use strict';

  const DECIMALS = 1;
  const round = (n) => Math.round(n * 10 ** DECIMALS) / 10 ** DECIMALS;

  // Ask the browser for location. Resolves to {lat, lon} or null
  // (denied, unsupported, or slow) — the server then falls back to IP lookup.
  function getCoords() {
    return new Promise((resolve) => {
      api.lastProblem = null;
      if (!navigator.geolocation) { api.lastProblem = 'unsupported'; return resolve(null); }
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ lat: round(pos.coords.latitude), lon: round(pos.coords.longitude) }),
        // 1 = permission denied, 2 = position unavailable (e.g. OS location off), 3 = timeout
        (err) => { api.lastProblem = ({ 1: 'denied', 2: 'unavailable', 3: 'timeout' })[err && err.code] || 'unavailable'; resolve(null); },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 10 * 60 * 1000 }
      );
    });
  }

  // Fill a <select> with the demo cities from /api/guard/config.
  function fillDemoSelect(select, cities) {
    select.innerHTML = '';
    for (const [key, c] of Object.entries(cities)) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = c.city;
      select.appendChild(opt);
    }
  }

  const api = { getCoords, fillDemoSelect, lastProblem: null };
  window.QuickLocation = api;
})();
