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
                                              demo_cities, languages}
"""
from flask import Blueprint

from .web import not_built

bp = Blueprint('guard', __name__, url_prefix='/api/guard')


@bp.post('/check')
def check():
    return not_built('Part D: guard check')


@bp.post('/confirm')
def confirm():
    return not_built('Part D: confirm')


@bp.get('/history')
def history():
    return not_built('Part D: history')


@bp.get('/config')
def config():
    return not_built('Part D: config')
