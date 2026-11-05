"""Small Flask helpers shared by the QUICK Guard route files."""
import secrets

from flask import jsonify, request, session

# Strict on purpose: letters, digits and . _ % + - only, so an "email" can never
# carry HTML or quotes (e.g. "<script>alert(1)</script>@evil.com").
EMAIL_RE = r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}$'


def json_body() -> dict:
    """The request's JSON object, or {} for anything else: no body, broken JSON,
    a list / string / number instead of an object, or JSON nested so deeply it
    would crash the parser."""
    try:
        data = request.get_json(silent=True)
    except RecursionError:
        return {}
    return data if isinstance(data, dict) else {}


def session_id() -> str:
    """A random ID for this browser, kept in Flask's signed session cookie."""
    if 'sid' not in session:
        session['sid'] = secrets.token_urlsafe(16)
    return session['sid']


def not_built(part: str):
    return jsonify({'error': f'Not built yet ({part}).'}), 501
