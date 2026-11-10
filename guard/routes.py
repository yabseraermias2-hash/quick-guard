"""
Part D — QUICK Guard API.

POST /api/guard/check
  body:  {amount: "25.00", currency: "USD", recipient: "email",
          message: "optional invoice text", language: "en" | "am",
          coords: {lat, lon} | null,      # only with browser permission
          demo_city: "tokyo" | null}      # DEMO MODE only
  reply: {check_id, level, score, reasons, scam: {...}, location: {...},
          explanation, voice}

POST /api/guard/confirm   body: {check_id}  → {ok, level}   (MEDIUM only)
GET  /api/guard/history                    → {payments: [...]}
GET  /api/guard/config                     → {paypal_client_id, demo_mode,
                                              demo_cities, languages, tools_enabled,
                                              ai: {provider, model, label}}
"""
import os
import re
import threading
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from . import ai_provider, location, paypal, risk, scam_check, store
from .translations import LANGUAGES, normalize_language, t, voice_for
from .web import EMAIL_RE, json_body, session_id

bp = Blueprint('guard', __name__, url_prefix='/api/guard')

MIN_AMOUNT = Decimal('0.01')
MAX_AMOUNT = Decimal('10000.00')
MAX_RECIPIENT = 254
_EMAIL_RE = re.compile(EMAIL_RE)

# Each check can cost an AI call, so cap how often one visitor can run them.
RATE_LIMIT = 30           # checks
RATE_WINDOW = 10 * 60     # per 10 minutes, per session and per IP
_hits: dict = defaultdict(deque)
_hits_lock = threading.Lock()


class BadInput(ValueError):
    pass


def _rate_limited(*keys: str) -> bool:
    now = time.time()
    with _hits_lock:
        if len(_hits) > 5000:
            _hits.clear()
        for key in keys:
            q = _hits[key]
            while q and now - q[0] > RATE_WINDOW:
                q.popleft()
            if len(q) >= RATE_LIMIT:
                return True
        for key in keys:
            _hits[key].append(now)
    return False


def _parse_amount(raw) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise BadInput('Enter an amount.')
    try:
        amount = Decimal(str(raw).strip().replace(',', ''))
    except InvalidOperation:
        raise BadInput('The amount must be a number, like 25.00.')
    if not amount.is_finite():
        raise BadInput('The amount must be a number, like 25.00.')
    # Range first: quantize() itself fails on giant numbers like 1e999999.
    if not MIN_AMOUNT <= amount <= MAX_AMOUNT:
        raise BadInput(f'The amount must be between {MIN_AMOUNT} and {MAX_AMOUNT}.')
    if amount != amount.quantize(Decimal('0.01')):
        raise BadInput('The amount can have at most 2 decimal places.')
    return f'{amount:.2f}'


def _parse_check_body(data: dict) -> dict:
    currency = str(data.get('currency') or 'USD').upper()
    if currency not in paypal.SUPPORTED_CURRENCIES:
        raise BadInput('Only USD is supported in this demo.')
    recipient = str(data.get('recipient') or '').strip().lower()
    if len(recipient) > MAX_RECIPIENT or not _EMAIL_RE.match(recipient):
        raise BadInput("Enter the recipient's PayPal email address.")
    message = data.get('message') or ''
    if not isinstance(message, str):
        raise BadInput('The message must be text.')
    if len(message) > scam_check.MAX_TEXT_CHARS:
        raise BadInput(f'The message is too long (max {scam_check.MAX_TEXT_CHARS} characters).')
    coords = data.get('coords')
    demo_city = data.get('demo_city')
    return {
        'amount': _parse_amount(data.get('amount')),
        'currency': currency,
        'recipient': recipient,
        'message': message,
        'language': normalize_language(data.get('language')),
        'coords': coords if isinstance(coords, dict) else None,
        'demo_city': demo_city if isinstance(demo_city, str) else None,
    }


