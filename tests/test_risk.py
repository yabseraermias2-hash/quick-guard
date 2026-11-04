"""Part D — risk engine unit tests."""
import pytest

from guard import risk
from guard.risk import HIGH, LOW, MEDIUM


def scam(score):
    return {'scam_score': score}


UNKNOWN = {'known': False, 'impossible': False, 'speed_kmh': None}
NORMAL = {'known': True, 'impossible': False, 'speed_kmh': 40}
FAST = {'known': True, 'impossible': False, 'speed_kmh': 650}
IMPOSSIBLE = {'known': True, 'impossible': True, 'speed_kmh': 120000}


@pytest.mark.parametrize('score,level', [
    (0, LOW), (39, LOW), (40, MEDIUM), (69, MEDIUM), (70, HIGH), (100, HIGH),
])
def test_scam_score_thresholds(score, level):
    assert risk.decide(scam(score), UNKNOWN)['level'] == level


def test_location_scores():
    assert risk.location_score(UNKNOWN) == 0
    assert risk.location_score(None) == 0
    assert risk.location_score(NORMAL) == 0
    assert risk.location_score(FAST) == risk.FAST_TRAVEL_SCORE
    assert risk.location_score(IMPOSSIBLE) == risk.IMPOSSIBLE_TRAVEL_SCORE


def test_safe_payment_is_low():
    r = risk.decide(scam(5), NORMAL)
    assert r == {'level': LOW, 'score': 5, 'reasons': []}


def test_impossible_travel_alone_blocks():
    r = risk.decide(scam(0), IMPOSSIBLE)
    assert r['level'] == HIGH and r['reasons'] == ['impossible_travel']


def test_fast_travel_alone_asks_to_confirm():
    r = risk.decide(scam(0), FAST)
    assert r['level'] == MEDIUM and r['reasons'] == ['fast_travel']


def test_two_medium_signals_become_high():
    r = risk.decide(scam(45), FAST)
    assert r['level'] == HIGH and r['score'] >= risk.HIGH_AT
    assert 'combined_signals' in r['reasons']


def test_scam_reasons():
    assert risk.decide(scam(85), UNKNOWN)['reasons'] == ['scam_likely']
    assert risk.decide(scam(50), UNKNOWN)['reasons'] == ['scam_signs']


@pytest.mark.parametrize('bad', [-50, 400, None])
def test_bad_scores_are_clamped(bad):
    r = risk.decide({'scam_score': bad}, UNKNOWN)
    assert 0 <= r['score'] <= 100
