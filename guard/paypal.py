"""
Part A — PayPal sandbox client (OAuth 2.0 client credentials + Orders API v2).

SANDBOX ONLY. There is deliberately no live URL anywhere in this project.
Never log the client secret, the access token, or full payment details.
"""
import os
import re
import threading
import time

import requests

SANDBOX_BASE_URL = 'https://api-m.sandbox.paypal.com'

SUPPORTED_CURRENCIES = {'USD'}

_TIMEOUT = 15                 # seconds for every PayPal call
_TOKEN_EARLY_REFRESH = 60     # refresh the token this many seconds before it expires
_MAX_DESCRIPTION = 127        # PayPal's limit for purchase_units[].description

_AMOUNT_RE = re.compile(r'^\d{1,5}\.\d{2}$')
from .web import EMAIL_RE  # noqa: E402
_EMAIL_RE = re.compile(EMAIL_RE)
_ORDER_ID_RE = re.compile(r'^[A-Z0-9]{10,30}$')

_token_lock = threading.Lock()
_token = {'value': None, 'expires_at': 0.0}


class PayPalError(Exception):
    """Raised when PayPal returns an error or can't be reached.
    The message is safe to show the user (no secrets, no raw responses).
    `issue` holds PayPal's error code when there is one (e.g. INSTRUMENT_DECLINED)."""

    def __init__(self, message: str, issue: str | None = None):
        super().__init__(message)
        self.issue = issue


def assert_sandbox():
    """Refuse to run unless PAYPAL_MODE=sandbox. Call once at startup."""
    mode = os.getenv('PAYPAL_MODE', 'sandbox').strip().lower()
    if mode != 'sandbox':
        raise RuntimeError('QUICK Guard only supports PAYPAL_MODE=sandbox.')


# PayPal client IDs are base64url-style strings (about 80 characters): only
# letters, digits, - and _. Anything else (an email, a space) is a paste mistake.
_CLIENT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,256}$')


def client_id() -> str:
    """Public client ID for the PayPal JS SDK in the browser. Never the secret.
    Returns '' when the value is missing or clearly not a client ID."""
    cid = _raw_client_id()
    return cid if _CLIENT_ID_RE.match(cid) else ''


def _raw_client_id() -> str:
    # Tolerate the usual copy-paste extras: spaces, newlines, wrapping quotes.
    return os.getenv('PAYPAL_CLIENT_ID', '').strip().strip('"\'').strip()


def client_id_problem() -> str | None:
    """None when PAYPAL_CLIENT_ID looks right, else a safe hint (never the value)."""
    cid = _raw_client_id()
    if not cid:
        return 'PAYPAL_CLIENT_ID is not set on the server.'
    if _CLIENT_ID_RE.match(cid):
        return None
    if '@' in cid:
        return ('PAYPAL_CLIENT_ID looks like an email address. Paste the sandbox app\'s Client ID '
                '(developer.paypal.com → Apps & Credentials → Sandbox), not the account email.')
    return (f'PAYPAL_CLIENT_ID does not look like a PayPal client ID ({len(cid)} characters; '
            'expected about 80 letters, digits, - and _).')


def _credentials() -> tuple[str, str]:
    cid = client_id()
    secret = os.getenv('PAYPAL_CLIENT_SECRET', '').strip().strip('"\'').strip()
    if not cid or not secret:
        raise PayPalError('PayPal sandbox keys are not set on the server.')
    return cid, secret