def _elapsed_text(hours: float, lang: str) -> str:
    if hours < 2:
        return t('travel.minutes', lang, n=max(1, round(hours * 60)))
    return t('travel.hours', lang, n=round(hours))


def build_explanation(decision: dict, scam: dict, travel: dict, lang: str) -> str:
    """One short spoken/written explanation: verdict, then the reasons."""
    parts = [t(f"verdict.{decision['level']}", lang)]
    if 'impossible_travel' in decision['reasons']:
        parts.append(t('travel.impossible', lang, to_city=travel['to_city'], from_city=travel['from_city'],
                       km=f"{travel['km']:,}", elapsed=_elapsed_text(travel['hours'], lang)))
    elif 'fast_travel' in decision['reasons']:
        parts.append(t('travel.fast', lang, km=f"{travel['km']:,}", from_city=travel['from_city']))
    parts.append(scam['explanation'])
    return ' '.join(p for p in parts if p)


@bp.post('/check')
def check():
    sid = session_id()
    if _rate_limited(f'sid:{sid}', f'ip:{location.client_ip(request)}'):
        return jsonify({'error': 'Too many checks. Please wait a few minutes.'}), 429
    try:
        body = _parse_check_body(json_body())
    except BadInput as e:
        return jsonify({'error': str(e)}), 400

    now = time.time()
    lang = body['language']
    here = location.resolve(body['coords'], body['demo_city'], request)
    travel = location.evaluate(here, store.last_trusted(sid), now)
    scam = scam_check.check(body['message'], body['recipient'], body['amount'], lang)
    decision = risk.decide(scam, travel)
    explanation = build_explanation(decision, scam, travel, lang)

    check_id = store.save_check(sid, {
        'level': decision['level'], 'score': decision['score'],
        'amount': body['amount'], 'currency': body['currency'],
        'recipient': body['recipient'], 'location': here, 'created_at': now,
    })
    if decision['level'] == risk.HIGH:
        store.set_status(sid, check_id, 'blocked')
        store.record_payment(sid, {
            'ts': now, 'amount': body['amount'], 'currency': body['currency'],
            'recipient': body['recipient'], 'level': decision['level'],
            'score': decision['score'], 'status': 'blocked',
            'city': (here or {}).get('city'),
        })

    return jsonify({
        'check_id': check_id,
        'level': decision['level'],
        'score': decision['score'],
        'reasons': decision['reasons'],
        'scam': {'score': scam['scam_score'], 'red_flags': scam['red_flags'], 'source': scam['source'],
                 'model': scam.get('model'),
                 # Fixed-text languages (Amharic): the AI's own words, in English, shown but never spoken.
                 'ai_explanation_en': scam.get('ai_explanation_en')},
        'location': {'city': (here or {}).get('city'), 'source': (here or {}).get('source'), **travel},
        'explanation': explanation,
        'voice': voice_for(lang),
    })


@bp.post('/confirm')
def confirm():
    check_id = str(json_body().get('check_id') or '')[:64]
    if not store.mark_confirmed(session_id(), check_id):
        return jsonify({'error': 'Only a MEDIUM-risk check can be confirmed.'}), 400
    return jsonify({'ok': True, 'level': risk.MEDIUM})


@bp.get('/history')
def history():
    return jsonify({'payments': store.history(session_id())})


@bp.get('/config')
def config():
    return jsonify({
        'paypal_client_id': paypal.client_id(),
        'paypal_problem': paypal.client_id_problem(),
        'demo_mode': location.demo_mode(),
        'demo_cities': location.DEMO_CITIES if location.demo_mode() else {},
        # a list, not a dict: JSON key sorting would put Amharic before English
        'languages': [[code, info['name']] for code, info in LANGUAGES.items()],
        'tools_enabled': os.getenv('ENABLE_QUICK_TOOLS', 'false').strip().lower() == 'true',
        'ai': ai_provider.model_info(),   # provider + model name only, never a key
    })
