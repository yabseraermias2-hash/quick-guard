"""
QUICK tool integrations — memory, search, GitHub, browser, math, files, code sandbox.
All capabilities implemented natively in Python for use with any Ollama model.
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, 'quick_memory.json')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')
GRAPHS_DIR  = os.path.join(BASE_DIR, 'graphs')
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
DB_DIR      = os.path.join(BASE_DIR, 'quick_db')

for _d in (REPORTS_DIR, GRAPHS_DIR, UPLOADS_DIR, DB_DIR):
    os.makedirs(_d, exist_ok=True)

requests.packages.urllib3.disable_warnings()


# ── Plugin Architecture ────────────────────────────────────────────────────────

PLUGINS_DIR = os.path.join(BASE_DIR, 'plugins')
os.makedirs(PLUGINS_DIR, exist_ok=True)

_plugin_registry = {}

def register_plugin_tool(name: str, trigger_regex: re.Pattern, handler: callable):
    _plugin_registry[name] = {
        'trigger': trigger_regex,
        'handler': handler
    }

def load_plugins():
    import importlib.util
    if not os.path.exists(PLUGINS_DIR):
        return
    for filename in os.listdir(PLUGINS_DIR):
        if filename.endswith(".py") and filename != "__init__.py":
            plugin_name = filename[:-3]
            filepath = os.path.join(PLUGINS_DIR, filename)
            try:
                spec = importlib.util.spec_from_file_location(plugin_name, filepath)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, 'initialize'):
                    mod.initialize(register_plugin_tool)
            except Exception as e:
                print(f"[Plugins] Error loading {filename}: {e}")

# Load plugins on startup
load_plugins()




# ── ChromaDB (persistent semantic memory) ─────────────────────────────────────

_chroma = None
_collection = None

def _init_chroma() -> bool:
    global _chroma, _collection
    if _collection is not None:
        return True
    try:
        import chromadb
        _chroma = chromadb.PersistentClient(path=DB_DIR)
        _collection = _chroma.get_or_create_collection('conversations')
        return True
    except Exception as e:
        print(f'[ChromaDB] unavailable: {e}')
        return False


# ── JSON fallback memory ───────────────────────────────────────────────────────

def _load_mem() -> dict:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {'conversations': [], 'scan_results': [], 'notes': []}


def _save_mem(mem: dict):
    with open(MEMORY_FILE, 'w') as f:
        json.dump(mem, f, indent=2)


# ── Public memory API ──────────────────────────────────────────────────────────

def save_turn(user: str, response: str):
    """Persist a conversation turn to both JSON and ChromaDB."""
    mem = _load_mem()
    mem['conversations'].append({
        'ts': datetime.now(timezone.utc).isoformat(),
        'user': user,
        'response': response,
    })
    mem['conversations'] = mem['conversations'][-60:]
    _save_mem(mem)

    if _init_chroma():
        try:
            _collection.add(
                documents=[f"User: {user}\nQUICK: {response}"],
                ids=[f"t{int(time.time() * 1000)}"],
                metadatas=[{
                    'user': user[:400],
                    'response': response[:400],
                    'ts': datetime.now(timezone.utc).isoformat(),
                }]
            )
        except Exception:
            pass


def save_scan(target: str, report: dict):
    mem = _load_mem()
    mem['scan_results'].append({
        'ts': datetime.now(timezone.utc).isoformat(),
        'target': target,
        'report': report,
    })
    mem['scan_results'] = mem['scan_results'][-20:]
    _save_mem(mem)


def get_recent_context(n: int = 6) -> str:
    """Last n turns from JSON memory as a prompt block."""
    mem = _load_mem()
    recent = mem['conversations'][-n:]
    if not recent:
        return ''
    lines = ['[Recent conversation history]']
    for t in recent:
        lines.append(f"User: {t['user']}")
        snippet = t['response'][:220] + ('...' if len(t['response']) > 220 else '')
        lines.append(f"QUICK: {snippet}")
    return '\n'.join(lines)


def query_semantic_memory(text: str, n: int = 3) -> str:
    """Semantic search in ChromaDB — finds past conversations relevant to query."""
    if not _init_chroma():
        return ''
    try:
        count = _collection.count()
        if count == 0:
            return ''
        results = _collection.query(query_texts=[text], n_results=min(n, count))
        docs = results.get('documents', [[]])[0]
        if not docs:
            return ''
        return '[Relevant past conversations]\n' + '\n---\n'.join(docs)
    except Exception:
        return ''


def delete_memory_entries(query: str) -> int:
    """Remove conversation turns that contain `query` from JSON memory and ChromaDB.
    Returns the number of turns deleted."""
    query_lower = query.lower().strip()
    mem = _load_mem()
    before = len(mem['conversations'])
    mem['conversations'] = [
        t for t in mem['conversations']
        if query_lower not in t.get('user', '').lower()
        and query_lower not in t.get('response', '').lower()
    ]
    deleted = before - len(mem['conversations'])
    _save_mem(mem)

    # Best-effort ChromaDB removal — query for matching docs and delete them
    if deleted > 0 and _init_chroma():
        try:
            count = _collection.count()
            if count > 0:
                results = _collection.query(query_texts=[query], n_results=min(10, count))
                ids = results.get('ids', [[]])[0]
                if ids:
                    _collection.delete(ids=ids)
        except Exception:
            pass

    return deleted


def get_memory_stats() -> dict:
    mem = _load_mem()
    total = 0
    if _init_chroma():
        try:
            total = _collection.count()
        except Exception:
            pass
    return {
        'recent_turns': len(mem['conversations']),
        'total_turns': total,
        'scan_results': len(mem['scan_results']),
    }


# ── Model selection ────────────────────────────────────────────────────────────

_models_cache: list = []
_models_ts: float = 0


def get_available_models() -> list:
    global _models_cache, _models_ts
    if _models_cache and time.time() - _models_ts < 60:
        return _models_cache
    try:
        r = requests.get('http://localhost:11434/api/tags', timeout=5)
        names = [m['name'].split(':')[0] for m in r.json().get('models', [])]
        _models_cache = list(dict.fromkeys(names))
        _models_ts = time.time()
        return _models_cache
    except Exception:
        return ['llama3.2', 'llama3']


_CODE_RE          = re.compile(r'\b(code|program|script|function|class|debug|fix bug|write|implement|algorithm|syntax|compile|refactor)\b', re.I)
_DEEP_ANALYSIS_RE = re.compile(r'\b(deep analysis|detailed analysis|full analysis|analyze in depth|explain in detail|comprehensive|think through|reason through|compare and contrast|research report|break.*down.*thoroughly)\b', re.I)


def select_model(text: str, has_image: bool = False, available: list = None) -> str:
    if available is None:
        available = get_available_models()

    def pick(name):
        return next((m for m in available if name in m), None)

    if has_image and pick('llava'):
        return pick('llava')
    if _CODE_RE.search(text) and pick('codellama'):
        return pick('codellama')
    # Use mixtral only when user explicitly asks for deep/comprehensive analysis
    if _DEEP_ANALYSIS_RE.search(text) and pick('mixtral'):
        return pick('mixtral')
    # Default: llama3.2 — fast and light
    return pick('llama3.2') or pick('llama3') or pick('mixtral') or (available[0] if available else 'llama3')


# ── Web search ─────────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> list:
    brave_key = os.environ.get('BRAVE_API_KEY', '').strip()
    return _brave_search(query, brave_key, max_results) if brave_key else _ddg_search(query, max_results)


def _brave_search(query: str, api_key: str, max_results: int) -> list:
    try:
        r = requests.get(
            'https://api.search.brave.com/res/v1/web/search',
            headers={'Accept': 'application/json', 'X-Subscription-Token': api_key},
            params={'q': query, 'count': max_results},
            timeout=10,
        )
        items = r.json().get('web', {}).get('results', [])[:max_results]
        return [{'title': i.get('title'), 'url': i.get('url'), 'snippet': i.get('description')} for i in items]
    except Exception as e:
        return [{'error': f'Brave search failed: {e}'}]


def _ddg_search(query: str, max_results: int) -> list:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return [
                {'title': r.get('title'), 'url': r.get('href'), 'snippet': r.get('body')}
                for r in ddgs.text(query, max_results=max_results)
            ]
    except ImportError:
        return [{'error': 'Install duckduckgo-search for web search'}]
    except Exception as e:
        return [{'error': f'Search failed: {e}'}]


# ── GitHub search ──────────────────────────────────────────────────────────────

def github_search(query: str, kind: str = 'repositories', max_results: int = 5) -> list:
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        r = requests.get(
            f'https://api.github.com/search/{kind}',
            headers=headers,
            params={'q': query, 'per_page': max_results, 'sort': 'stars', 'order': 'desc'},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get('items', [])[:max_results]
        return [{
            'name': i.get('full_name'), 'description': i.get('description'),
            'url': i.get('html_url'), 'stars': i.get('stargazers_count'),
            'language': i.get('language'), 'updated': str(i.get('updated_at', ''))[:10],
        } for i in items]
    except Exception as e:
        return [{'error': f'GitHub search failed: {e}'}]


# ── Wikipedia ──────────────────────────────────────────────────────────────────

def wikipedia_search(query: str) -> str:
    try:
        import wikipediaapi
        wiki = wikipediaapi.Wikipedia('QUICK-AI/1.0 (contact@quick.ai)', 'en')
        page = wiki.page(query)
        if page.exists():
            return page.summary[:2000]
        return f'No Wikipedia article found for "{query}".'
    except ImportError:
        return 'Wikipedia unavailable. Install wikipedia-api.'
    except Exception as e:
        return f'Wikipedia search failed: {e}'


# ── ArXiv research papers ──────────────────────────────────────────────────────

def arxiv_search(query: str, max_results: int = 3) -> list:
    try:
        import arxiv
        search = arxiv.Search(query=query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance)
        return [{
            'title': r.title,
            'authors': [a.name for a in r.authors[:3]],
            'summary': r.summary[:300],
            'url': r.entry_id,
            'published': str(r.published)[:10],
        } for r in search.results()]
    except ImportError:
        return [{'error': 'Install arxiv package for research paper search'}]
    except Exception as e:
        return [{'error': str(e)}]


# ── Browser ────────────────────────────────────────────────────────────────────

def screenshot_url(url: str, out_name: str = None) -> str:
    try:
        from playwright.sync_api import sync_playwright
        if not out_name:
            out_name = f'shot_{re.sub(r"[^\\w]","_",url)[:50]}.png'
        out_path = os.path.join(REPORTS_DIR, out_name)
        with sync_playwright() as p:
            br = p.chromium.launch(headless=True)
            page = br.new_page()
            page.goto(url, timeout=20000)
            page.screenshot(path=out_path, full_page=True)
            br.close()
        return out_path
    except ImportError:
        return 'Install playwright for screenshots'
    except Exception as e:
        return f'Screenshot failed: {e}'


def fetch_page_text(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            br = p.chromium.launch(headless=True)
            page = br.new_page()
            page.goto(url, timeout=20000)
            text = page.inner_text('body')
            br.close()
        return text[:3000]
    except Exception:
        pass
    try:
        r = requests.get(url, timeout=10, verify=False)
        text = re.sub(r'<[^>]+>', ' ', r.text)
        return re.sub(r'\s+', ' ', text).strip()[:3000]
    except Exception as e:
        return f'Could not fetch page: {e}'


# ── Math solver + graph ────────────────────────────────────────────────────────

_MATH_RE = re.compile(
    r'\b(solve|calculate|compute|derive|integrate|differentiate|simplify|factor|'
    r'expand|equation|polynomial|matrix|determinant|eigenvalue|limit|derivative|'
    r'integral|algebra|calculus|geometry|trigonometry|graph of|plot|f\(x\))\b'
    r'|[\d]+\s*[\+\-\*\/\^]\s*[\d]',
    re.IGNORECASE
)


def is_math_question(text: str) -> bool:
    return bool(_MATH_RE.search(text))


def solve_math(expression: str) -> dict:
    """Solve/simplify expression with sympy, generate graph if plottable."""
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations, implicit_multiplication_application,
        )
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np

        transformations = standard_transformations + (implicit_multiplication_application,)
        x = sp.Symbol('x')
        result: dict = {}

        if '=' in expression:
            lhs_s, rhs_s = expression.split('=', 1)
            lhs = parse_expr(lhs_s.strip(), transformations=transformations, local_dict={'x': x})
            rhs = parse_expr(rhs_s.strip(), transformations=transformations, local_dict={'x': x})
            solutions = sp.solve(lhs - rhs, x)
            result['solution'] = f"x = {solutions}"
            result['latex'] = sp.latex(solutions)
        else:
            expr = parse_expr(expression.strip(), transformations=transformations, local_dict={'x': x})
            simplified = sp.simplify(expr)
            result['solution'] = str(simplified)
            result['latex'] = sp.latex(simplified)

            if x in simplified.free_symbols:
                x_vals = np.linspace(-10, 10, 500)
                f_lam = sp.lambdify(x, simplified, 'numpy')
                try:
                    y_vals = np.clip(f_lam(x_vals), -1e6, 1e6)
                    fig, ax = plt.subplots(figsize=(6, 3.5), facecolor='#050d1a')
                    ax.set_facecolor('#050d1a')
                    ax.plot(x_vals, y_vals, color='#00d4ff', linewidth=2)
                    ax.axhline(0, color='#1a3355', linewidth=0.8)
                    ax.axvline(0, color='#1a3355', linewidth=0.8)
                    ax.grid(True, color='#0a1628', linewidth=0.5, alpha=0.7)
                    ax.tick_params(colors='#5588aa', labelsize=8)
                    for spine in ax.spines.values():
                        spine.set_edgecolor('#1a3355')
                    ax.set_xlabel('x', color='#5588aa', fontsize=9)
                    ax.set_ylabel('f(x)', color='#5588aa', fontsize=9)
                    ax.set_title(f'f(x) = {expression}', color='#a8d8ff', fontsize=9, pad=8)
                    plt.tight_layout()
                    graph_name = f'math_{int(time.time())}.png'
                    plt.savefig(os.path.join(GRAPHS_DIR, graph_name), dpi=120, facecolor='#050d1a')
                    plt.close()
                    result['graph_url'] = f'/graphs/{graph_name}'
                except Exception:
                    plt.close()

        return result
    except ImportError:
        return {'error': 'Install sympy and matplotlib for math solving'}
    except Exception as e:
        return {'error': str(e)}


# ── File analysis ──────────────────────────────────────────────────────────────

def analyze_file(filepath: str, original_name: str, mime_type: str = '') -> str:
    ext = os.path.splitext(original_name)[1].lower()

    if ext == '.pdf' or 'pdf' in mime_type:
        return _read_pdf(filepath)
    if ext in ('.docx', '.doc') or 'word' in mime_type:
        return _read_word(filepath)
    if ext in ('.csv',) or 'csv' in mime_type:
        return _analyze_csv(filepath)
    if ext in ('.xlsx', '.xls'):
        return _analyze_excel(filepath)
    if ext in ('.pcap', '.cap', '.pcapng') or 'pcap' in mime_type:
        return json.dumps(analyze_pcap(filepath), indent=2)
    if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp') or 'image' in mime_type:
        return _read_image_ocr(filepath)
    if ext in ('.txt', '.py', '.js', '.ts', '.html', '.css', '.json', '.md', '.yaml', '.yml', '.sh', '.c', '.cpp', '.java', '.go', '.rs'):
        try:
            return Path(filepath).read_text(errors='replace')[:6000]
        except Exception as e:
            return f'Error reading file: {e}'
    return f'File received ({ext}). Binary or unsupported format.'


def _read_pdf(filepath: str) -> str:
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages[:15]:
                pages.append(page.extract_text() or '')
        return '\n'.join(pages)[:6000]
    except ImportError:
        try:
            from pypdf import PdfReader
            r = PdfReader(filepath)
            return '\n'.join(p.extract_text() or '' for p in r.pages[:15])[:6000]
        except ImportError:
            return 'PDF reading unavailable. Install pdfplumber.'
    except Exception as e:
        return f'Error reading PDF: {e}'


def _read_word(filepath: str) -> str:
    try:
        from docx import Document
        doc = Document(filepath)
        return '\n'.join(p.text for p in doc.paragraphs)[:6000]
    except ImportError:
        return 'Install python-docx to read Word documents.'
    except Exception as e:
        return f'Error reading Word doc: {e}'


def _analyze_csv(filepath: str) -> str:
    try:
        import pandas as pd
        df = pd.read_csv(filepath)
        out = f"Shape: {df.shape[0]} rows × {df.shape[1]} cols\n"
        out += f"Columns: {', '.join(df.columns.tolist())}\n\n"
        out += f"Preview:\n{df.head(8).to_string()}\n\n"
        out += f"Stats:\n{df.describe().to_string()}"
        return out[:5000]
    except Exception as e:
        return f'Error reading CSV: {e}'


def _analyze_excel(filepath: str) -> str:
    try:
        import pandas as pd
        df = pd.read_excel(filepath)
        out = f"Shape: {df.shape[0]} rows × {df.shape[1]} cols\n"
        out += f"Columns: {', '.join(df.columns.tolist())}\n\n"
        out += f"Preview:\n{df.head(8).to_string()}\n\n"
        out += f"Stats:\n{df.describe().to_string()}"
        return out[:5000]
    except Exception as e:
        return f'Error reading Excel: {e}'


def _read_image_ocr(filepath: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        text = pytesseract.image_to_string(Image.open(filepath))
        return f'[OCR text from image]\n{text.strip()[:3000]}' if text.strip() else '[No text found in image via OCR]'
    except ImportError:
        return '[Image received. Install pytesseract + tesseract binary for OCR.]'
    except Exception as e:
        return f'OCR failed: {e}'


# ── Code sandbox ───────────────────────────────────────────────────────────────

def run_code(code: str, timeout: int = 12) -> dict:
    """Execute Python code in a subprocess sandbox. Returns stdout/stderr."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False, dir='/tmp') as f:
        f.write(code)
        fname = f.name
    try:
        env = {**os.environ, 'MPLBACKEND': 'Agg', 'PYTHONDONTWRITEBYTECODE': '1'}
        r = subprocess.run(
            [sys.executable, fname],
            capture_output=True, text=True, timeout=timeout, env=env, cwd='/tmp'
        )
        return {'stdout': r.stdout[:3000], 'stderr': r.stderr[:500], 'exit_code': r.returncode}
    except subprocess.TimeoutExpired:
        return {'error': f'Timed out after {timeout}s'}
    except Exception as e:
        return {'error': str(e)}
    finally:
        try:
            os.unlink(fname)
        except Exception:
            pass


