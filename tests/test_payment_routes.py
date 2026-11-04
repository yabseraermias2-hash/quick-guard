"""Part A — the store and the /api/paypal routes: money only moves for
LOW checks or confirmed MEDIUM checks, and the server re-checks at capture."""
import time

import pytest

from guard import paypal, store
from guard.web import session_id


@pytest.fixture(autouse=True)
def clean_store():
    store.clear()


@pytest.fixture
def fake_paypal(monkeypatch):
    calls = {'create': 0, 'capture': 0}

    def create(amount, currency, payee, desc, **kw):
        calls['create'] += 1
        return {'id': 'ORDER1234567', 'status': 'CREATED', 'approve_url': None}

    def capture(order_id):
        calls['capture'] += 1
        return {'id': order_id, 'status': 'COMPLETED', 'capture_id': 'CAP1',
                'amount': '25.00', 'currency': 'USD'}
    monkeypatch.setattr(paypal, 'create_order', create)
    monkeypatch.setattr(paypal, 'capture_order', capture)
    return calls


def make_check(client, level, **extra):
    """Save a check in the same session the test client uses."""
    with client.session_transaction() as sess:
        sess['sid'] = 'test-session'
    check = {'level': level, 'score': 10, 'amount': '25.00', 'currency': 'USD',
             'recipient': 'friend@example.com', 'created_at': time.time(),
             'location': {'lat': 9.0, 'lon': 38.7, 'city': 'Addis Ababa, Ethiopia'}, **extra}
    return store.save_check('test-session', check)


def test_low_check_can_be_paid_and_captured(client, fake_paypal):
    cid = make_check(client, 'LOW')
    r = client.post('/api/paypal/order', json={'check_id': cid})
    assert r.status_code == 200 and r.get_json()['order_id'] == 'ORDER1234567'

    r = client.post('/api/paypal/capture', json={'order_id': 'ORDER1234567'})
    assert r.status_code == 200 and r.get_json()['status'] == 'COMPLETED'

    hist = store.history('test-session')
    assert hist[0]['status'] == 'captured' and hist[0]['city'] == 'Addis Ababa, Ethiopia'
    assert store.last_trusted('test-session')['lat'] == 9.0


def test_high_check_is_refused(client, fake_paypal):
    cid = make_check(client, 'HIGH')
    r = client.post('/api/paypal/order', json={'check_id': cid})
    assert r.status_code == 403
    assert fake_paypal['create'] == 0


def test_medium_needs_confirmation(client, fake_paypal):
    cid = make_check(client, 'MEDIUM')
    assert client.post('/api/paypal/order', json={'check_id': cid}).status_code == 403
    assert store.mark_confirmed('test-session', cid)
    assert client.post('/api/paypal/order', json={'check_id': cid}).status_code == 200


def test_cannot_confirm_a_high_check():
    cid = store.save_check('s', {'level': 'HIGH', 'created_at': time.time()})
    assert store.mark_confirmed('s', cid) is False


def test_unknown_check_and_other_sessions_check(client, fake_paypal):
    assert client.post('/api/paypal/order', json={'check_id': 'nope'}).status_code == 404
    other = store.save_check('someone-else', {'level': 'LOW', 'score': 0, 'amount': '1.00',
                                              'currency': 'USD', 'recipient': 'a@b.co',
                                              'created_at': time.time()})
    assert client.post('/api/paypal/order', json={'check_id': other}).status_code == 404


def test_expired_check_is_refused(client, fake_paypal):
    cid = make_check(client, 'LOW', created_at=time.time() - store.CHECK_TTL - 1)
    assert client.post('/api/paypal/order', json={'check_id': cid}).status_code == 404


def test_cannot_capture_twice(client, fake_paypal):
    cid = make_check(client, 'LOW')
    client.post('/api/paypal/order', json={'check_id': cid})
    assert client.post('/api/paypal/capture', json={'order_id': 'ORDER1234567'}).status_code == 200
    assert client.post('/api/paypal/capture', json={'order_id': 'ORDER1234567'}).status_code == 403
    assert fake_paypal['capture'] == 1


def test_capture_of_unknown_order(client, fake_paypal):
    assert client.post('/api/paypal/capture', json={'order_id': 'ORDER9999999'}).status_code == 404


def test_session_id_is_random_and_stable(client):
    import server
    with server.app.test_request_context():
        a = session_id()
        assert session_id() == a and len(a) >= 16


def test_history_is_capped():
    for i in range(store.MAX_HISTORY + 5):
        store.record_payment('s', {'ts': i})
    h = store.history('s')
    assert len(h) == store.MAX_HISTORY and h[0]['ts'] == store.MAX_HISTORY + 4
