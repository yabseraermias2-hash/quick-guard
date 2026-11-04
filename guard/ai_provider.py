"""
Part B — one switch for the AI brain.

AI_PROVIDER=ollama → local Llama 3 via Ollama (laptop)
AI_PROVIDER=groq   → hosted Llama 3 via Groq's OpenAI-compatible API (deployed)
"""
import json
import os
from urllib.parse import urlparse

import requests

GROQ_BASE_URL = 'https://api.groq.com/openai/v1'
DEFAULT_GROQ_MODEL = 'llama-3.3-70b-versatile'
DEFAULT_OLLAMA_MODEL = 'llama3'
DEFAULT_OLLAMA_URL = 'http://localhost:11434'

_MAX_TOKENS = 700
_TEMPERATURE = 0.2   # low = consistent, less "creative" scoring


class AIError(Exception):
    """The AI call failed or returned something unusable. Callers fall back."""


def provider_name() -> str:
    """'ollama' or 'groq' (anything else is treated as 'ollama')."""
    p = os.getenv('AI_PROVIDER', 'ollama').strip().lower()
    return p if p in ('ollama', 'groq') else 'ollama'


def _ollama_url() -> str:
    """Plain HTTP is only allowed to this computer; anything remote must be HTTPS."""
    url = os.getenv('OLLAMA_URL', DEFAULT_OLLAMA_URL).strip().rstrip('/')
    parsed = urlparse(url)
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise AIError('OLLAMA_URL must be https unless it points at localhost.')
    return url


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in ```fences``` or add a sentence; find the object."""
    text = (text or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise AIError('AI reply contained no JSON object.')
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        raise AIError('AI reply was not valid JSON.')
    if not isinstance(data, dict):
        raise AIError('AI reply was not a JSON object.')
    return data


def _groq(system: str, user: str, timeout: float) -> str:
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not key:
        raise AIError('GROQ_API_KEY is not set.')
    resp = requests.post(
        f'{GROQ_BASE_URL}/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={
            'model': os.getenv('GROQ_MODEL', DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_object'},
            'temperature': _TEMPERATURE,
            'max_tokens': _MAX_TOKENS,
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        print(f'[AI] Groq HTTP {resp.status_code}')   # status only, never the key or body
        raise AIError(f'Groq returned HTTP {resp.status_code}.')
    return resp.json()['choices'][0]['message']['content']


def _ollama(system: str, user: str, timeout: float) -> str:
    resp = requests.post(
        f'{_ollama_url()}/api/chat',
        json={
            'model': os.getenv('OLLAMA_MODEL', DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}],
            'format': 'json',
            'stream': False,
            'options': {'temperature': _TEMPERATURE, 'num_predict': _MAX_TOKENS},
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise AIError(f'Ollama returned HTTP {resp.status_code}.')
    return resp.json().get('message', {}).get('content', '')


def chat_json(system: str, user: str, timeout: float = 20) -> dict:
    """Send one system + user message and return the reply parsed as JSON.
    Raises AIError on timeout, HTTP error, or invalid JSON."""
    call = _groq if provider_name() == 'groq' else _ollama
    try:
        return _parse_json(call(system, user, timeout))
    except AIError:
        raise
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        raise AIError(f'AI call failed ({type(e).__name__}).')