# ── File / report ops ──────────────────────────────────────────────────────────

def save_report(filename: str, content) -> str:
    safe = re.sub(r'[^\w\-.]', '_', filename)
    path = os.path.join(REPORTS_DIR, safe)
    with open(path, 'w') as f:
        if isinstance(content, (dict, list)):
            json.dump(content, f, indent=2)
        else:
            f.write(str(content))
    return path


def _calc_risk_level(report: dict) -> str:
    """Return Critical / High / Medium / Low based on scan report contents."""
    risks = report.get('risk_summary', [])
    if not risks or risks == ['No critical issues detected']:
        missing = report.get('headers', {}).get('security_headers_missing', [])
        if len(missing) >= 5:
            return 'Medium'
        return 'Low'

    risk_text = ' '.join(risks).lower()
    if 'expired' in risk_text or 'exposed sensitive' in risk_text:
        return 'Critical'
    if 'expires in' in risk_text or 'ssl issue' in risk_text:
        return 'High'
    if 'missing security headers' in risk_text:
        missing = report.get('headers', {}).get('security_headers_missing', [])
        if len(missing) >= 4:
            return 'Medium'
        return 'Low'
    return 'Medium'


def list_reports() -> list:
    files = []
    for f in sorted(Path(REPORTS_DIR).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not f.is_file():
            continue
        size = f.stat().st_size
        entry = {
            'filename': f.name,
            'size': f'{size // 1024} KB' if size > 1024 else f'{size} B',
            'modified': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
            'target': '',
            'risk_level': 'Unknown',
        }
        # Parse JSON to get target + risk level
        if f.suffix == '.json':
            try:
                data = json.loads(f.read_text())
                entry['target'] = data.get('target', f.stem)
                entry['risk_level'] = _calc_risk_level(data)
                ts = data.get('timestamp', '')
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        entry['modified'] = dt.strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        pass
            except Exception:
                pass
        files.append(entry)
    return files


def read_file(path: str) -> str:
    try:
        return Path(os.path.expanduser(path)).read_text(errors='replace')
    except Exception as e:
        return f'Error reading file: {e}'


# ── Intent detection ───────────────────────────────────────────────────────────

_PHONE_RE = re.compile(
    r"\b(look up|lookup|trace|track|search|check|investigate|info (on|about)?|osint|"
    r"who (owns|has|called|is)|whose (number|phone)|find (owner|info)|number belongs to|"
    r"phone number|cell number|mobile number)\b.{0,60}"
    r"(\+?[\d\s\-\.\(\)]{7,20})"
    r"|(\+?[\d\s\-\.\(\)]{7,20}).{0,30}"
    r"\b(phone|number|mobile|cell|caller|who is this)\b",
    re.IGNORECASE,
)

# Matches clear phone number patterns: +country digits, or 7-15 digit strings
# Requires the number to stand alone (not buried in a longer digit sequence like a year or port)
_PHONE_NUMBER_RE = re.compile(
    r'(?<!\d)(\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5})'  # +country format
    r'|(?<!\d)(\b0\d{9,10}\b)'                                                  # 0XXXXXXXXXX (10-11 digits, trunk)
    r'|(?<!\d)(\b[2-9]\d{9}\b)'                                                 # 10-digit starting 2-9 (US-style)
    r'|(?<!\d)(\b\d{7,8}\b(?!\s*(px|pt|em|rem|%|ms|s\b)))',                    # 7-8 digit local numbers
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE,
)

_SEARCH_RE = re.compile(
    r"\b(search (for|about|up)?|look up|what'?s? (the )?(latest|current|new|recent)|"
    r"find( out)?( about)?|news (about|on)|cve|exploit for|vulnerability in|"
    r"tell me about|who is|what is|how does|when did|wikipedia|article about)\b",
    re.IGNORECASE,
)
_GITHUB_RE = re.compile(
    r"\b(github|find (a |any )?tool|search (github|repo)|open.?source|exploit code|"
    r"repo(sitory)? for|security tool|hacking tool|python (tool|script) for)\b",
    re.IGNORECASE,
)
_BROWSER_RE = re.compile(
    r"\b(open (the )?(website|page|url|link|site)|visit|screenshot|browse to|"
    r"go to (http|https|www)|fetch (the )?(page|site|content))\b",
    re.IGNORECASE,
)
_WIKI_RE   = re.compile(r"\b(wikipedia|wiki article|wiki page|explain|who (is|was)|what (is|was))\b", re.IGNORECASE)
_ARXIV_RE  = re.compile(r"\b(research paper|arxiv|latest paper|academic paper|paper on|scientific paper)\b", re.IGNORECASE)
_MATH_INTENT_RE = _MATH_RE

# Shodan / exposed services
_SHODAN_RE = re.compile(r'\b(shodan|exposed services|open services|internet scan|what.s exposed on|what.s running on)\b', re.I)

# CVE lookup
_CVE_RE = re.compile(r'\b(CVE-\d{4}-\d+|cve|vulnerability|exploit|vuln(s)?|security flaw|patch)\b', re.I)

# IP geolocation
_IPGEO_RE = re.compile(r'\b(geolocat|ip locat|where is .* (ip|server|host)|trace ip|ip (info|address|lookup)|locate ip)\b', re.I)

# Hash lookup
_HASH_RE = re.compile(r'\b[a-fA-F0-9]{32,64}\b|\b(hash|malware hash|file hash|check hash|virustotal)\b', re.I)

# Network tools
_NET_RE = re.compile(r'\b(ping|traceroute|tracert|dig|nslookup|dns lookup)\b', re.I)

# Whois
_WHOIS_RE = re.compile(r'\b(whois|domain (info|lookup|owner|registrar)|who owns)\b', re.I)


def detect_tools(text: str) -> list:
    tools = []
    # Email takes priority over everything — catches bare addresses automatically
    if _EMAIL_RE.search(text):
        tools.append('email')
    # Phone lookup
    elif _PHONE_RE.search(text) or _PHONE_NUMBER_RE.search(text):
        tools.append('phone')
    if 'email' not in tools and 'phone' not in tools and _SEARCH_RE.search(text):
        tools.append('search')
    if _GITHUB_RE.search(text):
        tools.append('github')
    if _BROWSER_RE.search(text):
        tools.append('browser')
    if _WIKI_RE.search(text):
        tools.append('wikipedia')
    if _ARXIV_RE.search(text):
        tools.append('arxiv')
    if is_math_question(text):
        tools.append('math')
    if _SHODAN_RE.search(text):
        tools.append('shodan')
    if _CVE_RE.search(text):
        tools.append('cve')
    if _IPGEO_RE.search(text):
        tools.append('ipgeo')
    if _HASH_RE.search(text) and not _EMAIL_RE.search(text):
        tools.append('hash')
    if _NET_RE.search(text):
        tools.append('network')
    if _WHOIS_RE.search(text):
        tools.append('whois')
        
    # Check dynamically loaded plugins
    for name, data in _plugin_registry.items():
        if data['trigger'].search(text):
            tools.append(f"plugin:{name}")
            
    return tools

def execute_plugin(plugin_name: str, user_text: str) -> str:
    """Execute a dynamically loaded plugin by name."""
    if plugin_name in _plugin_registry:
        try:
            return _plugin_registry[plugin_name]['handler'](user_text)
        except Exception as e:
            return f"Plugin {plugin_name} error: {str(e)}"
    return f"Plugin {plugin_name} not found."


def extract_email(text: str) -> str | None:
    m = _EMAIL_RE.search(text)
    return m.group(0).lower() if m else None


def extract_phone_number(text: str) -> str | None:
    """Pull the first phone number out of a string."""
    m = _PHONE_NUMBER_RE.search(text)
    if m:
        return re.sub(r'[\s\-\.]', '', m.group(0))
    return None


# ── Format helpers ─────────────────────────────────────────────────────────────

def format_search_results(results: list) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        if 'error' in r:
            return r['error']
        lines.append(f"{i}. {r.get('title','Untitled')}")
        if r.get('snippet'):
            lines.append(f"   {r['snippet'][:180]}")
        if r.get('url'):
            lines.append(f"   {r['url']}")
    return '\n'.join(lines) or 'No results.'


def format_github_results(results: list) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        if 'error' in r:
            return r['error']
        stars = f" ⭐{r['stars']}" if r.get('stars') is not None else ''
        lang  = f" [{r['language']}]" if r.get('language') else ''
        lines.append(f"{i}. {r.get('name','?')}{stars}{lang}")
        if r.get('description'):
            lines.append(f"   {r['description']}")
        if r.get('url'):
            lines.append(f"   {r['url']}")
    return '\n'.join(lines) or 'No repos found.'


def format_arxiv_results(results: list) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        if 'error' in r:
            return r['error']
        authors = ', '.join(r.get('authors', []))
        lines.append(f"{i}. {r.get('title','?')} ({r.get('published','')})")
        if authors:
            lines.append(f"   Authors: {authors}")
        if r.get('summary'):
            lines.append(f"   {r['summary']}")
        if r.get('url'):
            lines.append(f"   {r['url']}")
    return '\n'.join(lines) or 'No papers found.'


# ── Phone OSINT ────────────────────────────────────────────────────────────────

_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

# Country codes to try when parsing a number without a + prefix (most common first)
_GUESS_COUNTRIES = ['TR', 'US', 'GB', 'ET', 'EG', 'NG', 'KE', 'ZA', 'PK', 'IN',
                    'DE', 'FR', 'IT', 'ES', 'AU', 'BR', 'MX', 'RU', 'AE', 'SA']


def _normalize_number(raw_input: str) -> tuple[str, object]:
    """
    Return (e164_string, phonenumbers_obj).
    Handles numbers with/without country code and leading trunk zeros.
    """
    try:
        import phonenumbers
    except ImportError:
        cleaned = re.sub(r'[^\d+]', '', raw_input)
        return ('+' + cleaned.lstrip('+0') if not cleaned.startswith('+') else cleaned), None

    import phonenumbers
    cleaned = re.sub(r'[^\d+]', '', raw_input).strip()

    # 1. Try parsing as-is (works if number has + country code)
    try:
        p = phonenumbers.parse(cleaned, None)
        if phonenumbers.is_valid_number(p):
            return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164), p
    except Exception:
        pass

    # 2. Strip a leading 0 (trunk prefix) and try with country hints
    stripped = cleaned.lstrip('+').lstrip('0')
    for country in _GUESS_COUNTRIES:
        try:
            # phonenumbers can parse national format given a country hint
            p = phonenumbers.parse(cleaned, country)
            if phonenumbers.is_valid_number(p):
                return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164), p
        except Exception:
            pass

    # 3. Best-effort: just prepend + and return
    e164 = ('+' + stripped) if stripped else ('+' + cleaned)
    return e164, None


