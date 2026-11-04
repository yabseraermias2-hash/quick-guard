"""
Part A — in-memory store for checks, payment history and trusted location.

Data is kept per browser session (session_id from Flask's signed cookie) and
lives only in server memory, so it resets when the server restarts. That is
fine for the demo and means no payment data is written to disk.

Only rounded location (see location.round_coords) may be stored here.
"""
import threading

MAX_HISTORY = 50   # per session
MAX_CHECKS = 100   # per session

_lock = threading.Lock()
_sessions: dict = {}


def save_check(session_id: str, check: dict) -> str:
    """Store a finished /api/guard/check result. Returns a new random check_id.
    `check` includes at least: level, score, amount, currency, recipient,
    location (rounded), created_at."""
    raise NotImplementedError


def get_check(session_id: str, check_id: str) -> dict | None:
    """Return the saved check, or None if it doesn't exist for this session."""
    raise NotImplementedError


def mark_confirmed(session_id: str, check_id: str) -> bool:
    """User confirmed a MEDIUM check. Returns False if not found or not MEDIUM."""
    raise NotImplementedError


def attach_order(session_id: str, check_id: str, order_id: str) -> None:
    """Remember which PayPal order belongs to which check."""
    raise NotImplementedError


def check_for_order(session_id: str, order_id: str) -> dict | None:
    """Find the check that created this order (used before capture)."""
    raise NotImplementedError


def record_payment(session_id: str, entry: dict) -> None:
    """Add to history. entry: {ts, amount, currency, recipient, level, score,
    status ('captured' | 'blocked' | 'cancelled'), city}"""
    raise NotImplementedError


def history(session_id: str) -> list:
    """Newest first."""
    raise NotImplementedError


def last_trusted(session_id: str) -> dict | None:
    """{lat, lon, city, ts} of the last captured payment, or None."""
    raise NotImplementedError


def set_trusted(session_id: str, location: dict, ts: float) -> None:
    """Save a (rounded) location as trusted after a successful capture."""
    raise NotImplementedError
