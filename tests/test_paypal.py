"""Part A — PayPal client tests. PayPal is faked; no network, no real keys."""
import pytest

from guard import paypal


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    monkeypatch.setenv('PAYPAL_CLIENT_ID', 'test-client-id')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', 'test-client-secret')
    paypal._clear_token()


@pytest.fixture
def token_calls(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return FakeResp(200, {'access_token': 'tok-1', 'expires_in': 3600})
    monkeypatch.setattr(paypal.requests, 'post', fake_post)
    return calls


def test_token_uses_sandbox_and_is_cached(token_calls):
    assert paypal.get_access_token() == 'tok-1'
    assert paypal.get_access_token() == 'tok-1'
    assert token_calls == ['https://api-m.sandbox.paypal.com/v1/oauth2/token']


def test_missing_keys_give_safe_error(monkeypatch):
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', '')
    with pytest.raises(paypal.PayPalError, match='not set'):
        paypal.get_access_token()


def test_bad_credentials_never_leak_secret(monkeypatch, capsys):
    monkeypatch.setattr(paypal.requests, 'post',
                        lambda url, **kw: FakeResp(401, {'error': 'invalid_client'}))
    with pytest.raises(paypal.PayPalError) as e:
        paypal.get_access_token()
    out = capsys.readouterr().out
    assert 'test-client-secret' not in str(e.value) + out


def test_create_order_sends_correct_body(token_calls, monkeypatch):
    sent = {}

    def fake_request(method, url, json=None, headers=None, timeout=None):
        sent.update(method=method, url=url, body=json, headers=headers)
        return FakeResp(201, {'id': 'ORDER1234567', 'status': 'PAYER_ACTION_REQUIRED',
                              'links': [{'rel': 'payer-action', 'href': 'https://sandbox.example/approve'}]})
    monkeypatch.setattr(paypal.requests, 'request', fake_request)

    out = paypal.create_order('25.00', 'USD', 'friend@example.com', 'rent')
    assert out == {'id': 'ORDER1234567', 'status': 'PAYER_ACTION_REQUIRED',
                   'approve_url': 'https://sandbox.example/approve'}
    assert sent['url'] == 'https://api-m.sandbox.paypal.com/v2/checkout/orders'
    unit = sent['body']['purchase_units'][0]
    assert sent['body']['intent'] == 'CAPTURE'
    assert unit['amount'] == {'currency_code': 'USD', 'value': '25.00'}
    assert unit['payee'] == {'email_address': 'friend@example.com'}
    assert sent['headers']['Authorization'] == 'Bearer tok-1'
    assert sent['headers']['PayPal-Request-Id']


@pytest.mark.parametrize('amount,currency,email', [
    ('25', 'USD', 'a@b.co'),          # needs 2 decimals
    ('-1.00', 'USD', 'a@b.co'),
    ('0.00', 'USD', 'a@b.co'),
    ('999999.00', 'USD', 'a@b.co'),
    ('5.00', 'BTC', 'a@b.co'),
    ('5.00', 'USD', 'not-an-email'),
])
def test_create_order_rejects_bad_input(amount, currency, email):
    with pytest.raises(paypal.PayPalError):
        paypal.create_order(amount, currency, email, 'x')


def test_expired_token_is_refreshed_once(monkeypatch):
    tokens = iter(['old', 'new'])
    monkeypatch.setattr(paypal.requests, 'post',
                        lambda url, **kw: FakeResp(200, {'access_token': next(tokens), 'expires_in': 3600}))
    seen = []

    def fake_request(method, url, json=None, headers=None, timeout=None):
        seen.append(headers['Authorization'])
        if headers['Authorization'] == 'Bearer old':
            return FakeResp(401, {})
        return FakeResp(201, {'id': 'ORDER1234567', 'status': 'CREATED', 'links': []})
    monkeypatch.setattr(paypal.requests, 'request', fake_request)

    assert paypal.create_order('1.00', 'USD', '', 'x')['id'] == 'ORDER1234567'
    assert seen == ['Bearer old', 'Bearer new']


def test_capture_parses_result(token_calls, monkeypatch):
    def fake_request(method, url, json=None, headers=None, timeout=None):
        assert url.endswith('/v2/checkout/orders/ORDER1234567/capture')
        assert headers['PayPal-Request-Id'] == 'capture-ORDER1234567'
        return FakeResp(201, {'id': 'ORDER1234567', 'status': 'COMPLETED', 'purchase_units': [
            {'payments': {'captures': [{'id': 'CAP1', 'amount': {'value': '25.00', 'currency_code': 'USD'}}]}}]})
    monkeypatch.setattr(paypal.requests, 'request', fake_request)
    assert paypal.capture_order('ORDER1234567') == {
        'id': 'ORDER1234567', 'status': 'COMPLETED', 'capture_id': 'CAP1',
        'amount': '25.00', 'currency': 'USD'}


def test_capture_not_approved(token_calls, monkeypatch):
    monkeypatch.setattr(paypal.requests, 'request', lambda *a, **kw: FakeResp(
        422, {'name': 'UNPROCESSABLE_ENTITY', 'details': [{'issue': 'ORDER_NOT_APPROVED'}]}))
    with pytest.raises(paypal.PayPalError) as e:
        paypal.capture_order('ORDER1234567')
    assert e.value.issue == 'ORDER_NOT_APPROVED'


def test_capture_rejects_weird_order_id():
    with pytest.raises(paypal.PayPalError):
        paypal.capture_order('../../v1/oauth2/token')