def phone_lookup(number: str) -> dict:
    """
    Full OSINT lookup: phonenumbers (offline), carrier APIs, sync.me,
    HIBP breach check, DuckDuckGo public mentions, spam databases.
    """
    e164, pn_obj = _normalize_number(number)

    result = {
        'number': e164,
        'valid': False,
        'country': None,
        'country_code': None,
        'carrier': None,
        'line_type': None,
        'location': None,
        # Spam
        'spam_score': None,
        'spam_reports': 0,
        'spam_sources': {},       # {source_name: report_count}
        # Identity
        'owner_name': None,       # from sync.me / caller ID
        # Breach data
        'data_breaches': None,    # list of breach names or None if unchecked
        'breach_checked': False,
        # Public mentions
        'web_mentions': [],       # [{title, url, snippet}]
        # Meta
        'sources': [],
        'not_found': [],
        'error': None,
    }

    # ── 1. phonenumbers — offline, always available ────────────────────────────
    try:
        import phonenumbers
        from phonenumbers import geocoder, carrier as pn_carrier, number_type, PhoneNumberType

        if pn_obj is None:
            try:
                pn_obj = phonenumbers.parse(e164, None)
            except Exception:
                pn_obj = None

        if pn_obj and phonenumbers.is_valid_number(pn_obj):
            result['valid'] = True
            region = phonenumbers.region_code_for_number(pn_obj)
            result['country_code'] = region
            result['country'] = geocoder.description_for_number(pn_obj, 'en') or region
            loc = geocoder.description_for_number(pn_obj, 'en')
            result['location'] = loc if loc and loc != result['country'] else None
            carr = pn_carrier.name_for_number(pn_obj, 'en')
            result['carrier'] = carr if carr else None
            ntype = number_type(pn_obj)
            _type_map = {
                PhoneNumberType.MOBILE: 'Mobile', PhoneNumberType.FIXED_LINE: 'Landline',
                PhoneNumberType.FIXED_LINE_OR_MOBILE: 'Mobile/Landline',
                PhoneNumberType.TOLL_FREE: 'Toll-Free', PhoneNumberType.PREMIUM_RATE: 'Premium Rate',
                PhoneNumberType.VOIP: 'VoIP', PhoneNumberType.PAGER: 'Pager',
                PhoneNumberType.SHARED_COST: 'Shared Cost',
            }
            result['line_type'] = _type_map.get(ntype, 'Unknown')
            result['sources'].append('phonenumbers-offline')
        else:
            result['not_found'].append('validation (unrecognized number format)')
    except ImportError:
        result['not_found'].append('offline-lookup (phonenumbers library not installed)')
    except Exception as e:
        print(f'[phone] phonenumbers error: {e}')

    # ── 2. numverify (free tier, requires key) ────────────────────────────────
    numverify_key = os.environ.get('NUMVERIFY_API_KEY', '').strip()
    if numverify_key:
        try:
            r = requests.get('http://apilayer.net/api/validate',
                params={'access_key': numverify_key, 'number': e164, 'format': 1}, timeout=8)
            d = r.json()
            if d.get('valid'):
                result['valid']        = True
                result['country']      = result['country'] or d.get('country_name')
                result['country_code'] = result['country_code'] or d.get('country_code')
                result['carrier']      = result['carrier'] or d.get('carrier') or None
                result['line_type']    = result['line_type'] or d.get('line_type')
                result['location']     = result['location'] or d.get('location') or None
                result['sources'].append('numverify')
        except Exception as e:
            print(f'[phone] numverify error: {e}')

    # ── 3. AbstractAPI (free tier, requires key) ──────────────────────────────
    abstract_key = os.environ.get('ABSTRACT_PHONE_API_KEY', '').strip()
    if abstract_key and not result['carrier']:
        try:
            r = requests.get('https://phonevalidation.abstractapi.com/v1/',
                params={'api_key': abstract_key, 'phone': e164}, timeout=8)
            d = r.json()
            if d.get('valid'):
                result['valid']        = True
                result['country']      = result['country'] or d.get('country', {}).get('name')
                result['country_code'] = result['country_code'] or d.get('country', {}).get('code')
                result['carrier']      = result['carrier'] or d.get('carrier')
                result['line_type']    = result['line_type'] or d.get('type')
                result['location']     = result['location'] or d.get('location')
                result['sources'].append('abstractapi')
        except Exception as e:
            print(f'[phone] abstractapi error: {e}')

    # ── 4. Prefix map fallback ────────────────────────────────────────────────
    if not result['country']:
        _infer_from_prefix(e164, result)

    # ── 5. sync.me — public caller ID / name ─────────────────────────────────
    _scrape_syncme(e164, result)

    # ── 6. Spam databases ─────────────────────────────────────────────────────
    _check_spam_multi(e164, result)

    # ── 7. HaveIBeenPwned breach check ────────────────────────────────────────
    _check_hibp(e164, result)

    # ── 8. DuckDuckGo public mentions ─────────────────────────────────────────
    _ddg_phone_search(e164, number, result)

    # Track fields we couldn't determine
    for field, label in [('carrier', 'carrier'), ('line_type', 'line type'), ('location', 'location')]:
        if not result[field]:
            result['not_found'].append(label)

    return result


