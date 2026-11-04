"""
Part C — location and impossible-travel check.

Privacy: only rounded coordinates (about city level) are ever stored or
returned. Exact GPS from the browser is rounded the moment it arrives.
"""

MAX_SPEED_KMH = 900        # faster than an airliner = impossible travel
COORD_DECIMALS = 1         # 0.1° ≈ 11 km

# Clearly labeled DEMO MODE presets, used to simulate a payment elsewhere.
DEMO_CITIES = {
    'addis_ababa': {'city': 'Addis Ababa, Ethiopia', 'lat': 9.0,  'lon': 38.7},
    'new_york':    {'city': 'New York, USA',         'lat': 40.7, 'lon': -74.0},
    'london':      {'city': 'London, UK',            'lat': 51.5, 'lon': -0.1},
    'tokyo':       {'city': 'Tokyo, Japan',          'lat': 35.7, 'lon': 139.7},
}


def round_coords(lat: float, lon: float) -> tuple[float, float]:
    """Validate (-90..90, -180..180) and round to COORD_DECIMALS."""
    raise NotImplementedError


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    raise NotImplementedError


def client_ip(request) -> str:
    """The real client IP, taking Render's proxy (X-Forwarded-For) into account."""
    raise NotImplementedError


def ip_lookup(ip: str) -> dict | None:
    """City-level lookup over HTTPS. Returns {lat, lon, city} (rounded) or None."""
    raise NotImplementedError


def resolve(browser_coords: dict | None, demo_city: str | None, request) -> dict | None:
    """Pick the location for this payment, in order: demo city (if DEMO_MODE),
    browser coords (rounded), IP lookup.
    Returns {lat, lon, city, source: 'demo' | 'browser' | 'ip'} or None."""
    raise NotImplementedError


def evaluate(current: dict | None, last: dict | None, now: float) -> dict:
    """Compare this payment's location with the last trusted one.

    Returns {'known': bool, 'km': float | None, 'hours': float | None,
             'speed_kmh': float | None, 'impossible': bool,
             'from_city': str | None, 'to_city': str | None}
    'known' is False when either location is missing (no penalty).
    """
    raise NotImplementedError
