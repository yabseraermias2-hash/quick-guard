"""Check a Groq API key before deploying: which models it can use, and whether
QUICK Guard's scam check really gets answers from Groq.

    python scripts/check_groq.py

Reads GROQ_API_KEY (and GROQ_MODEL, optional) from .env or the environment.
Never prints the key.
"""
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, '.env'))
os.environ['AI_PROVIDER'] = 'groq'

from guard import ai_provider, scam_check  # noqa: E402

PREFERRED = ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'llama-3.3-70b-versatile', 'llama-3.1-8b-instant']


def main() -> int:
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not key:
        print('GROQ_API_KEY is not set. Add it to .env (local) or the Render dashboard (deployed).')
        return 1
    print('GROQ_API_KEY: set (not shown)')

    r = requests.get(f'{ai_provider.GROQ_BASE_URL}/models', headers={'Authorization': f'Bearer {key}'}, timeout=15)
    if r.status_code != 200:
        print(f'Groq refused the key: HTTP {r.status_code}. Check that it was copied completely.')
        return 1
    available = sorted(m['id'] for m in r.json().get('data', []) if m.get('active', True))
    print(f'Models this key can list ({len(available)}):')
    for mid in available:
        print(f'  {"*" if mid in PREFERRED else " "} {mid}')

    configured = ai_provider.model_info()['model']
    print(f'\nModels QUICK Guard will try, in order: {", ".join(ai_provider.groq_models())}')
    tests = [('rent for November', 'friend@example.com', 'LOW'),
             ('PayPal Security Team: your account is limited. Verify your password within 24 hours '
              'at http://paypa1-help.com', 'pp.help.desk@gmail.com', 'HIGH')]
    ok = True
    for text, recipient, want in tests:
        try:
            ai = scam_check.ai_check(text, recipient, '25.00', 'en')
        except (ai_provider.AIError, ValueError) as e:
            print(f'  ✗ {configured} did not answer usably: {e}')
            ok = False
            break
        print(f'  ✓ {ai_provider.last_model_label()} answered: score {ai["scam_score"]} for “{text[:40]}…” (expected {want})')
    if not ok:
        usable = [m for m in PREFERRED if m in available and m != configured]
        if usable:
            print(f'\nTry: set GROQ_MODEL={usable[0]} and run this again.')
        return 1
    print('\nGroq is working. QUICK Guard will use it for every scam check.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
