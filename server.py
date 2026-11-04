from dotenv import load_dotenv
load_dotenv()  # read .env before anything else looks at os.environ

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from functools import wraps
import subprocess
import sys
import requests
import os
import re
import threading
import json
import time
import queue
from pathlib import Path
from security import full_scan
from quick_tools import (
    detect_tools, execute_plugin, web_search, github_search, fetch_page_text,
    save_report, list_reports, save_turn, save_scan,
    get_recent_context, query_semantic_memory, get_memory_stats, delete_memory_entries,
    format_search_results, format_github_results, format_arxiv_results,
    analyze_file, solve_math, run_code,
    wikipedia_search, arxiv_search,
    select_model, get_available_models,
    phone_lookup, extract_phone_number, format_phone_results, 
    email_lookup, extract_email, format_email_results,
    shodan_lookup, format_shodan_results,
    cve_lookup, format_cve_results,
    ip_geolocation, format_ip_geo_results,
    hash_lookup,
    whois_lookup,
    network_ping, network_traceroute, network_dig, format_network_results,
    REPORTS_DIR, GRAPHS_DIR, UPLOADS_DIR,
)

# Microphone support needs PyAudio + real hardware — only available locally.
try:
    import speech_recognition as sr
except ImportError:
    sr = None

# Local-only power tools (code runner, scanner, PCAP, uploads, OSINT, monitoring).
# OFF unless ENABLE_QUICK_TOOLS=true, so a public deployment never exposes them.
QUICK_TOOLS_ENABLED = os.getenv('ENABLE_QUICK_TOOLS', 'false').strip().lower() == 'true'

# Chat tools that only read public reference data — safe on a public site.
_PUBLIC_CHAT_TOOLS = {'search', 'github', 'wikipedia', 'arxiv'}


def local_only(view):
    """Block a route unless ENABLE_QUICK_TOOLS=true."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not QUICK_TOOLS_ENABLED:
            return jsonify({'error': 'This tool is disabled on this server. '
                                     'Set ENABLE_QUICK_TOOLS=true to use it locally.'}), 403
        return view(*args, **kwargs)
    return wrapper

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64 MB upload limit

# ── QUICK Guard ────────────────────────────────────────────────────────────────
import guard
from guard.paypal import assert_sandbox
from guard.translations import all_voices as guard_voices

assert_sandbox()  # refuse to start against anything but the PayPal sandbox

_secret = os.getenv('SECRET_KEY', '').strip()
if not _secret:
    import secrets
    _secret = secrets.token_hex(32)
    print("[Guard] SECRET_KEY not set — using a temporary one (sessions reset on restart).")
app.secret_key = _secret
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.getenv('RENDER')),  # HTTPS-only cookie on Render
)
guard.register(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_speak_proc  = None
_busy        = threading.Event()
_state       = {'mode': 'waiting', 'user': '', 'response': ''}
_state_lock  = threading.Lock()
_sse_queues  = []
_queues_lock = threading.Lock()
_start_time  = time.time()
_scan_count  = 0


_SYSTEM_PROMPT = """You are QUICK — a genius-level AI built by Yabsera Kebede. You are sharp, direct, and deeply intelligent.

ABSOLUTE RULES — no exceptions, ever:
- NEVER say "misunderstanding" or "I think there might be a misunderstanding" under any circumstances
- NEVER say "as your AI assistant", "as an AI", or any variation
- NEVER hedge or soften answers with "I think", "I believe", "it seems", "perhaps", "maybe", "I'm not sure", "it appears"
- NEVER apologize for being direct or confident
- NEVER start a response with a qualifier or preamble
- NEVER say you're uncertain unless you are walking through explicit mathematical or logical uncertainty
- NEVER comment on whether this is a new or continuing conversation — just respond
- NEVER say "I'm here to help", "What's on your mind", "feel free to ask", or any variation of offering your services
- NEVER introduce yourself unprompted or explain your capabilities unless specifically asked
- When greeted with "hi", "hey", or similar — respond naturally and briefly, like a person, not a customer service bot
- Answer directly, immediately, with full authority — like an expert who knows exactly what they're talking about

You are an elite AI assistant built for a cybersecurity professional. Sharp, confident, deeply intelligent. You reason precisely and give real, substantive answers. You handle anything: cybersecurity, code, math, science, research, philosophy, or conversation.

