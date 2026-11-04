"""
Developer tool: make ONE real PayPal *sandbox* payment from the command line,
to prove the PayPal part (guard/paypal.py) works on its own.

It skips QUICK Guard's checks on purpose: it only tests the PayPal connection.
It is not a web route, so nobody can reach it from the website.

Usage (from the project folder, with your venv active):
    python scripts/sandbox_payment_test.py                       # $1.00 to your app's sandbox business account
    python scripts/sandbox_payment_test.py --amount 5.00 --payee sb-xxxx@business.example.com
    python scripts/sandbox_payment_test.py --check-only          # only test keys + create an order

Steps: creates an order → opens PayPal sandbox in your browser → you log in with
your sandbox PERSONAL (buyer) account and approve → PayPal sends you back to a
local page → this script captures the payment and prints the result.
"""
import argparse
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from guard import paypal  # noqa: E402

PORT = 8765
_result = {}
_done = threading.Event()


class _ReturnHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ('/return', '/cancel'):
            _result['path'] = url.path
            _result['token'] = (parse_qs(url.query).get('token') or [''])[0]
            msg = ('Approved! Go back to your terminal.' if url.path == '/return'
                   else 'Cancelled. Go back to your terminal.')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(f'<h2 style="font-family:sans-serif">{msg}</h2>'.encode())
            _done.set()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # keep the terminal quiet
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--amount', default='1.00')
    ap.add_argument('--payee', default='', help='sandbox recipient email (default: your app account)')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()

    paypal.assert_sandbox()
    print('1/4  Getting a sandbox access token...')
    paypal.get_access_token()
    print('     OK (token not shown)')

    print(f'2/4  Creating a ${args.amount} USD order...')
    order = paypal.create_order(
        args.amount, 'USD', args.payee, 'QUICK Guard sandbox test',
        return_url=f'http://localhost:{PORT}/return',
        cancel_url=f'http://localhost:{PORT}/cancel')
    print(f"     Order {order['id']} status={order['status']}")
    if args.check_only:
        print('     --check-only: stopping here (the order will expire unpaid).')
        return

    server = HTTPServer(('127.0.0.1', PORT), _ReturnHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print('3/4  Opening PayPal sandbox in your browser.')
    print('     Log in with your sandbox PERSONAL account and click Pay / Complete Purchase.')
    print(f"     If the browser didn't open, paste this link:\n     {order['approve_url']}")
    webbrowser.open(order['approve_url'])

    if not _done.wait(timeout=600):
        print('Timed out after 10 minutes waiting for approval.')
        return
    server.shutdown()
    if _result.get('path') != '/return' or _result.get('token') != order['id']:
        print('Payment was cancelled in PayPal. Nothing was charged.')
        return

    print('4/4  Capturing the payment...')
    result = paypal.capture_order(order['id'])
    print(f"     DONE: status={result['status']} capture_id={result['capture_id']} "
          f"amount={result['amount']} {result['currency']}")


if __name__ == '__main__':
    try:
        main()
    except paypal.PayPalError as e:
        print(f'PayPal error: {e}' + (f' ({e.issue})' if e.issue else ''))
        sys.exit(1)
