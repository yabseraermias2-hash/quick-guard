"""Part C — location rounding, haversine, impossible travel, IP handling."""
import math
import time

import pytest

from guard import location as loc


class FakeRequest:
    def __init__(self, remote_addr='', headers=None):
        self.remote_addr = remote_addr
        self.headers = headers or {}


# ── Rounding / privacy ────────────────────────────────────────────

def test_round_coords_keeps_only_city_level():
    assert loc.round_coords(9.03456, 38.74689) == (9.0, 38.7)


@pytest.mark.parametrize('lat,lon', [(91, 0), (0, 181), (math.nan, 0), (math.inf, 0), (True, 0), ('x', 0)])
def test_round_coords_rejects_bad_values(lat, lon):
    with pytest.raises((ValueError, TypeError)):
        loc.round_coords(lat, lon)


def test_browser_coords_are_rounded_in_resolve():
    out = loc.resolve({'lat': 51.50735, 'lon': -0.12776}, None, FakeRequest())
    assert out['lat'] == 51.5 and out['lon'] == -0.1 and out['source'] == 'browser'


# ── Haversine ─────────────────────────────────────────────────────

def test_haversine_known_distances():
    assert loc.haversine_km(0, 0, 0, 0) == 0
    # Addis Ababa → London is about 5,900 km
    assert 5800 < loc.haversine_km(9.0, 38.7, 51.5, -0.1) < 6000
    # New York → Tokyo is about 10,850 km
    assert 10700 < loc.haversine_km(40.7, -74.0, 35.7, 139.7) < 11000


# ── Impossible travel ────────────────────────────────────────────

def addis(ts):
    return {'lat': 9.0, 'lon': 38.7, 'city': 'Addis Ababa, Ethiopia', 'ts': ts}


TOKYO = {'lat': 35.7, 'lon': 139.7, 'city': 'Tokyo, Japan'}


def test_addis_to_tokyo_in_5_minutes_is_impossible():
    now = time.time()
    r = loc.evaluate(TOKYO, addis(now - 300), now)
    assert r['known'] and r['impossible']
    assert r['speed_kmh'] > loc.MAX_SPEED_KMH
    assert r['from_city'] == 'Addis Ababa, Ethiopia' and r['to_city'] == 'Tokyo, Japan'


def test_addis_to_tokyo_after_two_days_is_fine():
    now = time.time()
    r = loc.evaluate(TOKYO, addis(now - 2 * 86400), now)
    assert r['known'] and not r['impossible']


def test_same_area_is_never_impossible():
    now = time.time()
    nearby = {'lat': 9.1, 'lon': 38.8, 'city': 'Near Addis'}
    assert not loc.evaluate(nearby, addis(now - 1), now)['impossible']


def test_no_history_means_unknown_and_no_penalty():
    r = loc.evaluate(TOKYO, None, time.time())
    assert r['known'] is False and r['impossible'] is False


def test_zero_elapsed_time_does_not_crash():
    now = time.time()
    assert loc.evaluate(TOKYO, addis(now), now)['impossible']


# ── Demo mode ─────────────────────────────────────────────────────

def test_demo_city_only_when_demo_mode_on(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    assert loc.resolve(None, 'tokyo', FakeRequest())['source'] == 'demo'
    monkeypatch.setenv('DEMO_MODE', 'false')
    assert loc.resolve(None, 'tokyo', FakeRequest()) is None   # localhost → no IP lookup


def test_unknown_demo_city_is_ignored(monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'true')
    assert loc.resolve(None, 'atlantis', FakeRequest()) is None


# ── IP handling ───────────────────────────────────────────────────

def test_private_ips_are_not_looked_up(monkeypatch):
    monkeypatch.setattr(loc, '_lookup_ipapi', lambda ip: pytest.fail('should not look up'))
    for ip in ('127.0.0.1', '192.168.1.5', '10.0.0.2', '::1', 'not-an-ip'):
        assert loc.ip_lookup(ip) is None


def test_ip_lookup_rounds_and_falls_back(monkeypatch):
    loc._ip_cache.clear()
    monkeypatch.setattr(loc, '_lookup_ipapi', lambda ip: None)
    monkeypatch.setattr(loc, '_lookup_ipwho', lambda ip: {'lat': 40.71277, 'lon': -74.00597, 'city': 'New York, US'})
    assert loc.ip_lookup('8.8.8.8') == {'lat': 40.7, 'lon': -74.0, 'city': 'New York, US'}


def test_forwarded_for_only_trusted_on_render(monkeypatch):
    req = FakeRequest('10.1.1.1', {'X-Forwarded-For': '6.6.6.6, 203.0.113.9'})
    monkeypatch.delenv('RENDER', raising=False)
    assert loc.client_ip(req) == '10.1.1.1'
    monkeypatch.setenv('RENDER', 'true')
    # the last entry is the one Render's proxy added; the first can be faked
    assert loc.client_ip(req) == '203.0.113.9'