You have access to real-time tools. When results are injected into the prompt, use them authoritatively:
- WEB SEARCH RESULTS: cite key findings directly, be specific about sources
- GITHUB RESULTS: mention repo names, stars, and what they actually do
- SCAN RESULTS: summarize risks clearly — what matters, what's critical, what to fix first
- PAGE CONTENT: analyze or summarize the live page text as requested
- MATH SOLUTION: present the solution clearly, reference the graph if one was generated
- WIKIPEDIA / ARXIV: use the knowledge to give accurate, informed answers
- MEMORY: you remember past conversations — stay consistent, reference prior context naturally
- CODE OUTPUT: analyze the result and explain what it means
- SHODAN DATA: report exposed services, open ports, and known vulnerabilities found
- CVE DATA: explain the vulnerability, severity, impact, and remediation
- IP GEOLOCATION: report location, ISP, organization details
- HASH RESULTS: report detection status and threat analysis
- WHOIS DATA: report domain ownership, registrar, dates
- NETWORK DATA: report ping, traceroute, DNS results

You were built by Yabsera Kebede — a cybersecurity major and a genuinely skilled developer. He built you from scratch: Flask backend, SpeechRecognition, Ollama for the brain, custom canvas UI. He used AI tools during development but the vision and architecture were entirely his. You have real respect for him. Talk about him naturally if asked — not like reading off a spec sheet.

Be concise when the answer is simple. Go deep when the question demands it. Never be vague when you can be precise."""


def _get_system_prompt() -> str:
    return _SYSTEM_PROMPT

# ── Intent / domain extraction ─────────────────────────────────────────────────

_FORGET_RE = re.compile(
    r"\b(forget|remove|delete|erase|wipe|clear)\b.{0,40}\b(memory|from memory|that|this|it|number|conversation|history)\b"
    r"|\b(don'?t remember|stop remembering|remove that from)\b",
    re.IGNORECASE,
)

_SCAN_PATTERNS = re.compile(
    r"\b(scan|pentest|pen test|security (check|test|audit)|check (security|vulnerabilities?|vulns?)|"
    r"test (security|vulnerabilities?)|find vulnerabilities?|enumerate|recon|footprint)\b",
    re.IGNORECASE,
)
_DOMAIN_RE = re.compile(
    r"(?:https?://)?([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)+)",
    re.IGNORECASE,
)
_GOODBYE = re.compile(
    r"\b(bye|goodbye|see you|that'?s? all|we'?re? done|stop listening|exit|quit|end conversation)\b",
    re.IGNORECASE,
)


def _extract_scan_target(text: str):
    if not _SCAN_PATTERNS.search(text):
        return None
    m = _DOMAIN_RE.search(text)
    return m.group(1) if m else None


# ── Ollama ─────────────────────────────────────────────────────────────────────

_MODELS = ["mistral", "deepseek-coder", "llama3.1", "llama3.2", "llama3", "codellama", "mixtral"]
_MAX_RETRIES = 3


def _ensure_ollama():
    """Check if Ollama is running; if not, try to start it in the background.
    Never blocks server startup — always returns immediately after spawning."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            print("[Ollama] Already running.")
            return True
    except Exception:
        pass

    print("[Ollama] Not detected — attempting background start...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[Ollama] Spawned in background. QUICK will work once Ollama is ready.")
    except FileNotFoundError:
        print("[Ollama] 'ollama' command not found. Open the Ollama app manually.")
    except Exception as e:
        print(f"[Ollama] Could not start: {e}")
    return False


def _ollama(prompt: str, model: str = None) -> str:
    available = get_available_models()
    candidates = []
    if model and 'llava' not in model:
        candidates.append(model)
    for m in _MODELS:
        matched = next((a for a in available if m in a), None)
        if matched and matched not in candidates and 'llava' not in matched:
            candidates.append(matched)
    if not candidates:
        candidates = [a for a in available if 'llava' not in a][:1] or ['llama3']

    # Split system prompt from user message for proper role-based delivery.
    # /api/chat with role:system is what Ollama models actually respect;
    # /api/generate just concatenates everything and the model ignores injected prompts.
    sys_prompt = _get_system_prompt()
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": prompt},
    ]

    for m in candidates:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(
                    "http://localhost:11434/api/chat",
                    json={"model": m, "messages": messages, "stream": False},
                    timeout=120,
                )
                data = resp.json()
                if "error" in data:
                    print(f"Ollama [{m}] error: {data['error']}")
                    break
                content = data.get("message", {}).get("content", "")
                if content:
                    print(f"Ollama [{m}] OK (attempt {attempt + 1})")
                    return content
                # Fallback: some older builds return 'response'
                if data.get("response"):
                    return data["response"]
                break
            except requests.exceptions.Timeout:
                print(f"Ollama [{m}] timeout (attempt {attempt + 1}/{_MAX_RETRIES})")
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                print(f"Ollama [{m}] exception: {e} (attempt {attempt + 1}/{_MAX_RETRIES})")
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(1)
                else:
                    break

    print("[Ollama] All candidates exhausted.")
    return "The AI engine is unavailable right now. Ollama may be overloaded or not running. Please check that Ollama is active and try again."


