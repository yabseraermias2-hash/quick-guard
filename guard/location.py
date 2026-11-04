"""
Part C — location and impossible-travel check.

Privacy: only rounded coordinates (about city level) are ever stored or
returned. Exact GPS from the browser is rounded the moment it arrives.
"""
import ipaddress
import math
import os
import threading

import requests

MAX_SPEED_KMH = 900        # faster than an airliner = impossible travel
COORD_DECIMALS = 1         # 0.1° ≈ 11 km
MIN_KM = 50                # closer than this is "same area" (IP lookups are fuzzy)
MIN_HOURS = 1 / 60         # treat anything under a minute as one minute (no divide-by-zero)
EARTH_RADIUS_KM = 6371.0

_IP_TIMEOUT = 4
_IP_CACHE_MAX = 500
_ip_cache: dict = {}
_ip_lock = threading.Lock()

# Clearly labeled DEMO MODE presets, used to simulate a payment elsewhere.
DEMO_CITIES = {
    'addis_ababa': {'city': 'Addis Ababa, Ethiopia', 'lat': 9.0,  'lon': 38.7},
    'new_york':    {'city': 'New York, USA',         'lat': 40.7, 'lon': -74.0},
    'london':      {'city': 'London, UK',            'lat': 51.5, 'lon': -0.1},
    'tokyo':       {'city': 'Tokyo, Japan',          'lat': 35.7, 'lon': 139.7},
}


def demo_mode() -> bool:
    return os.getenv('DEMO_MODE', 'false').strip().lower() == 'true'


def round_coords(lat: float, lon: float) -> tuple[float, float]:
    """Validate (-90..90, -180..180) and round to COORD_DECIMALS."""
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError('coordinates must be numbers')
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError('coordinates must be finite')
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('coordinates out of range')
    return round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def client_ip(request) -> str:
    """The real client IP, taking Render's proxy (X-Forwarded-For) into account.

    Only trust X-Forwarded-For behind Render's proxy, and only its LAST entry
    (the one Render's proxy added). Earlier entries can be faked by the client."""
    if os.getenv('RENDER'):
        forwarded = request.headers.get('X-Forwarded-For', '')
        parts = [p.strip() for p in forwarded.split(',') if p.strip()]
        if parts:
            return parts[-1]
    return request.remote_addr or ''


def _lookup_ipapi(ip: str) -> dict | None:
    r = requests.get(f'https://ipapi.co/{ip}/json/', timeout=_IP_TIMEOUT,
                     headers={'User-Agent': 'QUICK-Guard'})
    d = r.json()
    if r.status_code != 200 or d.get('error') or d.get('latitude') is None:
        return None
    return {'lat': d['latitude'], 'lon': d['longitude'],
            'city': ', '.join(x for x in (d.get('city'), d.get('country_name')) if x)}


def _lookup_ipwho(ip: str) -> dict | None:
    r = requests.get(f'https://ipwho.is/{ip}', timeout=_IP_TIMEOUT)
    d = r.json()
    if r.status_code != 200 or not d.get('success') or d.get('latitude') is None:
        return None
    return {'lat': d['latitude'], 'lon': d['longitude'],
            'city': ', '.join(x for x in (d.get('city'), d.get('country')) if x)}


def ip_lookup(ip: str) -> dict | None:
    """City-level lookup over HTTPS. Returns {lat, lon, city} (rounded) or None."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if not addr.is_global:          # localhost, home network, etc.
        return None
    key = str(addr)
    with _ip_lock:
        if key in _ip_cache:
            return _ip_cache[key]
    result = None
    for provider in (_lookup_ipapi, _lookup_ipwho):
        try:
            found = provider(key)
        except (requests.RequestException, ValueError):
            found = None
        if found:
            lat, lon = round_coords(found['lat'], found['lon'])
            result = {'lat': lat, 'lon': lon, 'city': found['city'] or 'Unknown city'}
            break
    with _ip_lock:
        if len(_ip_cache) >= _IP_CACHE_MAX:
            _ip_cache.clear()
        _ip_cache[key] = result
    return result


def resolve(browser_coords: dict | None, demo_city: str | None, request) -> dict | None:
    """Pick the location for this payment, in order: demo city (if DEMO_MODE),
    browser coords (rounded), IP lookup.
    Returns {lat, lon, city, source: 'demo' | 'browser' | 'ip'} or None."""
    if demo_city and demo_mode() and demo_city in DEMO_CITIES:
        return {**DEMO_CITIES[demo_city], 'source': 'demo'}
    if isinstance(browser_coords, dict):
        try:
            lat, lon = round_coords(browser_coords.get('lat'), browser_coords.get('lon'))
            return {'lat': lat, 'lon': lon, 'city': f'Your device (≈{lat}, {lon})',
                    'source': 'browser'}
        except (TypeError, ValueError):
            pass
    found = ip_lookup(client_ip(request))
    return {**found, 'source': 'ip'} if found else None


def evaluate(current: dict | None, last: dict | None, now: float) -> dict:
    """Compare this payment's location with the last trusted one.

    Returns {'known': bool, 'km': float | None, 'hours': float | None,
             'speed_kmh': float | None, 'impossible': bool,
             'from_city': str | None, 'to_city': str | None}
    'known' is False when either location is missing (no penalty).
    """
    result = {'known': False, 'km': None, 'hours': None, 'speed_kmh': None,
              'impossible': False,
              'from_city': (last or {}).get('city'),
              'to_city': (current or {}).get('city')}
    if not current or not last:
        return result
    km = haversine_km(last['lat'], last['lon'], current['lat'], current['lon'])
    hours = max((now - last['ts']) / 3600, MIN_HOURS)
    speed = km / hours
    result.update(known=True, km=round(km), hours=round(hours, 2), speed_kmh=round(speed),
                  impossible=km >= MIN_KM and speed > MAX_SPEED_KMH)
    return result
