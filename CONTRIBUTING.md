# Contributing to QUICK Guard

A simple workflow for our team of 4. Follow these steps every time.

## One-time setup

```bash
git clone https://github.com/yabseraermias2-hash/quick-guard.git
cd quick-guard
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then add YOUR OWN PayPal sandbox keys
```

**Everyone uses their own PayPal sandbox keys.** Make them at
https://developer.paypal.com → Apps & Credentials → Sandbox → Create App.
Never share keys in chat, and never paste them into code.

## Project layout: who owns what

QUICK Guard is split into 4 parts. Each part has its own files, so we rarely edit the same file.
Each file's docstring describes what its functions take and return. If you need to change a
function's inputs or outputs, talk to that part's owner first.

| Part | Owner | Files |
|---|---|---|
| A: PayPal | Yabsera | `guard/paypal.py`, `guard/routes_payments.py`, `guard/store.py`, `scripts/sandbox_payment_test.py`, `tests/test_paypal.py`, `tests/test_payment_routes.py` |
| B: AI scam check | Yabsera | `guard/ai_provider.py`, `guard/scam_check.py`, `guard/translations.py`, `tests/test_scam_check.py` |
| C: Location | Yabsera | `guard/location.py`, `static/location.js`, `tests/test_location.py` |
| D: Risk + dashboard | Yabsera | `guard/risk.py`, `guard/routes.py`, `guard/web.py`, `static/guard.js`, `static/guard.css`, `tests/test_risk.py`, `tests/test_guard_routes.py` |

Shared files (`server.py`, `index.html`): keep changes small and mention them in your PR.

### Running the tests
```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
Run them before every pull request.

## Every time you work on something

### 1. Start from the latest `main`
```bash
git checkout main
git pull
```

### 2. Make a branch named after your feature
```bash
git checkout -b feature/scam-check      # examples: feature/paypal-orders, fix/orb-color
```

### 3. Commit small, with clear messages
Commit each time one small thing works:
```bash
git status                      # check what changed. Is .env listed? STOP, don't add it.
git add guard/scam_check.py     # add files by name
git commit -m "Add keyword fallback to scam check"
```
A good message says *what* changed: "Add haversine distance function", not "stuff" or "update".

### 4. Push your branch and open a pull request
```bash
git push -u origin feature/scam-check
```
Then open the link git prints, or go to the repo on GitHub → **Compare & pull request**.
Write one or two sentences about what you built and how to test it, and ask a teammate to review it.

### 5. Merge only after someone else reviews it
After the PR is merged, go back to step 1 for your next feature.

## The rules

1. **Never push straight to `main`.** All changes go through a pull request.
2. **Never commit `.env`** or any real key. It's in `.gitignore`. If `git status` ever shows `.env`, stop and ask.
3. **Use only PayPal sandbox** (`api-m.sandbox.paypal.com`). No live PayPal URLs, ever.
4. **Don't log secrets or full payment details**, not even in `print()` while debugging.
5. **Pull `main` often** so your branch doesn't fall far behind.

## If you get a merge conflict

Don't panic. Run `git pull origin main` on your branch, open the files git lists, and look for the
`<<<<<<<`, `=======`, `>>>>>>>` markers. Keep the right code, delete the markers, then `git add` and
`git commit`. If you're unsure, ask the teammate who wrote the other side.
