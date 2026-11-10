# QUICK Guard — Project Brief

**An AI guardian that checks a PayPal payment for scams and account takeover *before* any money moves.**
Built solo by **Yabsera Kebede** for the PayPal AI Hackathon 2026, with Claude Code as an AI pair programmer.
**Live:** https://quick-guard.onrender.com (free plan: the first load can take up to a minute while the server wakes up).
PayPal **Sandbox only**: no real money ever moves.

---

## 1. The problem

PayPal's systems are secure, but scammers target the *person*: fake invoices, "your account is limited"
notices, fake support numbers, "Grandma, I'm in trouble, don't tell anyone". Victims send the money
themselves, so fraud systems see a legitimate payment. Many of the people hit hardest are first-time
digital-payment users who may not read English, so warnings have to be simple, spoken, and in their language.

QUICK Guard sits **in front of the PayPal button**. Every payment is checked first, and the server, not the
browser, decides whether PayPal is allowed to create the order.

## 2. How one payment flows

```
 Browser                          QUICK Guard server                          PayPal Sandbox
 ───────                          ──────────────────                          ──────────────
 amount, recipient, message ──►  POST /api/guard/check
 (+ city-level location)           ├─ scam check: keyword rules  ┐
                                   ├─ scam check: AI (Groq)       ├─ max() ─┐
                                   ├─ location vs last trusted    │         ├─► risk engine → LOW / MEDIUM / HIGH
                                   │    city (impossible travel) ─┘         │
                                   └─ saves the check (15 min, this session only)
 ◄── level, score, red flags, explanation, voice, model used
 orb turns green / yellow / red, warning is spoken

 LOW                ─► PayPal buttons shown
 MEDIUM             ─► "Yes, this is me" ─► POST /api/guard/confirm ─► PayPal buttons shown
 HIGH               ─► blocked. No buttons, and the server refuses an order even if called directly

 PayPal button ──►  POST /api/paypal/order    (refused unless LOW or confirmed MEDIUM) ──► Orders API v2: create
 buyer approves in PayPal popup ◄─────────────────────────────────────────────────────────┘
 onApprove ──────►  POST /api/paypal/capture  (re-checks, claims the check atomically)  ──► Orders API v2: capture
                    records history, saves this city as trusted
```

## 3. Code map

| Part | Files | What it does |
|---|---|---|
| A · PayPal | `guard/paypal.py`, `guard/routes_payments.py`, `guard/store.py` | OAuth2 client-credentials token (cached), Orders v2 create/capture with idempotency keys, sandbox-only guard, per-session in-memory store |
| B · Scam check | `guard/scam_check.py`, `guard/ai_provider.py`, `guard/translations.py` | Keyword rules in 7 languages + AI check (Groq or local Ollama), evidence rule, all warning text and voices |
| C · Location | `guard/location.py`, `static/location.js` | Browser location (rounded) → IP fallback using the visitor's real IP behind Render/Cloudflare; haversine distance; impossible-travel speed check; DEMO MODE cities; tells the user why location is unknown |
| D · Risk + dashboard | `guard/risk.py`, `guard/routes.py`, `static/guard.js`, `static/guard.css` | The LOW/MEDIUM/HIGH rule, the Guard API, the dashboard (orb, flags, voice, PayPal buttons, history) |
| Shared | `server.py`, `index.html` | Flask app, `/tts` voice, security settings; the original QUICK UI that hosts the Guard panel |
| Ops | `render.yaml`, `.python-version`, `scripts/check_groq.py`, `scripts/sandbox_payment_test.py` | Render deploy, Python 3.13 pin, Groq key checker, command-line sandbox payment |

## 4. The rules

**Risk engine** (`guard/risk.py`, pure functions):

| Signal | Score |
|---|---|
| Scam check | 0–100 (higher of keyword score and AI score) |
| Travel faster than 900 km/h since the last trusted payment (and ≥ 50 km away) | 90 |
| Travel at 500–900 km/h | 50 |

`score = max(scam, location)` → **LOW** < 40 ≤ **MEDIUM** < 70 ≤ **HIGH**.
If both the scam score and the location score are ≥ 40, the result is always **HIGH**.

**Keyword rules** (`guard/scam_check.py`) always run, even when the AI is up. Points add up, capped at 100:

