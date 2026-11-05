import os
import sys

# Tests never touch real keys or local tools.
os.environ.setdefault('PAYPAL_MODE', 'sandbox')
os.environ['ENABLE_QUICK_TOOLS'] = 'false'
os.environ.setdefault('SECRET_KEY', 'test-secret')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _fresh_ai_cache():
    """Each test gets its own AI answers (scam_check caches them for 10 minutes)."""
    from guard import scam_check
    scam_check._ai_cache.clear()
    yield
    scam_check._ai_cache.clear()


@pytest.fixture
def client():
    import server
    server.app.config['TESTING'] = True
    return server.app.test_client()
