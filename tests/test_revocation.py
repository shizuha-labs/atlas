"""Signed JWT -> real JWKS and ID HTTP authority -> Atlas authentication."""
import json
import os
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

import auth
import token_revocation as revocation


class RevocationTests(unittest.TestCase):
    def setUp(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.responses = []
        self.calls = []
        self.redirects = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != '/keys':
                    owner.redirects.append(self.path)
                    self.send_error(500)
                    return
                key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(owner.key.public_key()))
                self.respond(200, {'keys': [dict(key, kid='test-key')]})
            def do_POST(self):
                owner.calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                status, body = owner.responses.pop(0)
                self.respond(status, body)
            def respond(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                if status == 302:
                    self.send_header('Location', '/must-not-receive-token')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.05), daemon=True)
        self.worker.start()
        root = f'http://127.0.0.1:{self.server.server_port}'
        self.env = patch.dict(os.environ, {'ATLAS_JWT_SECRET': '', 'ATLAS_JWKS_URL': root+'/keys',
            'SHIZUHA_REVOCATION_STATUS_URL': root+'/status', 'SHIZUHA_EXPECTED_ISSUER': 'https://identity.example/id'})
        self.env.start()
        revocation._REVOCATION_CACHE.clear()
        auth._jwks = None

    def tearDown(self):
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        revocation._REVOCATION_CACHE.clear()
        auth._jwks = None

    def token(self, version=3):
        return jwt.encode({'user_id': 3, 'token_type': 'access', 'token_version': version,
                           'organization_memberships': {'1': 'member'},
                           'exp': int(time.time())+60, 'jti': str(uuid.uuid4())},
                          self.key, algorithm='RS256', headers={'kid': 'test-key'})

    def test_active_stale_active_session(self):
        self.responses.extend([(200, {'active': True, 'token_version': 3})]*3)
        self.assertEqual(auth.verify_token(self.token()).user_id, 3)
        with self.assertRaises(jwt.InvalidTokenError):
            auth.verify_token(self.token(2))
        self.assertTrue(auth.verify_token(self.token()).allows(1))
        self.assertEqual(len(self.calls), 3)

    def test_authority_revocation_after_cache_expiry_is_cached_denial(self):
        raw = self.token()
        self.responses.extend([(200, {'active': True}), (200, {'active': False})])
        auth.verify_token(raw)
        revocation._REVOCATION_CACHE[revocation._cache_key(raw)] = (time.monotonic()-1, False)
        for _ in range(2):
            with self.assertRaises(jwt.InvalidTokenError):
                auth.verify_token(raw)
        self.assertEqual(len(self.calls), 2)

    def test_indeterminate_verdicts_deny_uncached_then_recover(self):
        raw = self.token()
        self.responses.extend([(503, {}), (200, []), (200, {'active': 'false'}),
                               (200, {'active': True, 'token_version': True}),
                               (200, {'active': True})])
        for _ in range(4):
            with self.assertRaises(jwt.InvalidTokenError):
                auth.verify_token(raw)
            self.assertFalse(revocation._REVOCATION_CACHE)
        self.assertEqual(auth.verify_token(raw).user_id, 3)

    def test_redirect_does_not_forward_token_and_recovery_is_uncached(self):
        raw = self.token()
        self.responses.extend([(302, {}), (200, {'active': True})])
        with self.assertRaises(jwt.InvalidTokenError):
            auth.verify_token(raw)
        self.assertFalse(self.redirects)
        self.assertFalse(revocation._REVOCATION_CACHE)
        auth.verify_token(raw)

    def test_malformed_authority_configuration_denies_uncached(self):
        raw = self.token()
        with patch.dict(os.environ, {'SHIZUHA_REVOCATION_STATUS_URL': 'not-a-url'}):
            with self.assertRaises(jwt.InvalidTokenError):
                auth.verify_token(raw)
        self.assertFalse(revocation._REVOCATION_CACHE)
        self.responses.append((200, {'active': True}))
        self.assertEqual(auth.verify_token(raw).user_id, 3)

    def test_local_secret_does_not_call_platform_revocation(self):
        key = 'local-secret'
        raw = jwt.encode(
            {'user_id': 1, 'username': 'ada', 'organization_memberships': {'1': 'owner'},
             'exp': int(time.time()) + 60},
            key, algorithm='HS256')
        with patch.dict(os.environ, {
            'ATLAS_JWT_SECRET': key,
            'ATLAS_JWKS_URL': '',
            'SHIZUHA_REVOCATION_STATUS_URL': '',
        }):
            caller = auth.verify_token(raw)
        self.assertEqual(caller.user_id, 1)
        self.assertEqual(caller.username, 'ada')
        self.assertEqual(self.calls, [])

    def test_legacy_hs256_session_also_requires_authority(self):
        import secrets
        key = secrets.token_urlsafe(32)
        raw = jwt.encode({'user_id': 3, 'exp': int(time.time())+60}, key, algorithm='HS256')
        self.responses.append((200, {'active': False}))
        with patch.dict(os.environ, {'ATLAS_JWT_SECRET': key}):
            with self.assertRaises(jwt.InvalidTokenError):
                auth.verify_token(raw)
