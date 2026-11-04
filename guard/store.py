"""
Part A — in-memory store for checks, payment history and trusted location.

Data is kept per browser session (session_id from Flask's signed cookie) and
lives only in server memory, so it resets when the server restarts. That is
fine for the demo and means no payment data is written to disk.

Only rounded location (see location.round_coords) may be stored here.
"""
import copy
import secrets
import threading
import time
from collections import OrderedDict

MAX_HISTORY = 50      # per session
MAX_CHECKS = 100      # per session
MAX_SESSIONS = 1000   # oldest sessions are dropped so memory can't grow forever
CHECK_TTL = 15 * 60   # a check can be paid for up to 15 minutes after it runs

_lock = threading.Lock()
_sessions: OrderedDict = OrderedDict()


def _session(session_id: str) -> dict:
    """Get (or create) one session's data. Caller must hold _lock."""
    s = _sessions.get(session_id)
    if s is None:
        s = {'checks': OrderedDict(), 'history': [], 'trusted': None}
        _sessions[session_id] = s
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    else:
        _sessions.move_to_end(session_id)
    return s


def _live_check(s: dict, check_id: str) -> dict | None:
    check = s['checks'].get(check_id)
    if check is None or time.time() - check['created_at'] > CHECK_TTL:
        return None
    return check


def save_check(session_id: str, check: dict) -> str:
    """Store a finished /api/guard/check result. Returns a new random check_id.
    `check` includes at least: level, score, amount, currency, recipient,
    location (rounded), created_at."""
    check_id = secrets.token_urlsafe(12)
    with _lock:
        s = _session(session_id)
        s['checks'][check_id] = {**copy.deepcopy(check), 'check_id': check_id,
                                 'confirmed': False, 'order_id': None, 'status': 'checked'}
        while len(s['checks']) > MAX_CHECKS:
            s['checks'].popitem(last=False)
    return check_id


def get_check(session_id: str, check_id: str) -> dict | None:
    """Return the saved check, or None if it doesn't exist for this session."""
    with _lock:
        check = _live_check(_session(session_id), check_id)
        return copy.deepcopy(check) if check else None


def mark_confirmed(session_id: str, check_id: str) -> bool:
    """User confirmed a MEDIUM check. Returns False if not found or not MEDIUM."""
    with _lock:
        check = _live_check(_session(session_id), check_id)
        if not check or check['level'] != 'MEDIUM':
            return False
        check['confirmed'] = True
        return True


def attach_order(session_id: str, check_id: str, order_id: str) -> None:
    """Remember which PayPal order belongs to which check."""
    with _lock:
        check = _live_check(_session(session_id), check_id)
        if check:
            check['order_id'] = order_id


def check_for_order(session_id: str, order_id: str) -> dict | None:
    """Find the check that created this order (used before capture)."""
    with _lock:
        s = _session(session_id)
        for check_id, check in s['checks'].items():
            if check.get('order_id') == order_id and _live_check(s, check_id):
                return copy.deepcopy(check)
    return None


def set_status(session_id: str, check_id: str, status: str) -> None:
    """'checked' → 'captured' | 'blocked'."""
    with _lock:
        check = _session(session_id)['checks'].get(check_id)
        if check:
            check['status'] = status


def record_payment(session_id: str, entry: dict) -> None:
    """Add to history. entry: {ts, amount, currency, recipient, level, score,
    status ('captured' | 'blocked' | 'cancelled'), city}"""
    with _lock:
        h = _session(session_id)['history']
        h.insert(0, copy.deepcopy(entry))
        del h[MAX_HISTORY:]


def history(session_id: str) -> list:
    """Newest first."""
    with _lock:
        return copy.deepcopy(_session(session_id)['history'])


def last_trusted(session_id: str) -> dict | None:
    """{lat, lon, city, ts} of the last captured payment, or None."""
    with _lock:
        return copy.deepcopy(_session(session_id)['trusted'])


def set_trusted(session_id: str, location: dict, ts: float) -> None:
    """Save a (rounded) location as trusted after a successful capture."""
    with _lock:
        _session(session_id)['trusted'] = {
            'lat': location['lat'], 'lon': location['lon'],
            'city': location.get('city'), 'ts': ts,
        }


def clear(session_id: str | None = None) -> None:
    """Forget one session (or everything, for tests)."""
    with _lock:
        if session_id is None:
            _sessions.clear()
        else:
            _sessions.pop(session_id, None)