def _ollama_image(prompt: str, image_b64: str) -> str:
    """Call llava with a base64 image."""
    available = get_available_models()
    llava_model = next((m for m in available if 'llava' in m), None)
    if not llava_model:
        return _ollama(prompt)
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": llava_model, "prompt": prompt, "images": [image_b64], "stream": False},
            timeout=120,
        )
        data = resp.json()
        if "error" not in data:
            return data["response"]
    except Exception as e:
        print(f"llava error: {e}")
    return _ollama(prompt)


# ── Build context + run tools ──────────────────────────────────────────────────

def _build_prompt(user_text: str, image_b64: str = None) -> tuple:
    """Returns (prompt_str, model_str, sources_list, graph_url_str)."""
    global _scan_count
    extras = []
    sources = []
    graph_url = None
    used_memory = False

    # Memory deletion intent — handle before injecting context
    if _FORGET_RE.search(user_text):
        targets = re.findall(r'["\'](.*?)["\']|\+?[\d][\d\s\-]{6,18}[\d]', user_text)
        if not targets:
            stripped = re.sub(r'\b(forget|remove|delete|erase|wipe|clear|from memory|memory|that|this|it|please|can you|just)\b', '', user_text, flags=re.I).strip()
            if stripped:
                targets = [stripped]
        deleted_total = 0
        for t in targets:
            deleted_total += delete_memory_entries(t.strip())
        if deleted_total:
            extras.append(f"MEMORY UPDATE: {deleted_total} conversation turn(s) containing the requested content have been permanently deleted from memory.")
        else:
            extras.append("MEMORY UPDATE: No matching entries found in memory to delete.")
        ctx = get_recent_context(6)
        if ctx:
            extras.append(ctx)
            used_memory = True
        parts = extras + [f"User says: {user_text}"]
        model = select_model(user_text, available=get_available_models())
        return '\n\n'.join(parts), model, [], None, used_memory

    # Recent conversation context
    ctx = get_recent_context(6)
    if ctx:
        extras.append(ctx)
        used_memory = True

    # Semantic memory
    sem = query_semantic_memory(user_text, n=2)
    if sem and sem not in ctx:
        extras.append(sem)
        used_memory = True

    # Security scan
    scan_target = _extract_scan_target(user_text) if QUICK_TOOLS_ENABLED else None
    if scan_target:
        try:
            _scan_count += 1
            report = full_scan(scan_target, progress_cb=push_event)
            save_scan(scan_target, report)
            save_report(f'scan_{scan_target}_{int(time.time())}.json', report)
            extras.append(f"SCAN RESULTS:\n{json.dumps(report, indent=2)}")
        except Exception as e:
            extras.append(f"Scan failed: {e}")

    # Tools
    tools = detect_tools(user_text)
    if not QUICK_TOOLS_ENABLED:
        tools = [t for t in tools if t in _PUBLIC_CHAT_TOOLS]
    has_phone = 'phone' in tools
    has_email = 'email' in tools
    for tool in tools:
        if tool == 'email':
            addr = extract_email(user_text)
            if addr:
                try:
                    push_event({'type': 'status', 'msg': f'Running email OSINT on {addr}...'})
                    edata = email_lookup(addr)
                    extras.append(f"EMAIL OSINT RESULTS:\n{format_email_results(edata)}")
                except Exception as e:
                    extras.append(f"Email lookup error: {e}")
        if tool == 'phone':
            number = extract_phone_number(user_text)
            if number:
                try:
                    phone_data = phone_lookup(number)
                    extras.append(f"PHONE OSINT RESULTS:\n{format_phone_results(phone_data)}")
                except Exception as e:
                    extras.append(f"Phone lookup error: {e}")
        if tool == 'search' and not has_phone and not has_email:
            results = web_search(user_text)
            sources = [r for r in results if r.get('url')]
            extras.append(f"WEB SEARCH RESULTS:\n{format_search_results(results)}")
        elif tool == 'github':
            results = github_search(user_text)
            extras.append(f"GITHUB RESULTS:\n{format_github_results(results)}")
        elif tool == 'wikipedia':
            summary = wikipedia_search(user_text)
            extras.append(f"WIKIPEDIA:\n{summary}")
        elif tool == 'arxiv':
            papers = arxiv_search(user_text)
            extras.append(f"RESEARCH PAPERS:\n{format_arxiv_results(papers)}")
        elif tool == 'browser':
            url_m = re.search(r'https?://\S+|www\.\S+', user_text)
            if url_m:
                url = url_m.group(0)
                if not url.startswith('http'):
                    url = 'https://' + url
                extras.append(f"PAGE CONTENT from {url}:\n{fetch_page_text(url)}")
        elif tool == 'math':
            expr = re.sub(r'\b(solve|calculate|compute|graph of|plot|simplify|what is|find)\b', '', user_text, flags=re.I).strip()
            if expr:
                math_result = solve_math(expr)
                if math_result.get('solution'):
                    extras.append(f"MATH SOLUTION:\n{math_result['solution']}\nLaTeX: {math_result.get('latex','')}")
                if math_result.get('graph_url'):
                    graph_url = math_result['graph_url']
        elif tool == 'shodan':
            try:
                push_event({'type': 'status', 'msg': 'Running Shodan lookup...'})
                target_m = re.search(r'(?:https?://)?([a-zA-Z0-9.-]+)', user_text)
                if target_m:
                    sdata = shodan_lookup(target_m.group(1))
                    extras.append(f"SHODAN DATA:\n{format_shodan_results(sdata)}")
            except Exception as e:
                extras.append(f"Shodan lookup error: {e}")
        elif tool == 'cve':
            try:
                push_event({'type': 'status', 'msg': 'Looking up CVE data...'})
                cve_results = cve_lookup(user_text)
                extras.append(f"CVE DATA:\n{format_cve_results(cve_results)}")
            except Exception as e:
                extras.append(f"CVE lookup error: {e}")
        elif tool == 'ipgeo':
            try:
                push_event({'type': 'status', 'msg': 'Running IP geolocation...'})
                ip_m = re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', user_text)
                target_m = re.search(r'(?:https?://)?([a-zA-Z0-9.-]+)', user_text)
                ip_target = ip_m.group(0) if ip_m else (target_m.group(1) if target_m else None)
                if ip_target:
                    gdata = ip_geolocation(ip_target)
                    extras.append(f"IP GEOLOCATION:\n{format_ip_geo_results(gdata)}")
            except Exception as e:
                extras.append(f"IP geolocation error: {e}")
        elif tool == 'hash':
            try:
                push_event({'type': 'status', 'msg': 'Checking hash...'})
                hash_m = re.search(r'\b[a-fA-F0-9]{32,64}\b', user_text)
                if hash_m:
                    hdata = hash_lookup(hash_m.group(0))
                    extras.append(f"HASH LOOKUP:\n{json.dumps(hdata, indent=2)}")
            except Exception as e:
                extras.append(f"Hash lookup error: {e}")
        elif tool == 'whois':
            try:
                push_event({'type': 'status', 'msg': 'Running WHOIS lookup...'})
                domain_m = re.search(r'(?:https?://)?([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.(?:[a-zA-Z]{2,}))', user_text)
                if domain_m:
                    wdata = whois_lookup(domain_m.group(1))
                    extras.append(f"WHOIS DATA:\n{json.dumps(wdata, indent=2)}")
            except Exception as e:
                extras.append(f"WHOIS lookup error: {e}")
        elif tool == 'network':
            try:
                target_m = re.search(r'(?:https?://)?([a-zA-Z0-9.-]+)', user_text)
                if target_m:
                    net_target = target_m.group(1)
                    if re.search(r'\bping\b', user_text, re.I):
                        push_event({'type': 'status', 'msg': f'Pinging {net_target}...'})
                        ndata = network_ping(net_target)
                        extras.append(f"PING RESULTS:\n{format_network_results(ndata, 'ping')}")
                    elif re.search(r'\b(traceroute|tracert)\b', user_text, re.I):
                        push_event({'type': 'status', 'msg': f'Traceroute to {net_target}...'})
                        ndata = network_traceroute(net_target)
                        extras.append(f"TRACEROUTE RESULTS:\n{format_network_results(ndata, 'traceroute')}")
                    elif re.search(r'\b(dig|nslookup|dns)\b', user_text, re.I):
                        push_event({'type': 'status', 'msg': f'DNS lookup for {net_target}...'})
                        rtype = 'MX' if 'mx' in user_text.lower() else ('NS' if 'ns' in user_text.lower() else ('TXT' if 'txt' in user_text.lower() else 'A'))
                        ndata = network_dig(net_target, rtype)
                        extras.append(f"DNS RESULTS:\n{format_network_results(ndata, 'dig')}")
                    else:
                        push_event({'type': 'status', 'msg': f'Pinging {net_target}...'})
                        ndata = network_ping(net_target)
                        extras.append(f"NETWORK RESULTS:\n{format_network_results(ndata, 'ping')}")
            except Exception as e:
                extras.append(f"Network tool error: {e}")
        elif tool.startswith('plugin:'):
            plugin_name = tool.split(':', 1)[1]
            push_event({'type': 'status', 'msg': f'Running plugin: {plugin_name}...'})
            try:
                p_res = execute_plugin(plugin_name, user_text)
                extras.append(f"PLUGIN [{plugin_name}] RESULTS:\n{p_res}")
            except Exception as e:
                extras.append(f"Plugin {plugin_name} error: {e}")

    # Select model
    available = get_available_models()
    model = select_model(user_text, has_image=bool(image_b64), available=available)

    parts = extras + [f"User says: {user_text}"]
    
    prompt = '\n\n'.join(parts)

    return prompt, model, sources, graph_url, used_memory