def _scrape_syncme(e164: str, result: dict):
    """Scrape sync.me for public caller name / identity."""
    try:
        # sync.me uses the number in international format without +
        digits = re.sub(r'\D', '', e164)
        url = f'https://sync.me/search/?q=%2B{digits}'
        r = requests.get(url, headers={'User-Agent': _UA, 'Accept-Language': 'en-US,en;q=0.9'}, timeout=8)
        text = r.text
        # Try JSON-LD or og:title for name
        name_m = (re.search(r'"name"\s*:\s*"([^"]{3,60})"', text) or
                  re.search(r'<title>([^<|–-]{3,60}?)[\s|–-]', text))
        if name_m:
            name = name_m.group(1).strip()
            junk = {'sync.me', 'search', 'phone', 'number', 'lookup', 'find', 'who called'}
            if not any(j in name.lower() for j in junk):
                result['owner_name'] = name
                result['sources'].append('sync.me')
    except Exception as e:
        print(f'[phone] sync.me error: {e}')


def _check_spam_multi(e164: str, result: dict):
    """Check multiple free spam databases."""
    digits = re.sub(r'\D', '', e164)
    if len(digits) < 7:
        return

    # shouldianswer.com
    try:
        r = requests.get(f'https://www.shouldianswer.com/phone-number/{digits}',
                         headers={'User-Agent': _UA}, timeout=7)
        text = r.text
        rating_m = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', text)
        count_m  = re.search(r'"ratingCount"\s*:\s*"?(\d+)"?', text)
        if rating_m:
            rating = float(rating_m.group(1))
            score = max(0, round((5 - rating) / 4 * 100))
            count = int(count_m.group(1)) if count_m else 0
            result['spam_sources']['shouldianswer'] = {'score': score, 'reports': count}
            result['sources'].append('shouldianswer')
    except Exception as e:
        print(f'[phone] shouldianswer error: {e}')

    # 800notes.com
    try:
        r = requests.get(f'https://800notes.com/Phone.aspx/{digits}',
                         headers={'User-Agent': _UA}, timeout=7)
        text = r.text
        count_m = re.search(r'(\d+)\s+comment', text, re.I)
        negative_m = re.search(r'(scam|fraud|spam|robocall|telemarket|harass)', text, re.I)
        if count_m:
            count = int(count_m.group(1))
            result['spam_sources']['800notes'] = {
                'reports': count,
                'flagged': bool(negative_m),
            }
            if count > 0:
                result['sources'].append('800notes')
    except Exception as e:
        print(f'[phone] 800notes error: {e}')

    # Aggregate spam score across all sources
    scores = [v['score'] for v in result['spam_sources'].values() if 'score' in v]
    all_reports = sum(v.get('reports', 0) for v in result['spam_sources'].values())
    result['spam_score']   = round(sum(scores) / len(scores)) if scores else None
    result['spam_reports'] = all_reports


def _check_hibp(e164: str, result: dict):
    """Check HaveIBeenPwned for the number in known data breaches."""
    hibp_key = os.environ.get('HIBP_API_KEY', '').strip()
    headers = {'user-agent': 'QUICK-OSINT/2.0', 'hibp-api-key': hibp_key} if hibp_key else {'user-agent': 'QUICK-OSINT/2.0'}
    # Sanitize: try both with and without leading +
    variants = [e164, re.sub(r'\D', '', e164)]
    for variant in variants:
        try:
            r = requests.get(f'https://haveibeenpwned.com/api/v3/breachedaccount/{variant}',
                             headers=headers, timeout=8)
            if r.status_code == 200:
                breaches = r.json()
                result['data_breaches'] = [b.get('Name') for b in breaches]
                result['breach_checked'] = True
                result['sources'].append('haveibeenpwned')
                return
            elif r.status_code == 404:
                result['data_breaches'] = []
                result['breach_checked'] = True
                result['sources'].append('haveibeenpwned')
                return
            elif r.status_code == 401:
                result['not_found'].append('HIBP breach check (set HIBP_API_KEY for breach lookups)')
                return
        except Exception as e:
            print(f'[phone] HIBP error: {e}')
            break


def _ddg_phone_search(e164: str, original: str, result: dict):
    """Search DuckDuckGo for public mentions of the number."""
    try:
        from duckduckgo_search import DDGS
        # Search both E.164 and original format
        queries = list({f'"{e164}"', f'"{original}"'})
        mentions = []
        seen_urls = set()
        with DDGS() as ddgs:
            for q in queries:
                for item in ddgs.text(q, max_results=4):
                    url = item.get('href', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        mentions.append({
                            'title':   item.get('title', ''),
                            'url':     url,
                            'snippet': (item.get('body') or '')[:200],
                        })
                    if len(mentions) >= 5:
                        break
                if len(mentions) >= 5:
                    break
        if mentions:
            result['web_mentions'] = mentions
            result['sources'].append('duckduckgo')
    except ImportError:
        result['not_found'].append('web mentions (duckduckgo-search not installed)')
    except Exception as e:
        print(f'[phone] DDG phone search error: {e}')


_PREFIX_MAP = {
    '+1':   ('United States / Canada', 'US/CA'),
    '+44':  ('United Kingdom', 'GB'),
    '+49':  ('Germany', 'DE'),
    '+33':  ('France', 'FR'),
    '+39':  ('Italy', 'IT'),
    '+34':  ('Spain', 'ES'),
    '+31':  ('Netherlands', 'NL'),
    '+46':  ('Sweden', 'SE'),
    '+47':  ('Norway', 'NO'),
    '+45':  ('Denmark', 'DK'),
    '+41':  ('Switzerland', 'CH'),
    '+43':  ('Austria', 'AT'),
    '+61':  ('Australia', 'AU'),
    '+64':  ('New Zealand', 'NZ'),
    '+81':  ('Japan', 'JP'),
    '+82':  ('South Korea', 'KR'),
    '+86':  ('China', 'CN'),
    '+91':  ('India', 'IN'),
    '+92':  ('Pakistan', 'PK'),
    '+971': ('United Arab Emirates', 'AE'),
    '+966': ('Saudi Arabia', 'SA'),
    '+972': ('Israel', 'IL'),
    '+20':  ('Egypt', 'EG'),
    '+27':  ('South Africa', 'ZA'),
    '+234': ('Nigeria', 'NG'),
    '+254': ('Kenya', 'KE'),
    '+55':  ('Brazil', 'BR'),
    '+52':  ('Mexico', 'MX'),
    '+54':  ('Argentina', 'AR'),
    '+57':  ('Colombia', 'CO'),
    '+56':  ('Chile', 'CL'),
    '+7':   ('Russia / Kazakhstan', 'RU'),
    '+380': ('Ukraine', 'UA'),
    '+48':  ('Poland', 'PL'),
    '+90':  ('Turkey', 'TR'),
    '+62':  ('Indonesia', 'ID'),
    '+63':  ('Philippines', 'PH'),
    '+66':  ('Thailand', 'TH'),
    '+84':  ('Vietnam', 'VN'),
    '+60':  ('Malaysia', 'MY'),
    '+65':  ('Singapore', 'SG'),
    '+251': ('Ethiopia', 'ET'),
}


def _infer_from_prefix(number: str, result: dict):
    """Best-effort country from E.164 prefix."""
    # Try longest prefix first (4 digits → 3 → 2 → 1)
    for length in (4, 3, 2, 1):
        prefix = number[:length + 1]  # +1 for the leading '+'
        if prefix in _PREFIX_MAP:
            country, code = _PREFIX_MAP[prefix]
            result['country']      = country
            result['country_code'] = code
            result['valid']        = True
            result['sources'].append('prefix-inference')
            return


def _check_spam(number: str, result: dict):
    """
    Query shouldianswer.com (free, no key) for community spam reports.
    Uses only the digits after the country code for the URL.
    """
    try:
        # Use digits only, strip leading + and country code prefix for URL
        digits = re.sub(r'\D', '', number)
        # Strip leading zeros that came from normalization
        digits = digits.lstrip('0') if not number.startswith('+') else digits
        if len(digits) < 7:
            return
        url = f'https://www.shouldianswer.com/phone-number/{digits}'
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=8)
        text = r.text
        rating_m = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', text)
        count_m  = re.search(r'"ratingCount"\s*:\s*"?(\d+)"?', text)
        if rating_m:
            rating = float(rating_m.group(1))
            result['spam_score']   = max(0, round((5 - rating) / 4 * 100))
            result['spam_reports'] = int(count_m.group(1)) if count_m else 0
            result['sources'].append('shouldianswer')
    except Exception as e:
        print(f'[phone] spam check error: {e}')


