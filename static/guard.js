// Part D — QUICK Guard dashboard: payment form, orb colors, red flags, history.
// Every value from the server is inserted with textContent (never innerHTML),
// so text inside a scam message can't inject HTML or scripts into the page.
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const SAMPLES = {
    safe: { amount: '45.00', message: 'Invoice #1042 for logo design, 3 drafts as agreed. Due in 30 days. Thank you!' },
    scam: {
      amount: '250.00',
      message: 'PayPal Security Team: Your account has been limited due to unauthorized activity. ' +
               'To restore access, pay the verification fee within 24 hours and send the codes from ' +
               '2 Google Play gift cards. Verify here: http://paypa1-secure.com/login',
    },
  };

  const LEVEL_TEXT = { LOW: 'LOW RISK · SAFE', MEDIUM: 'MEDIUM RISK · CONFIRM', HIGH: 'HIGH RISK · BLOCKED' };
  const ORB = { LOW: 'guard_low', MEDIUM: 'guard_medium', HIGH: 'guard_high' };

  let config = null;
  let current = null;          // the last /api/guard/check result
  let paypalReady = null;      // Promise for the PayPal JS SDK
  let audio = null;

  // ── Helpers ───────────────────────────────────────────
  async function api(method, url, body) {
    const resp = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await resp.json(); } catch (e) { /* not JSON */ }
    if (!resp.ok) {
      const err = new Error(data.error || `Request failed (${resp.status})`);
      err.issue = data.issue;
      throw err;
    }
    return data;
  }

  function setStatus(text, kind) {
    const el = $('gStatus');
    el.textContent = text || '';
    el.className = 'g-status' + (kind ? ' ' + kind : '');
  }

  function setOrb(level) {
    if (typeof setOrbMode === 'function') setOrbMode(ORB[level] || 'idle');
    const hud = $('hudMode');
    if (hud) hud.textContent = level ? `GUARD: ${level}` : 'STANDBY';
  }

  async function speak(text, voice) {
    if (audio) { audio.pause(); audio = null; }
    try {
      const resp = await fetch('/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: (text || '').slice(0, 1500), voice }),   // server refuses longer text
      });
      if (!resp.ok) throw new Error('tts ' + resp.status);
      const url = URL.createObjectURL(await resp.blob());
      audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch (e) {
      console.warn('Guard voice unavailable:', e);
    }
  }

  // ── Tabs (Guard vs. local QUICK tools) ─────────────────
  function setupTabs(toolsEnabled) {
    document.querySelectorAll('.panel-tabs').forEach((bar) => {
      bar.querySelectorAll('.panel-tab').forEach((tab) => {
        if (tab.hasAttribute('data-tools-only')) tab.hidden = !toolsEnabled;
        tab.addEventListener('click', () => {
          bar.querySelectorAll('.panel-tab').forEach((t) => {
            t.classList.toggle('active', t === tab);
            $(t.dataset.pane).hidden = t !== tab;
          });
        });
      });
    });
  }

  // ── PayPal JS SDK ─────────────────────────────────────
  // The SDK is official PayPal code; the sandbox client ID makes it sandbox-only.
  function loadPayPal() {
    if (paypalReady) return paypalReady;
    paypalReady = new Promise((resolve, reject) => {
      if (!config.paypal_client_id) return reject(new Error(config.paypal_problem || 'PayPal sandbox client ID is not set on the server.'));
      const s = document.createElement('script');
      s.src = 'https://www.paypal.com/sdk/js?client-id=' + encodeURIComponent(config.paypal_client_id) +
              '&currency=USD&intent=capture&components=buttons';
      s.onload = () => resolve(window.paypal);
      s.onerror = () => { paypalReady = null; reject(new Error('Could not load PayPal. Check your connection, or that PAYPAL_CLIENT_ID on the server is the sandbox Client ID.')); };
      document.head.appendChild(s);
    });
    return paypalReady;
  }

  async function showPayPalButtons(checkId) {
    const box = $('paypalButtons');
    box.innerHTML = '';
    let pp;
    try { pp = await loadPayPal(); } catch (e) { setStatus(e.message, 'bad'); return; }
    pp.Buttons({
      style: { layout: 'vertical', label: 'pay', height: 40 },
      createOrder: async () => (await api('POST', '/api/paypal/order', { check_id: checkId })).order_id,
      onApprove: async (data, actions) => {
        setStatus('Completing payment...');
        try {
          const r = await api('POST', '/api/paypal/capture', { order_id: data.orderID });
          box.innerHTML = '';
          setStatus(`Payment complete ✓ (capture ${r.capture_id})`, 'ok');
          loadHistory();
        } catch (e) {
          if (e.issue === 'INSTRUMENT_DECLINED') return actions.restart();
          setStatus(e.message, 'bad');
        }
      },
      onCancel: () => setStatus('Payment cancelled. No money was sent.'),
      onError: (err) => setStatus((err && err.message) || 'PayPal error. No money was sent.', 'bad'),
    }).render(box);
  }

  // ── Showing a result ──────────────────────────────────
  function showResult(r) {
    current = r;
    const box = $('gResult');
    box.hidden = false;
    $('gEmpty').hidden = true;
    box.className = 'g-result ' + r.level.toLowerCase();
    $('gLevel').textContent = LEVEL_TEXT[r.level];
    $('gScoreBar').style.width = Math.max(3, r.score) + '%';
    $('gScoreText').textContent =
      `Risk ${r.score}/100 · scam check ${r.scam.score}/100 (` +
      (r.scam.model ? `AI: ${r.scam.model} + keyword rules` : 'keyword rules only') + ')';
    $('gExplanation').textContent = r.explanation;
    const aiEn = $('gAiEnglish');
    aiEn.textContent = r.scam.ai_explanation_en ? 'AI explanation (English): ' + r.scam.ai_explanation_en : '';
    aiEn.hidden = !r.scam.ai_explanation_en;

    const flags = $('gFlags');
    flags.innerHTML = '';
    r.scam.red_flags.forEach((f) => {
      const li = document.createElement('li');
      li.textContent = f;
      flags.appendChild(li);
    });

    const loc = r.location || {};
    const why = {
      denied: 'browser location is blocked for this site (allow it from the icon in the address bar)',
      unavailable: 'your device could not find its location (check that Location Services are on)',
      timeout: 'your device took too long to find its location',
      unsupported: 'this browser has no location support',
    }[r.locationProblem];
    let meta = loc.city
      ? `Location: ${loc.city}` + (loc.source === 'demo' ? ' (DEMO MODE)' : loc.source === 'ip' ? ' (approximate, from your internet address)' : '')
      : 'Location: unknown' + (why ? ` · ${why}` : '');
    if (loc.known) meta += ` · ${loc.km.toLocaleString()} km from last payment · ${loc.speed_kmh.toLocaleString()} km/h`;
    $('gMeta').textContent = meta;

    $('paypalButtons').innerHTML = '';
    $('gConfirm').hidden = r.level !== 'MEDIUM';
    setStatus(r.level === 'HIGH' ? 'Blocked. No money was sent.' : '', r.level === 'HIGH' ? 'bad' : '');
    if (r.level === 'LOW') showPayPalButtons(r.check_id);

    setOrb(r.level);
    speak(r.explanation, r.voice);
    if (typeof addMessage === 'function') addMessage('quick', `🛡 ${LEVEL_TEXT[r.level]}. ${r.explanation}`);
  }

  async function onConfirm() {
    if (!current) return;
    try {
      await api('POST', '/api/guard/confirm', { check_id: current.check_id });
      $('gConfirm').hidden = true;
      setStatus('Confirmed. You can pay now.', 'ok');
      showPayPalButtons(current.check_id);
    } catch (e) {
      setStatus(e.message, 'bad');
    }
  }

  // ── History ───────────────────────────────────────────
  async function loadHistory() {
    let data;
    try { data = await api('GET', '/api/guard/history'); } catch (e) { return; }
    const list = $('gHistory');
    list.innerHTML = '';
    if (!data.payments.length) {
      const li = document.createElement('li');
      li.className = 'g-empty';
      li.textContent = 'No payments yet.';
      list.appendChild(li);
      return;
    }
    data.payments.forEach((p) => {
      const li = document.createElement('li');
      li.className = 'g-item';
      const dot = document.createElement('span');
      dot.className = 'g-dot ' + p.status;
      const main = document.createElement('span');
      main.textContent = `$${p.amount} → ${p.recipient}`;
      const tag = document.createElement('span');
      tag.textContent = p.status === 'captured' ? 'PAID' : 'BLOCKED';
      tag.style.color = p.status === 'captured' ? 'var(--g-low)' : 'var(--g-high)';
      const sub = document.createElement('span');
      sub.className = 'g-item-sub';
      sub.textContent = `${new Date(p.ts * 1000).toLocaleString()} · ${p.level} ${p.score}/100` +
                        (p.city ? ` · ${p.city}` : '');
      li.append(dot, main, tag, sub);
      list.appendChild(li);
    });
  }

  // ── Form ──────────────────────────────────────────────
  async function onSubmit(ev) {
    ev.preventDefault();
    $('gError').textContent = '';
    const btn = $('gSubmit');
    btn.disabled = true;
    btn.textContent = 'CHECKING...';
    setOrb(null);
    if (typeof setOrbMode === 'function') setOrbMode('thinking');
    try {
      const demoOn = $('gDemoOn') && $('gDemoOn').checked;
      const coords = !demoOn && $('gUseLocation').checked ? await window.QuickLocation.getCoords() : null;
      const locationProblem = coords ? null : (!demoOn && $('gUseLocation').checked ? window.QuickLocation.lastProblem : null);
      const r = await api('POST', '/api/guard/check', {
        amount: $('gAmount').value.trim(),
        currency: 'USD',
        recipient: $('gRecipient').value.trim(),
        message: $('gMessage').value,
        language: $('gLanguage').value,
        coords,
        demo_city: demoOn ? $('gDemoCity').value : null,
      });
      r.locationProblem = locationProblem;
      showResult(r);
      loadHistory();
    } catch (e) {
      $('gError').textContent = e.message;
      setOrb(null);
    } finally {
      btn.disabled = false;
      btn.textContent = 'CHECK WITH QUICK GUARD';
    }
  }

  async function init() {
    try { config = await api('GET', '/api/guard/config'); } catch (e) { return; }

    const lang = $('gLanguage');
    config.languages.forEach(([code, name]) => {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = name;
      lang.appendChild(opt);
    });

    if (config.demo_mode) {
      $('gDemoBox').hidden = false;
      window.QuickLocation.fillDemoSelect($('gDemoCity'), config.demo_cities);
      $('gDemoOn').addEventListener('change', (e) => { $('gDemoCity').disabled = !e.target.checked; });
    }

    // The status bar shows the AI that QUICK Guard really uses (Groq on the
    // deployed site), not whatever local Ollama model happens to be installed.
    if (config.ai && typeof window.setGuardBrain === 'function') window.setGuardBrain(config.ai.label);
    if (typeof window.setVoiceInputAllowed === 'function') window.setVoiceInputAllowed(config.tools_enabled);
    if (typeof window.setChatAllowed === 'function') window.setChatAllowed(config.tools_enabled);

    setupTabs(config.tools_enabled);
    document.querySelectorAll('[data-sample]').forEach((b) => b.addEventListener('click', () => {
      const s = SAMPLES[b.dataset.sample];
      $('gAmount').value = s.amount;
      $('gMessage').value = s.message;
    }));
    $('guardForm').addEventListener('submit', onSubmit);
    $('gConfirm').addEventListener('click', onConfirm);
    $('gReplay').addEventListener('click', () => current && speak(current.explanation, current.voice));
    loadHistory();
  }

  init();
})();