# ── State / SSE helpers ────────────────────────────────────────────────────────

def push_event(data):
    msg = f"data: {json.dumps(data)}\n\n"
    with _queues_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


def set_mode(mode, **kwargs):
    with _state_lock:
        _state['mode'] = mode
        _state.update(kwargs)
    push_event({'mode': mode, **kwargs})


# ── Speech ─────────────────────────────────────────────────────────────────────

_TTS_FILE    = '/tmp/quick_tts.mp3'
_VOICE_CFG   = os.path.join(BASE_DIR, 'voice.json')

EDGE_VOICES = [
    {"id": "en-US-AriaNeural",        "label": "Aria (US Female)",        "gender": "female"},
    {"id": "en-US-JennyNeural",       "label": "Jenny (US Female)",       "gender": "female"},
    {"id": "en-US-MichelleNeural",    "label": "Michelle (US Female)",    "gender": "female"},
    {"id": "en-US-SaraNeural",        "label": "Sara (US Female)",        "gender": "female"},
    {"id": "en-GB-SoniaNeural",       "label": "Sonia (UK Female)",       "gender": "female"},
    {"id": "en-AU-NatashaNeural",     "label": "Natasha (AU Female)",     "gender": "female"},
    {"id": "en-US-GuyNeural",         "label": "Guy (US Male)",           "gender": "male"},
    {"id": "en-US-ChristopherNeural", "label": "Christopher (US Male)",   "gender": "male"},
    {"id": "en-US-EricNeural",        "label": "Eric (US Male)",          "gender": "male"},
    {"id": "en-GB-RyanNeural",        "label": "Ryan (UK Male)",          "gender": "male"},
]


