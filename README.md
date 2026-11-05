# QUICK Guard

**An AI guardian that stops PayPal scams before you pay.**

> Built for the PayPal AI Hackathon 2026. Uses the **PayPal Sandbox** only, so no real money ever moves.

## The problem

PayPal's systems are secure, but scammers target the *person*, not the system. Fake invoices, "your account is limited" messages, and fake support calls trick people into sending money themselves. QUICK Guard checks every payment **before** it's sent.

## Our story

_TODO: our team's roots in Ethiopia, first-time digital payment users, and why warnings need to speak Amharic, not just English._

## Features

_TODO: filled in as we build_

- [ ] PayPal sandbox payments (Orders API v2), captured only after QUICK Guard approves
- [ ] AI scam check of invoice and message text
- [ ] Location and impossible-travel check
- [ ] Combined risk engine (LOW / MEDIUM / HIGH)
- [ ] Voice warnings in English and Amharic
- [ ] Dashboard with a color-coded orb and payment history

## Live demo

_TODO: Render URL_

## Setup (run it yourself)

You need **Python 3.13** and **git**. 3.13 is the version the live demo runs on Render (pinned in `.python-version`), so use it locally too.

```bash
# 1. Clone
git clone https://github.com/<owner>/quick-guard.git
cd quick-guard

# 2. Create and activate a virtual environment
python3.13 -m venv venv           # Windows: py -3.13 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install packages
pip install -r requirements.txt
# Optional: QUICK's extra local tools (mic, memory, scanners)
# pip install -r requirements-local.txt

# 4. Add your settings
cp .env.example .env
# then open .env and paste in your own PayPal *sandbox* keys

# 5. Run
python server.py
```

Then open the `http://localhost:PORT` address the server prints.

### AI provider

Set `AI_PROVIDER` in `.env`:
- `ollama`: local Llama 3. Install [Ollama](https://ollama.com) and run `ollama pull llama3`.
- `groq`: hosted Llama 3 API (used by the live demo). _TODO: details_

## How judges can test it

_TODO: sandbox test accounts, a safe payment, a scam invoice, and an impossible-travel demo_

## How we built it

_TODO: architecture, and which AI tools we used and how_

## Security and privacy

- PayPal **sandbox** URLs only. Secrets live in `.env` / Render environment variables, never in code.
- Location is stored at city level or as rounded coordinates, never exact GPS.
- QUICK's original power tools (code runner, scanners, OSINT, uploads) are **off by default** (`ENABLE_QUICK_TOOLS=false`) and are never enabled on the public site.

## Screenshots

_TODO_

## Team

- Yab (Yabsera Kebede)
- Same Dawit
- Ismail Ishek
- Nahom Tefera

## License

[MIT](LICENSE)
