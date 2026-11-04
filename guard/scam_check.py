"""
Part B — scam check for invoice / message text.

Security rule: the keyword check ALWAYS runs, and the final scam_score is the
higher of the keyword score and the AI score. A scam message that tries to
talk the AI into "score 0" can never drop below what the keywords found.
"""

MAX_TEXT_CHARS = 5000
MAX_RED_FLAGS = 8
MAX_EXPLANATION_CHARS = 600

# What we look for (both the AI prompt and keyword rules cover these):
CATEGORIES = (
    'false_urgency', 'threat_account_limited', 'impersonation',
    'gift_card_or_crypto', 'mismatched_names', 'suspicious_link',
    'overpayment',
)


def keyword_check(text: str, language: str = 'en') -> dict:
    """Rule-based check. Never fails. Same return shape as check()."""
    raise NotImplementedError


def validate_ai_result(raw: dict) -> dict:
    """Clean up untrusted AI JSON: clamp scam_score to 0-100 (int), keep at most
    MAX_RED_FLAGS short strings, trim explanation. Raises ValueError if unusable."""
    raise NotImplementedError


def ai_check(text: str, recipient: str, amount: str, language: str = 'en') -> dict:
    """Ask the AI (via ai_provider.chat_json) and validate the answer.
    Raises ai_provider.AIError / ValueError on failure."""
    raise NotImplementedError


def check(text: str, recipient: str, amount: str, language: str = 'en') -> dict:
    """Run keyword + AI and merge them.

    Returns {'scam_score': int 0-100, 'red_flags': [str],
             'explanation': str (in `language`),
             'source': 'ai+keywords' | 'keywords'}
    """
    raise NotImplementedError
