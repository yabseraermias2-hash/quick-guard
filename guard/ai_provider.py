"""
Part B — one switch for the AI brain.

AI_PROVIDER=ollama → local Llama 3 via Ollama (laptop)
AI_PROVIDER=groq   → hosted open-weight model on Groq's OpenAI-compatible API (deployed).
                     Default: OpenAI's gpt-oss-120b, falling back to gpt-oss-20b when the
                     first is rate-limited (each model has its own free-tier budget).
"""
import json
import os
import threading
from urllib.parse import urlparse

import requests

GROQ_BASE_URL = 'https://api.groq.com/openai/v1'
# Free Groq keys can't use Llama models any more (Enterprise-only), so the
# default is the best model a normal key can use. Override with GROQ_MODEL.
DEFAULT_GROQ_MODEL = 'openai/gpt-oss-120b'
DEFAULT_GROQ_FALLBACK_MODEL = 'openai/gpt-oss-20b'
DEFAULT_OLLAMA_MODEL = 'llama3'
DEFAULT_OLLAMA_URL = 'http://localhost:11434'

_MAX_TOKENS = 900    # room for a reasoning model's thinking + the JSON (Amharic uses more tokens)
_TEMPERATURE = 0.2   # low = consistent, less "creative" scoring
# Try the next model on these: rate limit, model missing, reply not valid JSON, Groq trouble.
_FALLBACK_STATUSES = {400, 404, 429, 500, 502, 503}

_last = threading.local()   # which model answered the last call on this thread


class AIError(Exception):
    """The AI call failed or returned something unusable. Callers fall back."""


def provider_name() -> str:
    """'ollama' or 'groq' (anything else is treated as 'ollama')."""
    p = os.getenv('AI_PROVIDER', 'ollama').strip().lower()
    return p if p in ('ollama', 'groq') else 'ollama'


def _label(provider: str, model: str) -> str:
    return f'Groq · {model}' if provider == 'groq' else f'Ollama · {model} (local)'


def groq_models() -> list[str]:
    """GROQ_MODEL first, then GROQ_FALLBACK_MODEL (set it to '' to turn the fallback off)."""
    first = os.getenv('GROQ_MODEL', DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    second = os.getenv('GROQ_FALLBACK_MODEL', DEFAULT_GROQ_FALLBACK_MODEL).strip()
    return [first] + ([second] if second and second != first else [])


def model_info() -> dict:
    """Which AI model a check will try first, for showing in the UI.
    Returns {'provider': 'groq' | 'ollama', 'model': str, 'label': str}."""
    if provider_name() == 'groq':
        model = groq_models()[0]
    else:
        model = os.getenv('OLLAMA_MODEL', DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
    return {'provider': provider_name(), 'model': model, 'label': _label(provider_name(), model)}


def last_model_label() -> str | None:
    """The model that answered the most recent successful chat_json() on this thread."""
    return getattr(_last, 'label', None)


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


def _groq(system: str, user: str, timeout: float) -> tuple[str, str]:
    """Returns (reply text, model that answered). Tries the fallback model when
    the first one is rate-limited or unavailable."""
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not key:
        raise AIError('GROQ_API_KEY is not set.')
    status = None
    for model in groq_models():
        body = {
            'model': model,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_object'},
            'temperature': _TEMPERATURE,
            'max_tokens': _MAX_TOKENS,
        }
        if model.startswith('openai/gpt-oss'):
            body['reasoning_effort'] = 'low'   # ~3x fewer tokens, same answers in our tests
        resp = requests.post(
            f'{GROQ_BASE_URL}/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json=body, timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'], model
        status = resp.status_code
        print(f'[AI] Groq {model} HTTP {status}')   # status only, never the key or body
        if status not in _FALLBACK_STATUSES:
            break                                    # e.g. 401 bad key: another model won't help
    raise AIError(f'Groq returned HTTP {status}.')


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
    model = os.getenv('OLLAMA_MODEL', DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
    return resp.json().get('message', {}).get('content', ''), model


def chat_json(system: str, user: str, timeout: float = 20) -> dict:
    """Send one system + user message and return the reply parsed as JSON.
    Raises AIError on timeout, HTTP error, or invalid JSON."""
    provider = provider_name()
    call = _groq if provider == 'groq' else _ollama
    _last.label = None
    try:
        text, model = call(system, user, timeout)
        data = _parse_json(text)
        _last.label = _label(provider, model)
        return data
    except AIError:
        raise
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        raise AIError(f'AI call failed ({type(e).__name__}).')
