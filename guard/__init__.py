"""
QUICK Guard — checks a PayPal payment for scams and account takeover
*before* any money moves.

Flow:
  /api/guard/check   → scam_check + location + risk → LOW / MEDIUM / HIGH
  /api/guard/confirm → user says "yes, this is me" for a MEDIUM result
  /api/paypal/order  → only if the saved check is LOW or a confirmed MEDIUM
  /api/paypal/capture→ checks again, captures, records history

Each module has one owner (see CONTRIBUTING.md). Change another module's
function signatures only after agreeing with its owner.
"""


def register(app):
    """Attach QUICK Guard's routes to the Flask app."""
    from .routes import bp as guard_bp
    from .routes_payments import bp as payments_bp
    app.register_blueprint(guard_bp)
    app.register_blueprint(payments_bp)
