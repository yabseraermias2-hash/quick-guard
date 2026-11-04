"""
Part A — PayPal sandbox client (OAuth 2.0 client credentials + Orders API v2).

SANDBOX ONLY. There is deliberately no live URL anywhere in this project.
Never log the client secret, the access token, or full payment details.
"""
import os

SANDBOX_BASE_URL = 'https://api-m.sandbox.paypal.com'

SUPPORTED_CURRENCIES = {'USD'}


class PayPalError(Exception):
    """Raised when PayPal returns an error or can't be reached.
    The message is safe to show the user (no secrets, no raw responses)."""


def assert_sandbox():
    """Refuse to run unless PAYPAL_MODE=sandbox. Call once at startup."""
    mode = os.getenv('PAYPAL_MODE', 'sandbox').strip().lower()
    if mode != 'sandbox':
        raise RuntimeError('QUICK Guard only supports PAYPAL_MODE=sandbox.')


def client_id() -> str:
    """Public client ID for the PayPal JS SDK in the browser. Never the secret."""
    return os.getenv('PAYPAL_CLIENT_ID', '').strip()


def get_access_token() -> str:
    """POST /v1/oauth2/token with client credentials.
    Cache the token in memory until shortly before it expires."""
    raise NotImplementedError


def create_order(amount: str, currency: str, payee_email: str, description: str) -> dict:
    """POST /v2/checkout/orders with intent=CAPTURE.

    amount:      already-validated string like "25.00"
    currency:    one of SUPPORTED_CURRENCIES
    payee_email: the sandbox recipient's email
    description: short, already-trimmed text (no full invoice)

    Returns {'id': str, 'status': str}
    """
    raise NotImplementedError


def capture_order(order_id: str) -> dict:
    """POST /v2/checkout/orders/{order_id}/capture.

    Returns {'id': str, 'status': str, 'capture_id': str,
             'amount': str, 'currency': str}
    """
    raise NotImplementedError
