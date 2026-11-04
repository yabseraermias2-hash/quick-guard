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
    if not location or not location.get('known'):
        return 0
    if location.get('impossible'):
        return IMPOSSIBLE_TRAVEL_SCORE
    if (location.get('speed_kmh') or 0) >= FAST_TRAVEL_KMH:
        return FAST_TRAVEL_SCORE
    return 0


def _level(score: int) -> str:
    if score >= HIGH_AT:
        return HIGH
    if score >= MEDIUM_AT:
        return MEDIUM
    return LOW


def decide(scam: dict, location: dict) -> dict:
    """Combine scam_check.check() and location.evaluate() results.

    Returns {'level': LOW | MEDIUM | HIGH, 'score': int 0-100,
             'reasons': [str]}   # short reason codes, e.g. 'impossible_travel'
    """
    s = max(0, min(100, int(scam.get('scam_score') or 0)))
    l = location_score(location)
    score = max(s, l)
    level = _level(score)

    reasons = []
    if s >= HIGH_AT:
        reasons.append('scam_likely')
    elif s >= MEDIUM_AT:
        reasons.append('scam_signs')
    if l == IMPOSSIBLE_TRAVEL_SCORE:
        reasons.append('impossible_travel')
    elif l == FAST_TRAVEL_SCORE:
        reasons.append('fast_travel')

    # Two medium warnings together are a strong signal: scam text arriving
    # from an unusual place looks like account takeover.
    if s >= MEDIUM_AT and l >= MEDIUM_AT:
        level = HIGH
        score = max(score, HIGH_AT)
        reasons.append('combined_signals')

    return {'level': level, 'score': score, 'reasons': reasons}