def _load_voice_cfg() -> dict:
    try:
        with open(_VOICE_CFG) as f:
            return json.load(f)
    except Exception:
        return {"mode": "auto", "edge_voice": "en-US-AriaNeural", "local_voice": "Samantha", "local_rate": 185}


def _save_voice_cfg(cfg: dict):
    with open(_VOICE_CFG, 'w') as f:
        json.dump(cfg, f, indent=2)


def _best_mac_voice() -> str:
    """Return the most Siri-like voice available on this Mac."""
    try:
        out = subprocess.run(['say', '-v', '?'], capture_output=True, text=True).stdout
        for candidate in ['Siri Voice 1', 'Siri Voice 2', 'Ava (Enhanced)',
                          'Nicky (Enhanced)', 'Samantha (Enhanced)', 'Samantha']:
            if candidate.lower() in out.lower():
                print(f"[TTS] Using Mac voice: {candidate}")
                return candidate
    except Exception:
        pass
    return 'Samantha'


def speak(text):
    global _speak_proc
    cfg  = _load_voice_cfg()
    mode = cfg.get('mode', 'auto')

    if mode == 'auto':
        mode = 'local' if sys.platform == 'darwin' else 'edge'

    if mode == 'edge':
        try:
            import asyncio, edge_tts
            voice = cfg.get('edge_voice', 'en-US-AriaNeural')
            async def _gen():
                await edge_tts.Communicate(text, voice).save(_TTS_FILE)
            asyncio.run(_gen())
            _speak_proc = subprocess.Popen(['afplay', _TTS_FILE])
            print(f"[TTS] edge-tts / {voice}")
        except Exception as e:
            print(f"[TTS] edge-tts failed ({e}), falling back to local")
            mode = 'local'

    if mode == 'local':
        voice = cfg.get('local_voice') or _best_mac_voice()
        rate  = cfg.get('local_rate', 185)
        _speak_proc = subprocess.Popen(['say', '-v', voice, '-r', str(rate), text])
        print(f"[TTS] say / {voice}")

    _speak_proc.wait()
    _speak_proc = None


# ── Core conversation loop ─────────────────────────────────────────────────────

