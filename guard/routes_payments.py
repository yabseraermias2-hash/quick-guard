"""
Part A — PayPal routes, called by the PayPal JS SDK buttons.

POST /api/paypal/order    body: {check_id}  → {order_id}
  Refuses (403) unless the saved check is LOW, or MEDIUM and confirmed.
POST /api/paypal/capture  body: {order_id}  → {status, capture_id}
  Looks up the check again before capturing, then records history and
  saves the location as trusted.
"""
import time

from flask import Blueprint, jsonify, request

from . import paypal, store
from .risk import LOW, MEDIUM
from .web import json_body, session_id

bp = Blueprint('paypal', __name__, url_prefix='/api/paypal')


def approval_problem(check: dict) -> str | None:
    """Why this check may NOT be paid, or None if it's approved."""
    if check['status'] == 'captured':
        return 'This payment was already completed.'
    if check['status'] == 'capturing':
        return 'This payment is already being completed.'
    if check['level'] == LOW:
        return None
    if check['level'] == MEDIUM and check['confirmed']:
        return None
    if check['level'] == MEDIUM:
        return 'Please confirm this payment is really you first.'
    return 'QUICK Guard blocked this payment.'


def _body_str(key: str, limit: int = 64) -> str:
    value = json_body().get(key)
    return value[:limit] if isinstance(value, str) else ''


@bp.post('/order')
def order():
    sid = session_id()
    check = store.get_check(sid, _body_str('check_id'))
    if not check:
        return jsonify({'error': 'Unknown or expired check. Run QUICK Guard again.'}), 404
    problem = approval_problem(check)
    if problem:
        return jsonify({'error': problem}), 403
    try:
        created = paypal.create_order(check['amount'], check['currency'], check['recipient'],
                                      f"QUICK Guard checked payment to {check['recipient']}")
    except paypal.PayPalError as e:
        return jsonify({'error': str(e)}), 502
    store.attach_order(sid, check['check_id'], created['id'])
    return jsonify({'order_id': created['id']})


@bp.post('/capture')
def capture():
    sid = session_id()
    order_id = _body_str('order_id', 30)
    check = store.check_for_order(sid, order_id)
    if not check:
        return jsonify({'error': 'Unknown order.'}), 404
    problem = approval_problem(check)  # check again: never trust the browser
    if problem:
        return jsonify({'error': problem}), 403
    # Claim the check atomically, so two capture requests sent at the same
    # moment can't both get past the check above (no double payment).
    if not store.begin_capture(sid, check['check_id']):
        return jsonify({'error': 'This payment is already being completed.'}), 409
    try:
        result = paypal.capture_order(order_id)
    except paypal.PayPalError as e:
        store.set_status(sid, check['check_id'], 'checked')   # let the user try again
        return jsonify({'error': str(e), 'issue': e.issue}), 422 if e.issue else 502

    now = time.time()
    store.set_status(sid, check['check_id'], 'captured')
    location = check.get('location')
    if location:
        store.set_trusted(sid, location, now)
    store.record_payment(sid, {
        'ts': now, 'amount': result['amount'], 'currency': result['currency'],
        'recipient': check['recipient'], 'level': check['level'], 'score': check['score'],
        'status': 'captured', 'city': (location or {}).get('city'),
    })
    return jsonify({'status': result['status'], 'capture_id': result['capture_id']})
