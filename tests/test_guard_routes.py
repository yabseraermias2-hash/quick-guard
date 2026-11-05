"""Part D — the /api/guard routes, end to end (PayPal and AI are faked)."""
import time

import pytest

from guard import ai_provider, paypal, store
from guard import routes as guard_routes

SCAM = ("PayPal Security Team: your account has been limited. Pay within 24 hours "
        "with 2 Google Play gift cards. Verify at http://paypa1-secure.com")


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    store.clear()
    guard_routes._hits.clear()
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setattr(ai_provider, 'chat_json',
                        lambda *a, **kw: (_ for _ in ()).throw(ai_provider.AIError('offline')))
    monkeypatch.setattr(paypal, 'create_order',
                        lambda *a, **kw: {'id': 'ORDER1234567', 'status': 'CREATED', 'approve_url': None})
    monkeypatch.setattr(paypal, 'capture_order', lambda oid: {
        'id': oid, 'status': 'COMPLETED', 'capture_id': 'CAP1', 'amount': '25.00', 'currency': 'USD'})


def check(client, **overrides):
    body = {'amount': '25.00', 'currency': 'USD', 'recipient': 'friend@example.com',
            'message': 'Thanks for dinner!', 'language': 'en', 'coords': None,
            'demo_city': 'addis_ababa', **overrides}
    return client.post('/api/guard/check', json=body)


def pay(client, check_id):
    order = client.post('/api/paypal/order', json={'check_id': check_id})
    assert order.status_code == 200, order.get_json()
    return client.post('/api/paypal/capture', json={'order_id': order.get_json()['order_id']})


def test_the_demo_story(client):
    # 1. Safe payment from Addis Ababa → LOW → paid
    r = check(client).get_json()
    assert r['level'] == 'LOW' and r['location']['source'] == 'demo'
    assert pay(client, r['check_id']).status_code == 200

    # 2. Scam invoice → HIGH → blocked, PayPal refuses to create an order
    r = check(client, message=SCAM).get_json()
    assert r['level'] == 'HIGH' and r['scam']['red_flags']
    assert client.post('/api/paypal/order', json={'check_id': r['check_id']}).status_code == 403

    # 3. Innocent message but from Tokyo minutes later → impossible travel → HIGH
    r = check(client, demo_city='tokyo').get_json()
    assert r['level'] == 'HIGH' and 'impossible_travel' in r['reasons']
    assert 'Tokyo' in r['explanation'] and 'Addis Ababa' in r['explanation']
    assert client.post('/api/paypal/order', json={'check_id': r['check_id']}).status_code == 403

    hist = client.get('/api/guard/history').get_json()['payments']
    assert [p['status'] for p in hist] == ['blocked', 'blocked', 'captured']


def test_amharic_explanation_and_voice(client):
    r = check(client, message=SCAM, language='am').get_json()
    assert r['voice'] == 'am-ET-MekdesNeural'
    assert any('ሀ' <= ch <= '፿' for ch in r['explanation'])


def test_medium_flow_requires_confirm(client, monkeypatch):
    monkeypatch.setattr(ai_provider, 'chat_json', lambda *a, **kw: {
        'scam_score': 50, 'red_flags': [{'quote': 'Thanks for dinner', 'why': 'Unusual request'}],
        'explanation': 'Be careful.'})
    r = check(client).get_json()
    assert r['level'] == 'MEDIUM'
    assert client.post('/api/paypal/order', json={'check_id': r['check_id']}).status_code == 403
    assert client.post('/api/guard/confirm', json={'check_id': r['check_id']}).status_code == 200
    assert pay(client, r['check_id']).status_code == 200


def test_high_check_cannot_be_confirmed(client):
    r = check(client, message=SCAM).get_json()
    assert client.post('/api/guard/confirm', json={'check_id': r['check_id']}).status_code == 400


@pytest.mark.parametrize('field,value', [
    ('amount', ''), ('amount', 'abc'), ('amount', '0'), ('amount', '10000.01'),
    ('amount', '5.555'), ('amount', 'NaN'), ('amount', True), ('amount', None),
    ('currency', 'EUR'), ('recipient', 'nope'), ('recipient', 'a@b.co' + 'x' * 300),
    ('message', 'x' * 5001), ('message', ['list']),
])
def test_bad_input_is_rejected(client, field, value):
    assert check(client, **{field: value}).status_code == 400


def test_amount_is_normalized(client):
    r = check(client, amount='1,250.5').get_json()
    assert store.get_check(store_sid(client), r['check_id'])['amount'] == '1250.50'


def store_sid(client):
    with client.session_transaction() as s:
        return s['sid']


def test_demo_city_ignored_when_demo_mode_off(client, monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'false')
    r = check(client, demo_city='tokyo').get_json()
    assert r['location']['source'] is None   # localhost: no demo, no IP lookup
    assert client.get('/api/guard/config').get_json()['demo_cities'] == {}


def test_browser_coords_are_rounded(client):
    r = check(client, demo_city=None, coords={'lat': 9.03456, 'lon': 38.74689}).get_json()
    assert r['location']['source'] == 'browser'
    saved = store.get_check(store_sid(client), r['check_id'])['location']
    assert (saved['lat'], saved['lon']) == (9.0, 38.7)


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(guard_routes, 'RATE_LIMIT', 3)
    codes = [check(client).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_config_exposes_only_public_values(client, monkeypatch):
    monkeypatch.setenv('PAYPAL_CLIENT_ID', 'public-id')
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', 'super-secret')
    body = client.get('/api/guard/config').get_data(as_text=True)
    assert 'public-id' in body and 'super-secret' not in body


def test_dashboard_loads_guard_assets(client):
    page = client.get('/').get_data(as_text=True)
    assert '/static/guard.js' in page and '/static/location.js' in page and 'id="guardForm"' in page
    assert client.get('/static/guard.js').status_code == 200