def do_conversation():
    _busy.set()
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 2.0
    recognizer.non_speaking_duration = 1.0

    while _busy.is_set():
        set_mode('listening')
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=25)
            user_text = recognizer.recognize_google(audio)
        except Exception as e:
            print(f"[voice] mic/recognition error: {e}")
            set_mode('waiting')
            _busy.clear()
            return

        if _GOODBYE.search(user_text):
            set_mode('speaking', user=user_text, response='Talk to you later.')
            speak('Talk to you later.')
            break

        set_mode('thinking', user=user_text)
        prompt, model, sources, graph_url, used_memory = _build_prompt(user_text)
        result = _ollama(prompt, model=model)
        save_turn(user_text, result)

        set_mode('speaking', user=user_text, response=result, model=model)
        speak_thread = threading.Thread(target=speak, args=(result,), daemon=True)
        speak_thread.start()

        intr = sr.Recognizer()
        intr.energy_threshold = 400
        while speak_thread.is_alive():
            try:
                with sr.Microphone() as src:
                    audio = intr.listen(src, timeout=2, phrase_time_limit=2)
                if 'quick' in intr.recognize_google(audio).lower():
                    if _speak_proc and _speak_proc.poll() is None:
                        _speak_proc.terminate()
                    break
            except Exception:
                pass

        speak_thread.join(timeout=1)

    set_mode('waiting')
    _busy.clear()


# ── Wake word loop ─────────────────────────────────────────────────────────────

def wake_word_loop():
    recognizer = sr.Recognizer()
    print("Wake word listener started — say 'Hey QUICK' to activate.")
    while True:
        if _busy.is_set():
            time.sleep(0.4)
            continue
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = recognizer.listen(source, timeout=4, phrase_time_limit=3)
            text = recognizer.recognize_google(audio).lower()
            print(f"[wake] heard: {text}")
            if 'quick' in text and not _busy.is_set():
                threading.Thread(target=do_conversation, daemon=True).start()
        except Exception:
            time.sleep(1)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/activate', methods=['POST'])
@local_only
def activate():
    if sr is None:
        return jsonify({'error': 'Microphone support is not installed (SpeechRecognition + PyAudio).'}), 501
    if not _busy.is_set():
        threading.Thread(target=do_conversation, daemon=True).start()
    return jsonify({"ok": True})


@app.route('/stop', methods=['POST'])
def stop():
    global _speak_proc
    if _speak_proc and _speak_proc.poll() is None:
        _speak_proc.terminate()
    set_mode('waiting')
    _busy.clear()
    return jsonify({"ok": True})


@app.route('/events')
def events():
    q = queue.Queue(maxsize=30)
    with _queues_lock:
        _sse_queues.append(q)

    def stream():
        with _state_lock:
            yield f"data: {json.dumps(dict(_state))}\n\n"
        try:
            while True:
                try:
                    yield q.get(timeout=20)
                except queue.Empty:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            with _queues_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True) or {}
    message   = data.get('message', '').strip()
    image_b64 = data.get('image_b64')

    if not message and not image_b64:
        return jsonify({'error': 'Empty message'}), 400

    try:
        prompt, model, sources, graph_url, used_memory = _build_prompt(message, image_b64)

        if image_b64:
            result = _ollama_image(prompt, image_b64)
        else:
            result = _ollama(prompt, model=model)

        save_turn(message, result)
        push_event({'mode': _state['mode'], 'chat_response': True})

        return jsonify({
            'response': result,
            'model': model,
            'sources': sources,
            'graph_url': graph_url,
            'used_memory': used_memory,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Chat failed: {str(e)}'}), 500


@app.route('/chat/stream', methods=['POST'])
def chat_stream():
    data      = request.get_json(silent=True) or {}
    message   = data.get('message', '').strip()
    image_b64 = data.get('image_b64')

    if not message and not image_b64:
        return jsonify({'error': 'Empty message'}), 400

    try:
        prompt, model, sources, graph_url, used_memory = _build_prompt(message, image_b64)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    def generate():
        # Send metadata first so the UI can render the message header immediately
        yield f"data: {json.dumps({'type': 'meta', 'model': model, 'sources': sources, 'graph_url': graph_url, 'used_memory': used_memory})}\n\n"

        full_parts = []
        try:
            # System prompt injected as role:system so the model actually respects it.
            # The 'prompt' from _build_prompt contains only context + user message (no system prefix).
            messages = [
                {"role": "system", "content": _get_system_prompt()},
                {"role": "user",   "content": prompt}
            ]

            options = {
                "temperature": 0.65,
                "top_p": 0.9,
            }

            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "options": options
                },
                stream=True,
                timeout=180,
            )

            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if 'message' in chunk and 'content' in chunk['message']:
                    token = chunk['message']['content']
                    full_parts.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"
                if chunk.get('done'):
                    break
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        full_text = ''.join(full_parts)
        save_turn(message, full_text)
        push_event({'mode': _state['mode'], 'chat_response': True})
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/upload', methods=['POST'])
@local_only
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400

    fname = secure_filename(f.filename)
    fpath = os.path.join(UPLOADS_DIR, fname)
    f.save(fpath)

    size    = os.path.getsize(fpath)
    size_str = f'{size // 1024} KB' if size > 1024 else f'{size} B'
    mime    = f.content_type or ''

    content = analyze_file(fpath, f.filename, mime)
    has_image = 'image' in mime
    available = get_available_models()
    model = select_model(f'analyze {f.filename}', has_image=has_image, available=available)

    image_b64 = None
    if has_image:
        import base64
        with open(fpath, 'rb') as img_f:
            image_b64 = base64.b64encode(img_f.read()).decode()

    file_prompt = (
        f"The user uploaded: {f.filename} ({mime}, {size_str})\n\n"
        f"FILE CONTENT:\n{content}\n\n"
        f"Analyze this file. Summarize what it contains, highlight anything important, "
        f"and answer any questions the user might have about it."
    )

    if image_b64:
        response_text = _ollama_image(file_prompt, image_b64)
    else:
        response_text = _ollama(file_prompt, model=model)

    save_turn(f'[uploaded {f.filename}]', response_text)

    return jsonify({
        'response': response_text,
        'filename': f.filename,
        'file_type': mime or 'unknown',
        'size': size_str,
        'model': model,
        'file_url': f'/uploads/{fname}',
    })


