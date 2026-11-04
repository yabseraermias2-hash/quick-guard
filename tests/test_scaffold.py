"""Checks the QUICK Guard wiring and the project's safety rules."""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('method,url', [
    ('post', '/api/guard/check'),
    ('post', '/api/guard/confirm'),
    ('get', '/api/guard/history'),
    ('get', '/api/guard/config'),
    ('post', '/api/paypal/order'),
    ('post', '/api/paypal/capture'),
])
def test_guard_routes_are_registered(client, method, url):
    r = getattr(client, method)(url, json={})
    assert r.status_code != 404


def test_local_tools_are_off_by_default(client):
    assert client.post('/run-code', json={'code': 'print(1)'}).status_code == 403
    assert client.post('/scan', json={'target': 'example.com'}).status_code == 403


def test_refuses_non_sandbox_mode(monkeypatch):
    from guard.paypal import assert_sandbox
    monkeypatch.setenv('PAYPAL_MODE', 'live')
    with pytest.raises(RuntimeError):
        assert_sandbox()


def test_only_sandbox_paypal_urls_in_code():
    """No live PayPal API URL may appear anywhere in our source."""
    live = re.compile(r'api(-m)?\.paypal\.com')
    for path in list(ROOT.glob('*.py')) + list(ROOT.glob('guard/*.py')) + list(ROOT.glob('static/*.js')) + [ROOT / 'index.html']:
        text = path.read_text(encoding='utf-8', errors='ignore')
        assert not live.search(text), f'live PayPal URL in {path.name}'


def test_session_cookie_is_safe():
    import server
    assert server.app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert server.app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