def format_phone_results(data: dict) -> str:
    """Format full OSINT report for QUICK's prompt."""
    if data.get('error'):
        return f"Phone lookup failed: {data['error']}"

    sep = '─' * 48
    lines = [
        f"╔{'═' * 46}╗",
        f"║  PHONE OSINT REPORT: {data['number']:<24}║",
        f"╚{'═' * 46}╝",
        '',
        '── IDENTITY ──────────────────────────────────',
    ]

    lines.append(f"Number valid:  {'✓ Yes' if data['valid'] else '✗ Unconfirmed / Invalid format'}")
    if data.get('owner_name'):
        lines.append(f"Registered to: {data['owner_name']}")
    else:
        lines.append("Registered to: Not found in public caller ID databases")

    lines += ['', '── NUMBER INFO ───────────────────────────────']
    cc = f" ({data['country_code']})" if data.get('country_code') else ''
    lines.append(f"Country:       {data.get('country') or 'Not determined'}{cc}")
    if data.get('location') and data['location'] != data.get('country'):
        lines.append(f"Region:        {data['location']}")
    lines.append(f"Line type:     {data.get('line_type') or 'Not determined'}")
    lines.append(f"Carrier:       {data.get('carrier') or 'Not available (set NUMVERIFY_API_KEY or ABSTRACT_PHONE_API_KEY for carrier data)'}")

    lines += ['', '── SPAM / RISK ───────────────────────────────']
    if data.get('spam_sources'):
        for src, info in data['spam_sources'].items():
            score_str = f"  score {info['score']}/100" if 'score' in info else ''
            flag_str  = '  ⚠ flagged as spam/scam' if info.get('flagged') else ''
            lines.append(f"  {src}: {info.get('reports', 0)} reports{score_str}{flag_str}")
        risk_label = 'HIGH RISK ⚠' if (data['spam_score'] or 0) >= 70 else ('MODERATE ⚠' if (data['spam_score'] or 0) >= 30 else 'Low / Clean')
        lines.append(f"Overall risk:  {risk_label}  ({data['spam_reports']} total community reports)")
    else:
        lines.append("No spam reports found in checked databases.")

    lines += ['', '── DATA BREACH CHECK ─────────────────────────']
    if not data.get('breach_checked'):
        lines.append("Not checked (set HIBP_API_KEY to enable breach lookups)")
    elif data.get('data_breaches'):
        lines.append(f"⚠ FOUND IN {len(data['data_breaches'])} BREACH(ES): {', '.join(data['data_breaches'])}")
    else:
        lines.append("✓ Not found in any known data breaches")

    lines += ['', '── PUBLIC WEB MENTIONS ───────────────────────']
    if data.get('web_mentions'):
        for m in data['web_mentions'][:5]:
            lines.append(f"• {m['title']}")
            if m.get('snippet'):
                lines.append(f"  {m['snippet'][:160]}")
            lines.append(f"  {m['url']}")
    else:
        lines.append("No public web mentions found.")

    lines += ['', '── SOURCES USED ──────────────────────────────']
    lines.append(', '.join(data['sources']) if data['sources'] else 'None — number could not be validated')

    if data.get('not_found'):
        lines += ['', f"Could not determine: {', '.join(data['not_found'])}"]

    return '\n'.join(lines)


# ── Email OSINT ─────────────────────────────────────────────────────────────────

_DISPOSABLE_DOMAINS = {
    'mailinator.com', 'guerrillamail.com', 'tempmail.com', 'throwam.com',
    'yopmail.com', 'sharklasers.com', 'guerrillamailblock.com', 'grr.la',
    'guerrillamail.info', 'guerrillamail.biz', 'guerrillamail.de',
    'guerrillamail.net', 'guerrillamail.org', 'spam4.me', 'trashmail.com',
    'trashmail.me', 'trashmail.net', 'dispostable.com', '10minutemail.com',
    'getairmail.com', 'fakeinbox.com', 'maildrop.cc', 'mintemail.com',
    'spamgourmet.com', 'discard.email', 'mailnull.com', 'spamspot.com',
}


def _dns_query(name: str, qtype: str) -> list[str]:
    """DNS lookup via Cloudflare DoH — no library needed."""
    try:
        r = requests.get(
            'https://cloudflare-dns.com/dns-query',
            params={'name': name, 'type': qtype},
            headers={'Accept': 'application/dns-json'},
            timeout=6,
        )
        data = r.json()
        return [a.get('data', '') for a in data.get('Answer', [])]
    except Exception:
        return []


def email_lookup(email: str) -> dict:
    """Full OSINT on an email address: validation, breaches, social, domain, web."""
    email = email.lower().strip()
    local, _, domain = email.partition('@')

    result = {
        'email':          email,
        'local':          local,
        'domain':         domain,
        # Validity
        'format_valid':   bool(_EMAIL_RE.fullmatch(email)),
        'disposable':     domain in _DISPOSABLE_DOMAINS,
        'mx_records':     [],
        'spf':            None,
        'dmarc':          None,
        'deliverable':    None,       # True/False/None
        # Domain info
        'domain_registrar':  None,
        'domain_registered': None,
        'domain_expires':    None,
        'domain_country':    None,
        # Identity / social
        'gravatar_name':  None,
        'gravatar_url':   None,
        'social_accounts': {},        # {platform: url_or_True}
        # Breach data
        'breaches':       None,       # list or None if unchecked
        'breach_checked': False,
        'pastes':         None,
        # Web mentions
        'web_mentions':   [],
        # Meta
        'sources':        [],
        'not_found':      [],
    }

    if not result['format_valid']:
        result['not_found'].append('all (invalid email format)')
        return result

    # Run all checks
    _check_email_dns(domain, result)
    _check_domain_rdap(domain, result)
    _check_gravatar(email, result)
    _find_social_accounts(local, result)
    _check_email_hibp(email, result)
    _check_email_breach_free(email, result)
    _ddg_email_search(email, result)

    return result


def _check_email_dns(domain: str, result: dict):
    """Check MX, SPF, DMARC records to determine if email can receive mail."""
    mx = _dns_query(domain, 'MX')
    # Strip priority numbers from MX records
    result['mx_records'] = [re.sub(r'^\d+\s+', '', m).rstrip('.') for m in mx if m]
    if result['mx_records']:
        result['deliverable'] = True
        result['sources'].append('dns-mx')
    else:
        result['deliverable'] = False
        result['not_found'].append('MX records (domain may not accept email)')

    # SPF
    txt = _dns_query(domain, 'TXT')
    spf = next((t for t in txt if 'v=spf1' in t.lower()), None)
    result['spf'] = spf.strip('"') if spf else None

    # DMARC
    dmarc = _dns_query(f'_dmarc.{domain}', 'TXT')
    result['dmarc'] = dmarc[0].strip('"') if dmarc else None


def _check_domain_rdap(domain: str, result: dict):
    """Fetch registrar / registration info via RDAP."""
    try:
        r = requests.get(f'https://rdap.org/domain/{domain}',
                         headers={'User-Agent': _UA}, timeout=8)
        if r.status_code != 200:
            return
        d = r.json()
        # Registrar
        for entity in d.get('entities', []):
            roles = entity.get('roles', [])
            if 'registrar' in roles:
                vcard = entity.get('vcardArray', [])
                if isinstance(vcard, list) and len(vcard) > 1:
                    for field in vcard[1]:
                        if field[0] == 'fn':
                            result['domain_registrar'] = field[3]
                            break
        # Dates
        for event in d.get('events', []):
            action = event.get('eventAction', '')
            date   = event.get('eventDate', '')[:10]
            if action == 'registration':
                result['domain_registered'] = date
            elif action == 'expiration':
                result['domain_expires'] = date
        # Country
        if d.get('handle'):
            for entity in d.get('entities', []):
                for addr in entity.get('vcardArray', [[], []])[1]:
                    if addr[0] == 'adr':
                        country = (addr[3] or {}).get('country-name') or (
                            addr[3][-1] if isinstance(addr[3], list) and addr[3] else None)
                        if country:
                            result['domain_country'] = country
                            break
        if result['domain_registrar'] or result['domain_registered']:
            result['sources'].append('rdap')
    except Exception as e:
        print(f'[email] RDAP error: {e}')


