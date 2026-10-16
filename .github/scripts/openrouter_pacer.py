#!/usr/bin/env python3
"""Loopback relay: space OpenRouter requests and retry before streaming starts."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


UPSTREAM = 'https://openrouter.ai/api/v1/responses'
INTERVAL = 6
ATTEMPTS = 4
MAX_WAIT = 120


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an API credential to a redirect destination.
        return None


def retry_delay(value, fallback, now=None):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            seconds = (date - (now or datetime.now(timezone.utc))).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return fallback
    return max(fallback, seconds) if math.isfinite(seconds) else fallback


class Pacer:
    def __init__(self, open_request=None, *, clock=time.monotonic, sleep=time.sleep):
        self.open_request = open_request or build_opener(NoRedirect()).open
        self.clock, self.sleep = clock, sleep
        self.next_start = clock()
        self.exhausted = False

    def open(self, body, authorization):
        if self.exhausted or self.next_start - self.clock() > MAX_WAIT:
            raise HTTPError(UPSTREAM, 429, 'OpenRouter quota/cooldown requires a later run',
                            {'Content-Type': 'application/json',
                             'Retry-After': str(max(1, math.ceil(self.next_start - self.clock())))},
                            BytesIO(b'{"error":{"message":"OpenRouter quota/cooldown requires a later run","code":429}}'))
        for attempt in range(ATTEMPTS):
            wait = max(0, self.next_start - self.clock())
            if wait:
                self.sleep(wait)
            self.next_start = self.clock() + INTERVAL
            request = Request(UPSTREAM, data=body, headers={
                'Authorization': authorization,
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream, application/json',
            })
            try:
                return self.open_request(request, timeout=180)
            except HTTPError as error:
                if error.code == 429:
                    # Metadata calls consume no model requests. Do not burn
                    # retries when a daily allowance has already run out.
                    try:
                        request = Request('https://openrouter.ai/api/v1/key',
                                          headers={'Authorization': authorization})
                        with self.open_request(request, timeout=30) as response:
                            quota = json.load(response)['data'].get('free_model_daily_requests')
                        if quota and quota.get('remaining') == 0:
                            self.exhausted = True
                            print('OpenRouter daily free-model allowance exhausted; stopping.', flush=True)
                            raise error
                    except (OSError, ValueError, KeyError):
                        if self.exhausted:
                            raise error
                        print('OpenRouter quota metadata unavailable; using bounded retries.', flush=True)
                if error.code not in (429, 500, 502, 503, 504):
                    raise
                delay = retry_delay(error.headers.get('Retry-After'), INTERVAL * 2 ** attempt)
                self.next_start = max(self.next_start, self.clock() + delay)
                if attempt == ATTEMPTS - 1 or delay > MAX_WAIT:
                    # Preserve a long cooldown for later incoming requests too.
                    raise
                error.close()
                print(f'OpenRouter HTTP {error.code}: retry {attempt + 2}/{ATTEMPTS} in {delay:g}s.', flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Never log request headers, bodies, prompts or credentials.

    def do_GET(self):
        if self.path not in ('/healthz', '/shutdown'):
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok\n')
        if self.path == '/shutdown':
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_POST(self):
        if self.path != '/v1/responses':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32 * 1024 * 1024:
                self.send_error(413)
                return
            body = self.rfile.read(length)
            request = json.loads(body)
            if not isinstance(request, dict) or request.get('model') != 'openrouter/free' or 'models' in request:
                self.send_error(400, 'Only openrouter/free without fallback models is permitted')
                return
        except (ValueError, TypeError):
            self.send_error(400)
            return
        authorization = self.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            self.send_error(401)
            return
        # Keep complete streams serialized; health/shutdown remain responsive.
        with self.server.request_lock:
            self.forward(body, authorization)

    def forward(self, body, authorization):
        try:
            response = self.server.pacer.open(body, authorization)
        except HTTPError as error:
            response = error
        except (OSError, URLError):
            self.send_error(502, 'OpenRouter connection failed')
            return
        with response:
            self.send_response(response.code)
            for name in ('Content-Type', 'Content-Encoding', 'Retry-After',
                         'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset'):
                if name in response.headers:
                    self.send_header(name, response.headers[name])
            self.end_headers()
            try:
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # A started response is never replayed.


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, pacer=None):
        super().__init__(address, Handler)
        self.pacer = pacer or Pacer()
        self.request_lock = threading.Lock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-info', type=Path, required=True)
    args = parser.parse_args()
    with RelayServer(('127.0.0.1', 0)) as server:
        args.server_info.write_text(json.dumps({'port': server.server_port}))
        print('OpenRouter relay ready: 6s request spacing, four attempts maximum.', flush=True)
        server.serve_forever()
