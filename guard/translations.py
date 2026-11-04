"""
Part B — supported languages, their edge-tts voices, and fixed warning text
used when the AI is unavailable. Amharic text is reviewed by a native speaker.
"""

DEFAULT_LANGUAGE = 'en'

LANGUAGES = {
    'en': {'name': 'English', 'voice': 'en-US-AriaNeural'},
    'am': {'name': 'አማርኛ (Amharic)', 'voice': 'am-ET-MekdesNeural'},
}

# key → {lang: text}. Filled in by Part B; use {placeholders} for values.
MESSAGES: dict = {}


def normalize_language(lang: str | None) -> str:
    """Return a supported language code, falling back to DEFAULT_LANGUAGE."""
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def t(key: str, lang: str, **values) -> str:
    """Look up MESSAGES[key][lang] (falling back to English) and fill placeholders."""
    raise NotImplementedError


def voice_for(lang: str) -> str:
    return LANGUAGES[normalize_language(lang)]['voice']