def _check_gravatar(email: str, result: dict):
    """Look up Gravatar profile using MD5 of email."""
    import hashlib
    h = hashlib.md5(email.lower().strip().encode()).hexdigest()
    try:
        r = requests.get(f'https://en.gravatar.com/{h}.json',
                         headers={'User-Agent': _UA}, timeout=6)
        if r.status_code == 200:
            entry = r.json().get('entry', [{}])[0]
            result['gravatar_name'] = entry.get('displayName') or entry.get('name', {}).get('formatted')
            urls = entry.get('urls', [])
            result['gravatar_url'] = urls[0].get('value') if urls else f'https://gravatar.com/{h}'
            # Pull social links from profile
            for acc in entry.get('accounts', []):
                platform = acc.get('shortname', '').lower()
                url = acc.get('url', '')
                if platform and url:
                    result['social_accounts'][platform] = url
            result['sources'].append('gravatar')
    except Exception as e:
        print(f'[email] gravatar error: {e}')


def _find_social_accounts(username: str, result: dict):
    """Check public APIs for username existence on major platforms."""
    # Clean username — strip dots/plus aliases common in emails
    uname = re.sub(r'[.+].*', '', username)  # strip sub-addressing and dots
    if len(uname) < 2:
        return

    checks = [
        ('github',    f'https://api.github.com/users/{uname}',                         None),
        ('reddit',    f'https://www.reddit.com/user/{uname}/about.json',               {'User-Agent': 'QUICK-OSINT/2.0'}),
        ('hackernews',f'https://hacker-news.firebaseio.com/v0/user/{uname}.json',       None),
        ('gitlab',    f'https://gitlab.com/api/v4/users?username={uname}',             None),
        ('dev.to',    f'https://dev.to/api/users/by_username?url={uname}',             None),
    ]

    _profile_urls = {
        'github':     lambda u, d: d.get('html_url') or f'https://github.com/{u}',
        'reddit':     lambda u, d: f'https://reddit.com/user/{u}',
        'hackernews': lambda u, d: f'https://news.ycombinator.com/user?id={u}',
        'gitlab':     lambda u, d: d[0].get('web_url') if isinstance(d, list) and d else f'https://gitlab.com/{u}',
        'dev.to':     lambda u, d: f'https://dev.to/{u}',
    }

    for platform, url, extra_headers in checks:
        if platform in result['social_accounts']:
            continue
        try:
            headers = {'User-Agent': _UA}
            if extra_headers:
                headers.update(extra_headers)
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code != 200:
                continue
            d = r.json()
            # Confirm real user exists (not null/empty)
            has_user = (
                (isinstance(d, dict) and (d.get('login') or d.get('name') or d.get('id') or d.get('username'))) or
                (isinstance(d, list) and d and d[0].get('id'))
            )
            if has_user:
                result['social_accounts'][platform] = _profile_urls[platform](uname, d)
        except Exception as e:
            print(f'[email] social check {platform} error: {e}')

    if result['social_accounts'] and 'gravatar' not in result['sources']:
        result['sources'].append('social-check')


def _check_email_hibp(email: str, result: dict):
    """Check HaveIBeenPwned for breaches and pastes."""
    hibp_key = os.environ.get('HIBP_API_KEY', '').strip()
    if not hibp_key:
        result['not_found'].append('HIBP breach check (set HIBP_API_KEY env var — free at haveibeenpwned.com)')
        return
    headers = {'hibp-api-key': hibp_key, 'user-agent': 'QUICK-OSINT/2.0'}
    # Breaches
    try:
        r = requests.get(f'https://haveibeenpwned.com/api/v3/breachedaccount/{email}',
                         headers=headers, timeout=8)
        if r.status_code == 200:
            result['breaches'] = [
                {'name': b.get('Name'), 'date': b.get('BreachDate'), 'pwn_count': b.get('PwnCount')}
                for b in r.json()
            ]
            result['breach_checked'] = True
            result['sources'].append('haveibeenpwned-breaches')
        elif r.status_code == 404:
            result['breaches'] = []
            result['breach_checked'] = True
            result['sources'].append('haveibeenpwned-breaches')
    except Exception as e:
        print(f'[email] HIBP breach error: {e}')
    # Pastes
    try:
        r = requests.get(f'https://haveibeenpwned.com/api/v3/pasteaccount/{email}',
                         headers=headers, timeout=8)
        if r.status_code == 200:
            result['pastes'] = len(r.json())
            result['sources'].append('haveibeenpwned-pastes')
        elif r.status_code == 404:
            result['pastes'] = 0
    except Exception as e:
        print(f'[email] HIBP paste error: {e}')


