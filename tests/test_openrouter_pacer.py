"""Exercise request spacing, retry decisions and stream forwarding without API calls."""
from email.message import Message
import http.client
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import threading
from urllib.error import HTTPError

import pytest


PATH = Path(__file__).resolve().parents[1] / '.github/scripts/openrouter_pacer.py'


def module():
    spec = importlib.util.spec_from_file_location('openrouter_pacer', PATH)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def error(status, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    return HTTPError('https://openrouter.ai/api/v1/responses', status,
                     'upstream error', headers, BytesIO(b'{"error":"limited"}'))


def pacer(outcomes, remaining=22):
    m = module()
    clock = Clock()
    starts = []
    requests = []

    def open_request(request, timeout):
        requests.append(request)
        if request.full_url.endswith('/key'):
            return BytesIO(json.dumps({'data': {'free_model_daily_requests':
                                               {'remaining': remaining}}}).encode())
        starts.append(clock.now)
        result = outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    return m.Pacer(open_request, clock=lambda: clock.now, sleep=clock.sleep), clock, starts, requests


def test_spaces_successive_requests_six_seconds_apart():
    relay, clock, starts, _ = pacer([BytesIO(b'first'), BytesIO(b'second')])
    assert relay.open(b'{}', 'Bearer private-key').read() == b'first'
    assert relay.open(b'{}', 'Bearer private-key').read() == b'second'
    assert starts == [0, 6]
    assert clock.sleeps == [6]


def test_honors_retry_after_then_exponential_backoff():
    relay, clock, starts, _ = pacer([error(429, '15'), error(503), BytesIO(b'ok')])
    assert relay.open(b'{}', 'Bearer private-key').read() == b'ok'
    assert starts == [0, 15, 27]
    assert clock.sleeps == [15, 12]


def test_daily_exhaustion_does_not_retry_or_forward_later_requests():
    relay, clock, starts, _ = pacer([error(429)], remaining=0)
    with pytest.raises(HTTPError) as failure:
        relay.open(b'{}', 'Bearer private-key')
    assert failure.value.code == 429
    with pytest.raises(HTTPError):
        relay.open(b'{}', 'Bearer private-key')
    assert starts == [0]
    assert clock.sleeps == []


def test_stops_after_four_attempts_and_does_not_retry_auth_errors():
    relay, _, starts, _ = pacer([error(503) for _ in range(4)])
    with pytest.raises(HTTPError):
        relay.open(b'{}', 'Bearer private-key')
    assert starts == [0, 6, 18, 42]
    relay, _, starts, _ = pacer([error(401)])
    with pytest.raises(HTTPError):
        relay.open(b'{}', 'Bearer private-key')
    assert starts == [0]


def test_long_retry_after_is_returned_without_retrying_early():
    relay, clock, starts, _ = pacer([error(429, '3600')])
    with pytest.raises(HTTPError):
        relay.open(b'{}', 'Bearer private-key')
    assert starts == [0]
    assert clock.sleeps == []
    with pytest.raises(HTTPError):
        relay.open(b'{}', 'Bearer private-key')
    assert starts == [0]


def test_retry_after_http_date():
    m = module()
    from datetime import datetime, timezone
    assert m.retry_delay('Thu, 15 Oct 2026 00:00:20 GMT', 6,
                         datetime(2026, 10, 15, tzinfo=timezone.utc)) == 20
    assert m.retry_delay('invalid', 12) == 12


def test_forwards_only_to_fixed_endpoint_with_auth_header():
    relay, _, _, requests = pacer([BytesIO(b'ok')])
    relay.open(b'{"model":"openrouter/free"}', 'Bearer private-key')
    assert requests[0].full_url == 'https://openrouter.ai/api/v1/responses'
    assert requests[0].get_header('Authorization') == 'Bearer private-key'
    assert requests[0].data == b'{"model":"openrouter/free"}'


def test_http_relay_streams_before_completion_and_rejects_paid_models(capsys):
    m = module()
    release = threading.Event()
    forwarded = []
    prefix = b'data: {"type":"response.created"}\n\n'

    class StreamingResponse:
        code = 200
        headers = {'Content-Type': 'text/event-stream'}

        def __init__(self):
            self.first = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read1(self, size):
            if self.first:
                self.first = False
                return prefix
            assert release.wait(3)
            return b''

    class Upstream:
        def open(self, body, authorization):
            forwarded.append((body, authorization))
            return StreamingResponse()

    try:
        server = m.RelayServer(('127.0.0.1', 0), Upstream())
    except PermissionError:
        pytest.skip('loopback sockets unavailable inside this sandbox; exercised on the CI host')
    with server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            conn.request('POST', '/v1/responses', json.dumps({'model': 'paid/model'}),
                         {'Authorization': 'Bearer private-key'})
            response = conn.getresponse()
            assert response.status == 400
            response.read()
            assert forwarded == []
            conn.close()
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            conn.request('POST', '/v1/responses', json.dumps({'model': 'openrouter/free'}),
                         {'Authorization': 'Bearer private-key'})
            response = conn.getresponse()
            assert response.status == 200
            assert response.getheader('Content-Type') == 'text/event-stream'
            assert response.read(len(prefix)) == prefix
            assert forwarded[0][1] == 'Bearer private-key'
            # Control requests must work while a model stream is still open.
            health = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            health.request('GET', '/healthz')
            assert health.getresponse().read() == b'ok\n'
            health.close()
            release.set()
            response.read()
            conn.close()
        finally:
            release.set()
            server.shutdown()
            worker.join(timeout=3)
    assert 'private-key' not in capsys.readouterr().out