| Category | Points | Examples |
|---|---|---|
| Overpayment trick | 50 | "accidentally sent you", "refund the difference" |
| Gift card / crypto / wire | 45 | "gift cards", "bitcoin", "Western Union", ስጦታ ካርድ, ቢትኮይን |
| Aimed at the AI checker | 40 | "ignore previous instructions", "SYSTEM:", "scam_score", "mark this LOW" |
| Account threat | 35 | "account has been limited", "unauthorized activity", "arrested" |
| Asks for credentials | 35 | "password", "one-time code", "verify your account", የይለፍ ቃል |
| Suspicious link | 30 | http://, bare IPs, link shorteners, PayPal look-alikes, punycode |
| Secrecy | 30 | "don't tell anyone", ለማንም አትናገር |
| Fake prize | 30 | "you've won", "claim your prize", "processing fee", አሸንፈዋል |
| Impersonation | 25 | "PayPal Support", "Dear customer", "call us now at +1…" |
| Name mismatch | 25 | claims to be PayPal/Amazon/… but the money goes to a personal email |
| False urgency | 20 | "urgent", "within 24 hours", "final notice", አስቸኳይ |

**AI check** (`guard/ai_provider.py`): one switch, `AI_PROVIDER=groq` (deployed) or `ollama` (laptop, Llama 3).
On Groq the model is OpenAI's open-weight **gpt-oss-120b** with low reasoning effort, falling back to
**gpt-oss-20b** when the free tier's 8,000 tokens/minute limit is hit (free Groq keys can't use Llama models).
Identical messages within 10 minutes reuse the cached answer. The model must return strict JSON, and untrusted text
is fenced between markers and labeled as data. Each result shows which model actually answered, or
"keyword rules only".

**Evidence rule:** every red flag must quote words that are really in the message, for example
`Pressure to pay right away: “within 24 hours”`. AI flags that quote nothing, or quote words that aren't there,
are dropped. The AI may push a payment to MEDIUM or HIGH only if at least one of its quotes checks out. This
stopped a confused local model from blocking "ቡና" (coffee) as 80/100.

**The AI can raise a score but never lower it.** A scam that talks the AI into saying "safe" still gets the
keyword score, plus 40 points for trying to manipulate the checker.

## 5. Security and privacy

- **Sandbox only.** `PAYPAL_MODE` must be `sandbox` or the server refuses to start, and there is no live PayPal URL in the code.
- **The server is the gate.** Order creation and capture both re-check the saved result. Checks belong to one browser session (signed cookie) and expire after 15 minutes.
- **No double payment.** Capture claims the check under a lock before calling PayPal, and PayPal's `PayPal-Request-Id` makes the capture call idempotent.
- **Secrets** live only in `.env` (local) or Render environment variables. Logs show the HTTP status, PayPal's error name and `debug_id`, never keys, tokens, full payment bodies or IP addresses.
- **Config mistakes are caught.** A `PAYPAL_CLIENT_ID` with stray spaces or quotes is cleaned up. One that is clearly wrong (for example an email address) is never sent to the page; the page names the mistake without showing the value, and `/health` reports `paypal_client_id: ok | missing | invalid`.
- **Location** is rounded to 0.1° (≈ 11 km) the moment it arrives. Exact GPS is never stored or returned.
- **No payment data on disk.** Everything lives in server memory and resets on restart.
- **Inputs are validated server-side.** Amount 0.01–10,000.00 USD with at most 2 decimals; strict email; message ≤ 5,000 characters; JSON bodies ≤ 256 KB; `/tts` ≤ 1,500 characters and approved voices only.
- **Rate limit:** 30 checks per 10 minutes, per session and per visitor IP. On Render the IP comes from Cloudflare's `CF-Connecting-IP` (Cloudflare rejects client-supplied values), else the rightmost `X-Forwarded-For` entry that isn't a Render or Cloudflare hop. Entries a client could fake are never used.
- **No HTML injection.** Every server value is inserted as text (`textContent`), and the chat renderer escapes everything before formatting.
- **Cookies** are `HttpOnly` and `SameSite=Lax`, plus `Secure` on Render.
- **QUICK's original power tools** (chat, code runner, scanners, uploads, monitoring, microphone) are off unless `ENABLE_QUICK_TOOLS=true`, which is never set on the public site. With it off, those routes return 403, and the microphone can never switch on, not even from the wake word.

## 6. Languages and voice

Warnings, red flags and spoken explanations are available in **English, Amharic (አማርኛ), Spanish, French,
Mandarin, Hindi and Nepali**, with keyword rules in each language. `/tts` turns the explanation into speech
with Microsoft Edge neural voices (e.g. `am-ET-MekdesNeural` for Amharic), so it works on a server with no
speakers. Amharic is reviewed by a native speaker. The other languages, and the three newest Amharic labels
(secrecy, "aimed at the AI", prize), still need a native-speaker check.

## 7. Deploying (Render)