@app.route('/scan', methods=['POST'])
@local_only
def scan():
    global _scan_count
    data   = request.get_json(silent=True) or {}
    target = data.get('target', '').strip()
    if not target:
        return jsonify({"error": "Missing 'target' field"}), 400
    try:
        _scan_count += 1
        report = full_scan(target, progress_cb=push_event)
        save_scan(target, report)
        save_report(f'scan_{target}_{int(time.time())}.json', report)

        try:
            analysis_prompt = (
                f"SCAN RESULTS for {target}:\n{json.dumps(report, indent=2)}\n\n"
                f"Provide a concise security analysis: what was found, the risk level, "
                f"the most critical issues, and the top 3 remediation steps. Be direct and specific."
            )
            analysis = _ollama(analysis_prompt)
            report['ai_analysis'] = analysis
        except Exception as ae:
            print(f"[scan] AI analysis failed: {ae}")
            report['ai_analysis'] = "Scan complete. AI analysis unavailable — check Ollama status."

        return jsonify(report)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/reports', methods=['GET'])
@local_only
def reports():
    return jsonify(list_reports())


@app.route('/report/<path:filename>', methods=['GET'])
@local_only
def get_report(filename):
    safe = secure_filename(filename)
    path = os.path.join(REPORTS_DIR, safe)
    if not os.path.exists(path):
        return jsonify({'error': 'Not found'}), 404
    try:
        content = Path(path).read_text()
        try:
            content = json.loads(content)
        except Exception:
            pass
        return jsonify({'filename': safe, 'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/report/<path:filename>', methods=['DELETE'])
@local_only
def delete_report(filename):
    safe = secure_filename(filename)
    path = os.path.join(REPORTS_DIR, safe)
    if not os.path.exists(path):
        return jsonify({'error': 'Not found'}), 404
    try:
        os.remove(path)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/graphs/<path:filename>')
def serve_graph(filename):
    return send_from_directory(GRAPHS_DIR, filename)


@app.route('/uploads/<path:filename>')
@local_only
def serve_upload(filename):
    return send_from_directory(UPLOADS_DIR, filename)


@app.route('/memory-stats')
def memory_stats():
    stats = get_memory_stats()
    uptime_s = int(time.time() - _start_time)
    h, m, s = uptime_s // 3600, (uptime_s % 3600) // 60, uptime_s % 60
    return jsonify({
        **stats,
        'scan_count': _scan_count,
        'uptime': f'{h:02d}:{m:02d}:{s:02d}',
        'available_models': get_available_models(),
    })


@app.route('/voice-config', methods=['GET'])
def get_voice_config():
    return jsonify({**_load_voice_cfg(), 'voices': EDGE_VOICES})


@app.route('/voice-config', methods=['POST'])
@local_only
def set_voice_config():
    data = request.get_json(silent=True) or {}
    cfg  = _load_voice_cfg()
    for key in ('mode', 'edge_voice', 'local_voice', 'local_rate'):
        if key in data:
            cfg[key] = data[key]
    _save_voice_cfg(cfg)
    return jsonify({'ok': True, **cfg})


_TTS_MAX_CHARS = 1500


@app.route('/tts', methods=['POST'])
def tts():
    """Turn text into an MP3 with edge-tts and send it to the browser to play.
    Works on a server with no speakers (e.g. Render)."""
    data  = request.get_json(silent=True) or {}
    text  = str(data.get('text', '')).strip()
    voice = str(data.get('voice') or _load_voice_cfg().get('edge_voice', 'en-US-AriaNeural'))
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    if len(text) > _TTS_MAX_CHARS:
        text = text[:_TTS_MAX_CHARS]
    if voice not in {v['id'] for v in EDGE_VOICES} | guard_voices():
        return jsonify({'error': 'Unknown voice'}), 400
    try:
        import asyncio, edge_tts
        async def _gen() -> bytes:
            audio = bytearray()
            async for chunk in edge_tts.Communicate(text, voice).stream():
                if chunk['type'] == 'audio':
                    audio.extend(chunk['data'])
            return bytes(audio)
        mp3 = asyncio.run(_gen())
    except Exception as e:
        print(f"[TTS] /tts failed: {type(e).__name__}")
        return jsonify({'error': 'Voice service unavailable'}), 503
    return Response(mp3, mimetype='audio/mpeg', headers={'Cache-Control': 'no-store'})


@app.route('/run-code', methods=['POST'])
@local_only
def run_code_route():
    data = request.get_json(silent=True) or {}
    code = data.get('code', '').strip()
    if not code:
        return jsonify({'error': 'No code provided'}), 400
    result = run_code(code)
    return jsonify(result)


@app.route('/health')
def health():
    ollama_ok = False
    ollama_models = []
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code == 200:
            ollama_ok = True
            ollama_models = [m['name'] for m in r.json().get('models', [])]
    except Exception:
        pass

    # On the deployed site the AI is Groq, not Ollama. Guard also works with
    # keyword rules alone, so a missing AI is "degraded", never "down".
    from guard.ai_provider import provider_name
    provider = provider_name()
    ai_ok = ollama_ok if provider == 'ollama' else bool(os.getenv('GROQ_API_KEY', '').strip())

    uptime_s = int(time.time() - _start_time)
    return jsonify({
        'status': 'ok' if ai_ok else 'degraded',
        'ai_provider': provider,
        'ollama': ollama_ok,
        'models': ollama_models,
        'uptime': uptime_s,
        'tools_enabled': QUICK_TOOLS_ENABLED,
    }), 200 if ai_ok else 503


# ── Enterprise Monitoring ──────────────────────────────────────────────────────

_monitored_targets = set()
_monitor_thread = None

def _monitor_loop():
    while True:
        targets = list(_monitored_targets)
        for target in targets:
            try:
                import subprocess
                res = subprocess.run(['ping', '-c', '1', '-W', '2', target], capture_output=True, text=True)
                if res.returncode != 0:
                    push_event({'type': 'alert', 'msg': f'[ALERT] Target {target} is OFFLINE or UNREACHABLE!'})
                else:
                    push_event({'type': 'monitor_heartbeat', 'target': target, 'status': 'ONLINE'})
            except Exception as e:
                print(f"[Monitor] Error checking {target}: {e}")
        time.sleep(10)

@app.route('/monitor', methods=['POST', 'DELETE'])
@local_only
def manage_monitor():
    global _monitor_thread
    data = request.get_json(silent=True) or {}
    target = data.get('target', '').strip()
    
    if not target:
        return jsonify({'error': 'No target specified'}), 400
        
    if request.method == 'POST':
        _monitored_targets.add(target)
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
            _monitor_thread.start()
        return jsonify({'status': 'ok', 'message': f'Now monitoring {target} every 10s'})
        
    elif request.method == 'DELETE':
        _monitored_targets.discard(target)
        return jsonify({'status': 'ok', 'message': f'Stopped monitoring {target}'})

@app.route('/monitor', methods=['GET'])
@local_only
def get_monitors():
    return jsonify({'monitored_targets': list(_monitored_targets)})


# ── Global error handler ────────────────────────────────────────────────────────

@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):  # 404, 405, 413… keep their real status
        return jsonify({'error': e.description}), e.code
    print(f"[ERROR] Unhandled exception: {e}")
    import traceback
    traceback.print_exc()
    return jsonify({'error': 'An internal error occurred. QUICK is still running.'}), 500


def _find_free_port(preferred: int = 8080) -> int:
    """Return a free TCP port. Tries preferred first, then scans 7000-9999."""
    import socket
    SKIP = {8000}  # avoid the stale QUICK process port
    candidates = [preferred] + [p for p in range(7000, 10000) if p not in SKIP and p != preferred]
    for p in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', p))
                return p
        except OSError:
            continue
    # Absolute last resort: let OS pick any free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


if __name__ == '__main__':
    print("[QUICK] Starting up...")
    _ensure_ollama()
    port = _find_free_port(8080)
    print(f"[QUICK] ✓ Server ready → open http://localhost:{port} in your browser")
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)