def _log_failure(what: str, resp) -> None:
    """Log only the status, PayPal's error name and debug_id — never the body."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    print(f"[PayPal] {what} failed: HTTP {resp.status_code} "
          f"{body.get('name') or body.get('error', '')} debug_id={body.get('debug_id', '-')}")


def _first_issue(resp) -> str | None:
    try:
        details = resp.json().get('details') or []
        return details[0].get('issue') if details else None
    except (ValueError, AttributeError):
        return None


def get_access_token() -> str:
    """POST /v1/oauth2/token with client credentials.
    Cache the token in memory until shortly before it expires."""
    with _token_lock:
        if _token['value'] and time.time() < _token['expires_at'] - _TOKEN_EARLY_REFRESH:
            return _token['value']
        cid, secret = _credentials()
        try:
            resp = requests.post(
                f'{SANDBOX_BASE_URL}/v1/oauth2/token',
                auth=(cid, secret),
                data={'grant_type': 'client_credentials'},
                headers={'Accept': 'application/json'},
                timeout=_TIMEOUT,
            )
        except requests.RequestException:
            raise PayPalError('Could not reach the PayPal sandbox.')
        if resp.status_code != 200:
            _log_failure('token', resp)
            raise PayPalError('The PayPal sandbox rejected our credentials.')
        data = resp.json()
        _token['value'] = data['access_token']
        _token['expires_at'] = time.time() + int(data.get('expires_in', 0))
        return _token['value']


def _clear_token():
    with _token_lock:
        _token['value'] = None
        _token['expires_at'] = 0.0


def _api(method: str, path: str, body: dict | None, request_id: str):
    """Call the Orders API with our token. Retries once if the token expired.
    request_id makes the call idempotent: PayPal won't do the same thing twice."""
    for attempt in (1, 2):
        headers = {
            'Authorization': f'Bearer {get_access_token()}',
            'Content-Type': 'application/json',
            'PayPal-Request-Id': request_id,
            'Prefer': 'return=representation',
        }
        try:
            resp = requests.request(method, f'{SANDBOX_BASE_URL}{path}',
                                    json=body, headers=headers, timeout=_TIMEOUT)
        except requests.RequestException:
            raise PayPalError('Could not reach the PayPal sandbox.')
        if resp.status_code == 401 and attempt == 1:
            _clear_token()
            continue
        return resp


def create_order(amount: str, currency: str, payee_email: str, description: str,
                 return_url: str | None = None, cancel_url: str | None = None) -> dict:
    """POST /v2/checkout/orders with intent=CAPTURE.

    amount:      already-validated string like "25.00"
    currency:    one of SUPPORTED_CURRENCIES
    payee_email: the sandbox recipient's email ('' = the app's own sandbox account)
    description: short text (no full invoice); trimmed to PayPal's limit
    return_url / cancel_url: only for the redirect flow (scripts); the JS SDK
                 buttons don't need them

    Returns {'id': str, 'status': str, 'approve_url': str | None}
    """
    if not _AMOUNT_RE.match(amount or '') or float(amount) <= 0:
        raise PayPalError('Invalid amount.')
    if currency not in SUPPORTED_CURRENCIES:
        raise PayPalError('Unsupported currency.')
    if payee_email and not _EMAIL_RE.match(payee_email):
        raise PayPalError('Invalid recipient email.')

    unit = {
        'amount': {'currency_code': currency, 'value': amount},
        'description': (description or 'QUICK Guard payment')[:_MAX_DESCRIPTION],
    }
    if payee_email:
        unit['payee'] = {'email_address': payee_email}

    experience = {
        'brand_name': 'QUICK Guard Demo',
        'shipping_preference': 'NO_SHIPPING',
        'user_action': 'PAY_NOW',
    }
    if return_url and cancel_url:
        experience.update(return_url=return_url, cancel_url=cancel_url)

    body = {
        'intent': 'CAPTURE',
        'purchase_units': [unit],
        'payment_source': {'paypal': {'experience_context': experience}},
    }
    request_id = f'order-{os.urandom(12).hex()}'
    resp = _api('POST', '/v2/checkout/orders', body, request_id)
    if resp.status_code not in (200, 201):
        _log_failure('create order', resp)
        raise PayPalError('PayPal could not create the order.', _first_issue(resp))

    data = resp.json()
    approve_url = next((l['href'] for l in data.get('links', [])
                        if l.get('rel') in ('payer-action', 'approve')), None)
    return {'id': data['id'], 'status': data.get('status', ''), 'approve_url': approve_url}


def capture_order(order_id: str) -> dict:
    """POST /v2/checkout/orders/{order_id}/capture.

    Returns {'id': str, 'status': str, 'capture_id': str,
             'amount': str, 'currency': str}
    """
    if not _ORDER_ID_RE.match(order_id or ''):
        raise PayPalError('Invalid order ID.')
    resp = _api('POST', f'/v2/checkout/orders/{order_id}/capture', None,
                f'capture-{order_id}')
    if resp.status_code not in (200, 201):
        _log_failure('capture', resp)
        issue = _first_issue(resp)
        if issue == 'ORDER_NOT_APPROVED':
            raise PayPalError('The payment was not approved in PayPal yet.', issue)
        if issue == 'INSTRUMENT_DECLINED':
            raise PayPalError('PayPal declined that payment method. Try another one.', issue)
        raise PayPalError('PayPal could not complete the payment.', issue)

    data = resp.json()
    capture = data['purchase_units'][0]['payments']['captures'][0]
    return {
        'id': data['id'],
        'status': data.get('status', ''),
        'capture_id': capture['id'],
        'amount': capture['amount']['value'],
        'currency': capture['amount']['currency_code'],
    }
