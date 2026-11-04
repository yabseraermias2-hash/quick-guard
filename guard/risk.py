"""
Part D — the risk engine. Pure functions, no I/O, fully unit-tested.

Rule (tune here only):
  location_score = 90 if impossible travel (> 900 km/h)
                   50 if 500-900 km/h
                    0 otherwise / unknown
  score  = max(scam_score, location_score)
  level  = LOW (< 40) · MEDIUM (40-69) · HIGH (>= 70)
  If scam_score >= 40 AND location_score >= 40 → always HIGH.
"""

LOW, MEDIUM, HIGH = 'LOW', 'MEDIUM', 'HIGH'

MEDIUM_AT = 40
HIGH_AT = 70

IMPOSSIBLE_TRAVEL_SCORE = 90
FAST_TRAVEL_KMH = 500
FAST_TRAVEL_SCORE = 50


def location_score(location: dict) -> int:
    """Turn location.evaluate() output into a 0-100 score."""
    raise NotImplementedError


def decide(scam: dict, location: dict) -> dict:
    """Combine scam_check.check() and location.evaluate() results.

    Returns {'level': LOW | MEDIUM | HIGH, 'score': int 0-100,
             'reasons': [str]}   # short reason codes, e.g. 'impossible_travel'
    """
    raise NotImplementedError
