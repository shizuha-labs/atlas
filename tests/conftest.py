"""Existing map authorization tests use an explicit active ID authority."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import token_revocation


@pytest.fixture()
def active_revocation_authority(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            body = json.dumps({'active': True}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.05), daemon=True)
    worker.start()
    monkeypatch.setenv('SHIZUHA_REVOCATION_STATUS_URL', f'http://127.0.0.1:{server.server_port}/status')
    token_revocation._REVOCATION_CACHE.clear()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        token_revocation._REVOCATION_CACHE.clear()
