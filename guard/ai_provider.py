"""
Part B — one switch for the AI brain.

AI_PROVIDER=ollama → local Llama 3 via Ollama (laptop)
AI_PROVIDER=groq   → hosted Llama 3 via Groq's OpenAI-compatible API (deployed)
"""
import os

GROQ_BASE_URL = 'https://api.groq.com/openai/v1'
DEFAULT_GROQ_MODEL = 'llama-3.3-70b-versatile'
DEFAULT_OLLAMA_MODEL = 'llama3'


class AIError(Exception):
    """The AI call failed or returned something unusable. Callers fall back."""


def provider_name() -> str:
    """'ollama' or 'groq' (anything else is treated as 'ollama')."""
    p = os.getenv('AI_PROVIDER', 'ollama').strip().lower()
    return p if p in ('ollama', 'groq') else 'ollama'


def chat_json(system: str, user: str, timeout: float = 20) -> dict:
    """Send one system + user message and return the reply parsed as JSON.
    Raises AIError on timeout, HTTP error, or invalid JSON."""
    raise NotImplementedError