def _check_email_breach_free(email: str, result: dict):
    """Free breach check via leakcheck.io public endpoint (10 free/day, no key)."""
    if result['breach_checked']:
        return
    try:
        r = requests.get(f'https://leakcheck.io/api/public?query={email}',
                         headers={'User-Agent': _UA}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            if d.get('success'):
                found = d.get('found', 0)
                sources = d.get('sources', [])
                if found:
                    result['breaches'] = [{'name': s.get('name', '?'), 'date': s.get('date', '?')} for s in sources]
                else:
                    result['breaches'] = []
                result['breach_checked'] = True
                result['sources'].append('leakcheck.io')
    except Exception as e:
        print(f'[email] leakcheck error: {e}')


def _ddg_email_search(email: str, result: dict):
    """Search DuckDuckGo for public mentions of the email."""
    try:
        from duckduckgo_search import DDGS
        mentions = []
        with DDGS() as ddgs:
            for item in ddgs.text(f'"{email}"', max_results=5):
                mentions.append({
                    'title':   item.get('title', ''),
                    'url':     item.get('href', ''),
                    'snippet': (item.get('body') or '')[:200],
                })
        if mentions:
            result['web_mentions'] = mentions
            result['sources'].append('duckduckgo')
    except Exception as e:
        print(f'[email] DDG error: {e}')


def format_email_results(data: dict) -> str:
    """Format full email OSINT report for QUICK's prompt."""
    if not data.get('format_valid'):
        return f"Invalid email format: {data['email']}"

    lines = [
        f"╔{'═' * 50}╗",
        f"║  EMAIL OSINT REPORT: {data['email']:<28}║",
        f"╚{'═' * 50}╝",
        '',
        '── VALIDATION ────────────────────────────────────',
    ]

    lines.append(f"Format:        ✓ Valid")
    disp = '⚠ Yes — likely throwaway address' if data['disposable'] else '✓ No'
    lines.append(f"Disposable:    {disp}")
    if data['mx_records']:
        lines.append(f"Mail servers:  ✓ {', '.join(data['mx_records'][:2])}")
        lines.append(f"Deliverable:   ✓ Yes (MX records found)")
    else:
        lines.append(f"Deliverable:   ✗ No MX records — domain may not accept mail")
    if data.get('spf'):
        lines.append(f"SPF:           {data['spf'][:80]}")
    if data.get('dmarc'):
        lines.append(f"DMARC:         {data['dmarc'][:80]}")

    lines += ['', '── DOMAIN INFO ───────────────────────────────────']
    lines.append(f"Domain:        {data['domain']}")
    lines.append(f"Registrar:     {data.get('domain_registrar') or 'Not found'}")
    lines.append(f"Registered:    {data.get('domain_registered') or 'Not found'}")
    lines.append(f"Expires:       {data.get('domain_expires') or 'Not found'}")
    if data.get('domain_country'):
        lines.append(f"Country:       {data['domain_country']}")

    lines += ['', '── IDENTITY / SOCIAL ─────────────────────────────']
    if data.get('gravatar_name'):
        lines.append(f"Gravatar name: {data['gravatar_name']}")
    if data.get('gravatar_url'):
        lines.append(f"Gravatar URL:  {data['gravatar_url']}")
    if data.get('social_accounts'):
        for platform, url in data['social_accounts'].items():
            lines.append(f"  {platform.capitalize():<14} {url}")
    else:
        lines.append(f"No linked accounts found (checked GitHub, Reddit, HN, GitLab, dev.to)")

    lines += ['', '── DATA BREACHES ─────────────────────────────────']
    if not data['breach_checked']:
        lines.append("Not checked — set HIBP_API_KEY for full breach lookup")
        lines.append("Free alternative: leakcheck.io was tried (may be rate-limited)")
    elif data.get('breaches'):
        lines.append(f"⚠ FOUND IN {len(data['breaches'])} BREACH(ES):")
        for b in data['breaches'][:10]:
            date = f" ({b.get('date', '')})" if b.get('date') else ''
            count = f" — {b['pwn_count']:,} accounts" if b.get('pwn_count') else ''
            lines.append(f"  • {b.get('name', '?')}{date}{count}")
        if len(data['breaches']) > 10:
            lines.append(f"  ... and {len(data['breaches']) - 10} more")
    else:
        lines.append("✓ Not found in any known data breaches")
    if data.get('pastes') is not None:
        lines.append(f"Paste sites:   {'⚠ Found in ' + str(data['pastes']) + ' paste(s)' if data['pastes'] else '✓ Not found in paste sites'}")

    lines += ['', '── PUBLIC WEB MENTIONS ───────────────────────────']
    if data.get('web_mentions'):
        for m in data['web_mentions'][:5]:
            lines.append(f"• {m['title']}")
            if m.get('snippet'):
                lines.append(f"  {m['snippet'][:160]}")
            lines.append(f"  {m['url']}")
    else:
        lines.append("No public web mentions found.")

    lines += ['', '── SOURCES USED ──────────────────────────────────']
    lines.append(', '.join(data['sources']) if data['sources'] else 'None')

    if data.get('not_found'):
        lines += ['', f"Could not check: {'; '.join(data['not_found'])}"]

    return '\n'.join(lines)


# ── Shodan InternetDB lookup ───────────────────────────────────────────────────

import socket


def shodan_lookup(target: str) -> dict:
    """Query Shodan InternetDB (free, no API key) for exposed services on an IP."""
    try:
        # Resolve hostname to IP if needed
        ip = target.strip()
        try:
            socket.inet_aton(ip)
        except OSError:
            # Not a valid IP — treat as hostname and resolve
            try:
                infos = socket.getaddrinfo(ip, None, socket.AF_INET)
                if infos:
                    ip = infos[0][4][0]
                else:
                    return {'error': f'Could not resolve hostname: {target}'}
            except socket.gaierror as e:
                return {'error': f'DNS resolution failed for {target}: {e}'}

        r = requests.get(f'https://internetdb.shodan.io/{ip}', timeout=10)
        if r.status_code == 404:
            return {
                'ip': ip,
                'ports': [],
                'hostnames': [],
                'cpes': [],
                'vulns': [],
                'tags': [],
                'note': 'No information available for this IP in Shodan InternetDB.',
            }
        r.raise_for_status()
        data = r.json()
        return {
            'ip': data.get('ip', ip),
            'ports': data.get('ports', []),
            'hostnames': data.get('hostnames', []),
            'cpes': data.get('cpes', []),
            'vulns': data.get('vulns', []),
            'tags': data.get('tags', []),
        }
    except requests.RequestException as e:
        return {'error': f'Shodan lookup failed: {e}'}
    except Exception as e:
        return {'error': f'Shodan lookup error: {e}'}


# ── CVE / NVD lookup ───────────────────────────────────────────────────────────

_CVE_ID_RE = re.compile(r'CVE-\d{4}-\d+', re.I)


def cve_lookup(query: str) -> list:
    """Query NIST NVD for CVE information. Accepts a CVE ID or keyword search."""
    try:
        query = query.strip()
        cve_match = _CVE_ID_RE.search(query)

        if cve_match:
            cve_id = cve_match.group(0).upper()
            url = 'https://services.nvd.nist.gov/rest/json/cves/2.0'
            params = {'cveId': cve_id}
        else:
            url = 'https://services.nvd.nist.gov/rest/json/cves/2.0'
            params = {'keywordSearch': query, 'resultsPerPage': 5}

        r = requests.get(url, params=params, timeout=12)
        r.raise_for_status()
        data = r.json()

        results = []
        for item in data.get('vulnerabilities', []):
            cve = item.get('cve', {})
            cve_id = cve.get('id', 'Unknown')

            # Description
            descriptions = cve.get('descriptions', [])
            desc = next((d['value'] for d in descriptions if d.get('lang') == 'en'), '')
            if not desc and descriptions:
                desc = descriptions[0].get('value', '')

            # Severity / score — try CVSS v3.1 first, then v3.0, then v2.0
            severity = 'Unknown'
            score = None
            metrics = cve.get('metrics', {})
            for key in ('cvssMetricV31', 'cvssMetricV30', 'cvssMetricV2'):
                metric_list = metrics.get(key, [])
                if metric_list:
                    cvss_data = metric_list[0].get('cvssData', {})
                    score = cvss_data.get('baseScore')
                    severity = cvss_data.get('baseSeverity', 'Unknown')
                    break

            # Published date
            published = cve.get('published', '')[:10]

            # References
            refs = [ref.get('url', '') for ref in cve.get('references', [])[:5]]

            results.append({
                'id': cve_id,
                'description': desc[:500],
                'severity': severity,
                'score': score,
                'published': published,
                'references': refs,
            })

        return results if results else [{'id': query, 'description': 'No CVE data found.', 'severity': 'Unknown', 'score': None, 'published': '', 'references': []}]

    except requests.RequestException as e:
        return [{'error': f'NVD API request failed: {e}'}]
    except Exception as e:
        return [{'error': f'CVE lookup error: {e}'}]


# ── IP geolocation ─────────────────────────────────────────────────────────────

def ip_geolocation(ip: str) -> dict:
    """Get geolocation data for an IP address using ip-api.com (free, no key)."""
    try:
        target = ip.strip()
        # Resolve hostname to IP if needed
        try:
            socket.inet_aton(target)
        except OSError:
            try:
                infos = socket.getaddrinfo(target, None, socket.AF_INET)
                if infos:
                    target = infos[0][4][0]
                else:
                    return {'error': f'Could not resolve hostname: {ip}'}
            except socket.gaierror as e:
                return {'error': f'DNS resolution failed for {ip}: {e}'}

        r = requests.get(
            f'http://ip-api.com/json/{target}',
            params={'fields': 'status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query'},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        if data.get('status') == 'fail':
            return {'error': f"Geolocation failed: {data.get('message', 'unknown error')}"}
        return data

    except requests.RequestException as e:
        return {'error': f'IP geolocation request failed: {e}'}
    except Exception as e:
        return {'error': f'IP geolocation error: {e}'}


# ── Hash lookup (VirusTotal) ───────────────────────────────────────────────────

def hash_lookup(hash_str: str) -> dict:
    """Look up a file hash on VirusTotal (requires VIRUSTOTAL_API_KEY env var)."""
    try:
        hash_str = hash_str.strip().lower()

        # Detect hash type by length
        hash_len = len(hash_str)
        if hash_len == 32:
            hash_type = 'MD5'
        elif hash_len == 40:
            hash_type = 'SHA-1'
        elif hash_len == 64:
            hash_type = 'SHA-256'
        else:
            return {'error': f'Unrecognized hash length ({hash_len}). Expected MD5 (32), SHA-1 (40), or SHA-256 (64).'}

        # Validate hex characters
        if not re.fullmatch(r'[a-f0-9]+', hash_str):
            return {'error': 'Invalid hash — must contain only hexadecimal characters.'}

        vt_key = os.environ.get('VIRUSTOTAL_API_KEY', '').strip()
        if not vt_key:
            return {
                'hash': hash_str,
                'hash_type': hash_type,
                'detected': None,
                'detection_count': None,
                'total_engines': None,
                'scan_results': None,
                'note': 'Set VIRUSTOTAL_API_KEY environment variable to enable hash lookups. '
                        'Get a free API key at https://www.virustotal.com/',
            }

        r = requests.get(
            f'https://www.virustotal.com/api/v3/files/{hash_str}',
            headers={'x-apikey': vt_key},
            timeout=12,
        )

        if r.status_code == 404:
            return {
                'hash': hash_str,
                'hash_type': hash_type,
                'detected': False,
                'detection_count': 0,
                'total_engines': 0,
                'scan_results': 'Hash not found in VirusTotal database.',
            }

        r.raise_for_status()
        data = r.json().get('data', {}).get('attributes', {})
        stats = data.get('last_analysis_stats', {})
        malicious = stats.get('malicious', 0)
        suspicious = stats.get('suspicious', 0)
        total = sum(stats.values()) if stats else 0

        return {
            'hash': hash_str,
            'hash_type': hash_type,
            'detected': (malicious + suspicious) > 0,
            'detection_count': malicious + suspicious,
            'total_engines': total,
            'file_type': data.get('type_description', 'Unknown'),
            'file_name': data.get('meaningful_name', data.get('names', ['Unknown'])[0] if data.get('names') else 'Unknown'),
            'file_size': data.get('size'),
            'scan_results': {
                'malicious': malicious,
                'suspicious': suspicious,
                'undetected': stats.get('undetected', 0),
                'harmless': stats.get('harmless', 0),
            },
        }

    except requests.RequestException as e:
        return {'error': f'VirusTotal request failed: {e}'}
    except Exception as e:
        return {'error': f'Hash lookup error: {e}'}


# ── WHOIS / RDAP domain lookup ─────────────────────────────────────────────────

def whois_lookup(domain: str) -> dict:
    """Query RDAP for domain registration information."""
    try:
        domain = domain.strip().lower()
        # Strip protocol if user passed a URL
        domain = re.sub(r'^https?://', '', domain)
        domain = domain.split('/')[0]  # strip path

        r = requests.get(f'https://rdap.org/domain/{domain}',
                         headers={'User-Agent': _UA}, timeout=10)

        if r.status_code == 404:
            return {'domain': domain, 'error': 'Domain not found in RDAP.'}
        r.raise_for_status()
        d = r.json()

        result = {
            'domain': domain,
            'registrar': None,
            'registered': None,
            'expires': None,
            'updated': None,
            'status': [],
            'nameservers': [],
        }

        # Registrar
        for entity in d.get('entities', []):
            roles = entity.get('roles', [])
            if 'registrar' in roles:
                vcard = entity.get('vcardArray', [])
                if isinstance(vcard, list) and len(vcard) > 1:
                    for field in vcard[1]:
                        if field[0] == 'fn':
                            result['registrar'] = field[3]
                            break

        # Dates
        for event in d.get('events', []):
            action = event.get('eventAction', '')
            date = event.get('eventDate', '')[:10]
            if action == 'registration':
                result['registered'] = date
            elif action == 'expiration':
                result['expires'] = date
            elif action == 'last changed':
                result['updated'] = date

        # Status
        result['status'] = d.get('status', [])

        # Nameservers
        for ns in d.get('nameservers', []):
            ns_name = ns.get('ldhName', '')
            if ns_name:
                result['nameservers'].append(ns_name.lower())

        return result

    except requests.RequestException as e:
        return {'domain': domain, 'error': f'RDAP request failed: {e}'}
    except Exception as e:
        return {'domain': domain if 'domain' in dir() else '', 'error': f'WHOIS lookup error: {e}'}


# ── Network tools (ping, traceroute, dig) ──────────────────────────────────────

def _sanitize_target(target: str) -> str:
    """Sanitize target to prevent command injection — allow only safe chars."""
    target = target.strip()
    if not re.fullmatch(r'[a-zA-Z0-9.\-]+', target):
        raise ValueError(f'Invalid target: "{target}" — only alphanumeric, dots, and hyphens allowed.')
    return target


def analyze_pcap(filepath: str) -> dict:
    """Analyze a PCAP file for top IPs, protocols, and malicious signatures."""
    try:
        from scapy.all import rdpcap, IP, TCP, Raw
    except ImportError:
        return {"error": "scapy is not installed. Run 'pip3 install scapy'."}
        
    try:
        packets = rdpcap(filepath)
    except Exception as e:
        return {"error": f"Failed to read pcap: {e}"}
        
    report = {
        "total_packets": len(packets),
        "top_ips": {},
        "alerts": []
    }
    
    sqli_re = re.compile(r'(?i)(union\s+select|select\s+.*\s+from|or\s+1=1|--\s*$)')
    xss_re = re.compile(r'(?i)(<script>|javascript:|onerror=)')
    
    for pkt in packets:
        if IP in pkt:
            src = pkt[IP].src
            dst = pkt[IP].dst
            report["top_ips"][src] = report["top_ips"].get(src, 0) + 1
            report["top_ips"][dst] = report["top_ips"].get(dst, 0) + 1
            
            if Raw in pkt and TCP in pkt:
                try:
                    payload = pkt[Raw].load.decode('utf-8', errors='ignore')
                    if sqli_re.search(payload):
                        report["alerts"].append(f"[SQLi] Potential injection from {src} to {dst} on port {pkt[TCP].dport}")
                    if xss_re.search(payload):
                        report["alerts"].append(f"[XSS] Potential cross-site scripting from {src} to {dst} on port {pkt[TCP].dport}")
                except Exception:
                    pass
                    
    # Sort and slice top IPs
    report["top_ips"] = dict(sorted(report["top_ips"].items(), key=lambda item: item[1], reverse=True)[:5])
    return report

def network_ping(target: str) -> dict:
    """Run ping -c 4 against a target. Returns packet stats and RTT."""
    try:
        target = _sanitize_target(target)
        result_proc = subprocess.run(
            ['ping', '-c', '4', target],
            capture_output=True, text=True, timeout=15,
        )

        output = result_proc.stdout
        result = {
            'target': target,
            'packets_sent': None,
            'packets_received': None,
            'packet_loss': None,
            'avg_rtt_ms': None,
            'raw_output': output[:2000],
        }

        # Parse packet stats: "4 packets transmitted, 4 packets received, 0.0% packet loss"
        pkt_m = re.search(r'(\d+) packets? transmitted.*?(\d+) (?:packets? )?received.*?([\d.]+)% packet loss', output, re.I)
        if pkt_m:
            result['packets_sent'] = int(pkt_m.group(1))
            result['packets_received'] = int(pkt_m.group(2))
            result['packet_loss'] = f"{pkt_m.group(3)}%"

        # Parse RTT: "round-trip min/avg/max/stddev = 1.234/5.678/9.012/3.456 ms"
        rtt_m = re.search(r'(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+\s*ms', output, re.I)
        if rtt_m:
            result['avg_rtt_ms'] = float(rtt_m.group(1))

        return result

    except ValueError as e:
        return {'error': str(e)}
    except subprocess.TimeoutExpired:
        return {'target': target, 'error': 'Ping timed out after 15 seconds.'}
    except FileNotFoundError:
        return {'target': target, 'error': 'ping command not found on this system.'}
    except Exception as e:
        return {'target': target, 'error': f'Ping failed: {e}'}


def network_traceroute(target: str) -> dict:
    """Run traceroute against a target. Returns hop list and raw output."""
    try:
        target = _sanitize_target(target)
        result_proc = subprocess.run(
            ['traceroute', '-m', '20', '-w', '2', target],
            capture_output=True, text=True, timeout=30,
        )

        output = result_proc.stdout
        hops = []

        for line in output.strip().split('\n'):
            # Skip header line
            hop_m = re.match(r'\s*(\d+)\s+(.*)', line)
            if hop_m:
                hop_num = int(hop_m.group(1))
                hop_data = hop_m.group(2).strip()
                hops.append({'hop': hop_num, 'data': hop_data})

        return {
            'target': target,
            'hops': hops,
            'raw_output': output[:3000],
        }

    except ValueError as e:
        return {'error': str(e)}
    except subprocess.TimeoutExpired:
        return {'target': target, 'error': 'Traceroute timed out after 30 seconds.'}
    except FileNotFoundError:
        return {'target': target, 'error': 'traceroute command not found. Install with: brew install traceroute'}
    except Exception as e:
        return {'target': target, 'error': f'Traceroute failed: {e}'}


def network_dig(target: str, record_type: str = 'A') -> dict:
    """Run dig for DNS records. Returns parsed records and raw output."""
    try:
        target = _sanitize_target(target)
        # Sanitize record type too
        record_type = record_type.strip().upper()
        if not re.fullmatch(r'[A-Z]{1,10}', record_type):
            raise ValueError(f'Invalid record type: "{record_type}"')

        result_proc = subprocess.run(
            ['dig', target, record_type, '+short'],
            capture_output=True, text=True, timeout=10,
        )

        output = result_proc.stdout.strip()
        records = [line.strip() for line in output.split('\n') if line.strip()]

        return {
            'target': target,
            'record_type': record_type,
            'records': records,
            'raw_output': output[:2000],
        }

    except ValueError as e:
        return {'error': str(e)}
    except subprocess.TimeoutExpired:
        return {'target': target, 'error': 'DNS lookup timed out after 10 seconds.'}
    except FileNotFoundError:
        return {'target': target, 'error': 'dig command not found on this system.'}
    except Exception as e:
        return {'target': target, 'error': f'DNS lookup failed: {e}'}


# ── Format helpers for new tools ───────────────────────────────────────────────

def format_shodan_results(data: dict) -> str:
    """Format Shodan InternetDB results with box-drawing style."""
    if data.get('error'):
        return f"Shodan lookup failed: {data['error']}"

    lines = [
        f"╔{'═' * 50}╗",
        f"║  SHODAN INTERNETDB REPORT: {data.get('ip', '?'):<22}║",
        f"╚{'═' * 50}╝",
        '',
        '── TARGET ────────────────────────────────────────────',
        f"IP Address:    {data.get('ip', 'N/A')}",
    ]

    if data.get('note'):
        lines += ['', f"Note: {data['note']}"]
        return '\n'.join(lines)

    lines += ['', '── OPEN PORTS ────────────────────────────────────────']
    if data.get('ports'):
        lines.append(f"Ports ({len(data['ports'])}):  {', '.join(str(p) for p in data['ports'])}")
    else:
        lines.append('No open ports detected.')

    lines += ['', '── HOSTNAMES ─────────────────────────────────────────']
    if data.get('hostnames'):
        for h in data['hostnames']:
            lines.append(f"  • {h}")
    else:
        lines.append('No hostnames associated.')

    lines += ['', '── CPEs (Software/Services) ──────────────────────────']
    if data.get('cpes'):
        for cpe in data['cpes'][:15]:
            lines.append(f"  • {cpe}")
        if len(data['cpes']) > 15:
            lines.append(f"  ... and {len(data['cpes']) - 15} more")
    else:
        lines.append('No CPE identifiers found.')

    lines += ['', '── VULNERABILITIES ───────────────────────────────────']
    if data.get('vulns'):
        lines.append(f"⚠ {len(data['vulns'])} known vulnerabilities:")
        for v in data['vulns'][:20]:
            lines.append(f"  • {v}")
        if len(data['vulns']) > 20:
            lines.append(f"  ... and {len(data['vulns']) - 20} more")
    else:
        lines.append('✓ No known vulnerabilities detected.')

    if data.get('tags'):
        lines += ['', '── TAGS ──────────────────────────────────────────────']
        lines.append(f"Tags: {', '.join(data['tags'])}")

    return '\n'.join(lines)


def format_cve_results(results: list) -> str:
    """Format CVE/NVD lookup results with box-drawing style."""
    if not results:
        return 'No CVE results found.'
    if results[0].get('error'):
        return f"CVE lookup failed: {results[0]['error']}"

    lines = [
        f"╔{'═' * 50}╗",
        f"║  CVE / VULNERABILITY REPORT                      ║",
        f"╚{'═' * 50}╝",
    ]

    for i, cve in enumerate(results, 1):
        lines += [
            '',
            f"── CVE #{i} ───────────────────────────────────────────",
            f"ID:          {cve.get('id', 'Unknown')}",
        ]

        severity = cve.get('severity', 'Unknown')
        score = cve.get('score')
        score_str = f" (Score: {score})" if score is not None else ''
        severity_icon = '🔴' if severity in ('CRITICAL', 'HIGH') else ('🟡' if severity == 'MEDIUM' else '🟢')
        lines.append(f"Severity:    {severity_icon} {severity}{score_str}")

        if cve.get('published'):
            lines.append(f"Published:   {cve['published']}")

        if cve.get('description'):
            lines.append(f"Description: {cve['description'][:400]}")

        if cve.get('references'):
            lines.append('References:')
            for ref in cve['references'][:5]:
                lines.append(f"  • {ref}")

    return '\n'.join(lines)


def format_ip_geo_results(data: dict) -> str:
    """Format IP geolocation results with box-drawing style."""
    if data.get('error'):
        return f"IP Geolocation failed: {data['error']}"

    lines = [
        f"╔{'═' * 50}╗",
        f"║  IP GEOLOCATION REPORT                           ║",
        f"╚{'═' * 50}╝",
        '',
        '── LOCATION ──────────────────────────────────────────',
        f"IP Address:    {data.get('query', 'N/A')}",
        f"Country:       {data.get('country', 'N/A')} ({data.get('countryCode', '')})",
        f"Region:        {data.get('regionName', 'N/A')} ({data.get('region', '')})",
        f"City:          {data.get('city', 'N/A')}",
        f"ZIP:           {data.get('zip', 'N/A')}",
        f"Timezone:      {data.get('timezone', 'N/A')}",
        f"Coordinates:   {data.get('lat', 'N/A')}, {data.get('lon', 'N/A')}",
        '',
        '── NETWORK ───────────────────────────────────────────',
        f"ISP:           {data.get('isp', 'N/A')}",
        f"Organization:  {data.get('org', 'N/A')}",
        f"AS:            {data.get('as', 'N/A')}",
    ]

    return '\n'.join(lines)


def format_network_results(data: dict, tool_name: str) -> str:
    """Format network tool results (ping, traceroute, dig) with box-drawing style."""
    if data.get('error'):
        return f"{tool_name} failed: {data['error']}"

    title = tool_name.upper()
    target = data.get('target', 'N/A')

    padding = max(0, 50 - len(title) - 12)
    lines = [
        f"╔{'═' * 50}╗",
        f"║  {title} REPORT: {target:<{padding}}║",
        f"╚{'═' * 50}╝",
    ]

    if tool_name.lower() == 'ping':
        lines += [
            '',
            '── PING RESULTS ──────────────────────────────────────',
            f"Target:            {target}",
            f"Packets sent:      {data.get('packets_sent', 'N/A')}",
            f"Packets received:  {data.get('packets_received', 'N/A')}",
            f"Packet loss:       {data.get('packet_loss', 'N/A')}",
            f"Avg RTT:           {data.get('avg_rtt_ms', 'N/A')} ms" if data.get('avg_rtt_ms') is not None else f"Avg RTT:           N/A",
        ]

    elif tool_name.lower() == 'traceroute':
        lines += ['', '── TRACEROUTE HOPS ───────────────────────────────────']
        for hop in data.get('hops', []):
            lines.append(f"  {hop.get('hop', '?'):>2}  {hop.get('data', '*')}")
        if not data.get('hops'):
            lines.append('  No hops recorded.')

    elif tool_name.lower() == 'dig':
        record_type = data.get('record_type', 'A')
        lines += [
            '',
            f"── DNS RECORDS ({record_type}) ────────────────────────────────",
        ]
        if data.get('records'):
            for rec in data['records']:
                lines.append(f"  • {rec}")
        else:
            lines.append(f"  No {record_type} records found.")

    return '\n'.join(lines)