`render.yaml` defines everything: Python 3.13, `pip install -r requirements.txt`, and
`gunicorn server:app --workers 1 --threads 4`. **Keep one worker**, because checks and history live in memory.
The health check is `/health`, which answers 200 even when the AI is down, since Guard still protects users with keyword rules.
`PYTHONUNBUFFERED=1` makes the app's log lines (`[PayPal]`, `[Location]`, `[Guard]`) show up in Render's logs right away.
Render auto-deploys every push to `main`.

Secrets you type into Render (never commit them): `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `GROQ_API_KEY`.
A free Groq key allows about 6 new checks a minute per model (~12 with the fallback) and 1,000 a day per model.
Past that, checks fall back to keyword rules until the minute resets.
`SECRET_KEY` is generated by Render. Before deploying, run `python scripts/check_groq.py` with your key in
`.env` to confirm which Groq models your key can use.

## 8. Test results

- **239 automated tests pass** (`python -m pytest -q`), including the audit's regression tests and tests for both live bugs below.
- **Scam accuracy, 40 real messages through the live AI:** 20 normal (including "", "ቡና", emojis, typos)
  → all LOW; 20 scams (fake limits, invoices, support callbacks, gift cards, crypto, overpayment, prizes,
  family emergencies, bad links, 3 in Amharic) → all HIGH. **0 false positives, 0 false negatives, every
  red flag quotes the message.**
- **Location:** Erie → Pittsburgh 3 h later = LOW (63 km/h). Addis → Tokyo 2 days later = LOW (217 km/h).
  Addis → Tokyo 2 minutes later = HIGH (312,031 km/h). No location, denied permission and junk coordinates all work.
- **PayPal sandbox:** real orders were created and captured by a sandbox buyer, locally (capture `6XN59489CV561532L`)
  and on the live site ($45.00, LOW 5/100, capture `3XE96830G46460116`).
  HIGH, unconfirmed MEDIUM, double captures, simultaneous captures, fake or tampered order IDs, expired
  checks and other sessions are all refused.
- **Attacks:** 5 prompt injections stay HIGH, even with an AI that fully obeys them. XSS payloads stay plain text.
  20+ malformed inputs and 8 malformed body types get clean 4xx errors. The 31st check is rate-limited.
  Every local-only route returns 403. No secret or access token appears in any response, page, log or tracked file.
- **Final live check (2026-11-10, Chrome, DEMO MODE):** safe invoice → LOW 5/100 with PayPal buttons, and the server
  creates a sandbox order; fake "PayPal Security Team" message → HIGH 100/100, blocked, 8 quoted red flags, spoken
  in English and in Amharic (`am-ET-MekdesNeural`); the server refuses an order for the HIGH check (403). All answers came
  from Groq `openai/gpt-oss-120b`.
- **AI failure:** Ollama down, a wrong or missing Groq key, and 15 kinds of broken AI JSON all fall back to keyword
  rules with calm wording, and the page keeps working.

## 9. Bugs found after deploying (and fixed)

| Bug on the live site | Cause | Fix |
|---|---|---|
| PayPal buttons: "Could not load PayPal." | `PAYPAL_CLIENT_ID` on Render held an email address; PayPal's SDK answered HTTP 400 | Re-pasted the real Client ID; the server now validates the ID, explains the mistake safely and reports it in `/health` |
| "Location: unknown" when the browser didn't share its location | The IP fallback took the *last* `X-Forwarded-For` entry, which on Render is its own proxy (`['public', 'proxy', 'proxy']` in the logs), so the lookup was skipped. Every visitor also shared one rate limit | Use `CF-Connecting-IP`, else the rightmost non-proxy entry; don't cache failed lookups; the page says why location is unknown. Verified live: blocked browser location now gives the visitor's city, and faked headers are ignored |

## 10. Known limits

- State is in memory: a Render restart or redeploy clears checks and history, and the app must run as a single process.
- The free Render plan sleeps when idle, so the first visit after a while takes ~30–60 s to wake.
- IP location is city-level and can be wrong (VPNs, mobile networks). That's why travel only adds risk and never blocks on its own unless it's physically impossible.
- QUICK's original chat (`/chat`) needs a local Ollama, so on the deployed site it returns 403 and the chat box is hidden.

## 11. What's next

- **Recipient check** (in progress, not deployed): look up the recipient email's domain (does it exist, can it receive
  mail, how old is it, is it a throwaway inbox or a PayPal look-alike) and hand those facts to the AI.
- Native-speaker review of every language, starting with the newest Amharic labels.
- Save trusted locations and history in a database, so restarts don't clear them and the app can run more than one worker.
