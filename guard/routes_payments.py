"""
Part A — PayPal routes, called by the PayPal JS SDK buttons.

POST /api/paypal/order    body: {check_id}  → {order_id}
  Refuses (403) unless the saved check is LOW, or MEDIUM and confirmed.
POST /api/paypal/capture  body: {order_id}  → {status, capture_id}
  Looks up the check again before capturing, then records history and
  saves the location as trusted.
"""
from flask import Blueprint

from .web import not_built

bp = Blueprint('paypal', __name__, url_prefix='/api/paypal')


@bp.post('/order')
def order():
    return not_built('Part A: create order')


@bp.post('/capture')
def capture():
    return not_built('Part A: capture order')
