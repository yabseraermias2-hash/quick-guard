"""Small Flask helpers shared by the QUICK Guard route files."""
import secrets

from flask import jsonify, session


def session_id() -> str:
    """A random ID for this browser, kept in Flask's signed session cookie."""
    if 'sid' not in session:
        session['sid'] = secrets.token_urlsafe(16)
    return session['sid']


def not_built(part: str):
    return jsonify({'error': f'Not built yet ({part}).'}), 501
