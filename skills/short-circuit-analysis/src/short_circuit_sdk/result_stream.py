"""Independent CloudPSS object-stream reader (official client module 97091).

Reads production binary WebSockets, not the testing-only SSE endpoint. Raw
remote messages retain their fields: browser receive times, random keys and
IndexedDB IDs cannot be recovered by inventing replacements.
"""
from copy import deepcopy
from dataclasses import dataclass
import io
import math
import os
import re
import struct
import time
from urllib.parse import urlsplit, urlunsplit


class ResultStreamError(RuntimeError):
    """Transport/decode failure; no partial result is reported as success."""


class ResultStreamUnavailable(ResultStreamError):
    """The service does not expose the requested output stream."""


class ResultStreamStopped(ResultStreamError):
    """SDK reception was stopped locally; the cloud task was not aborted."""


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError('Result collection deadline reached')
    return value


def stream_url(stream_id):
    if not isinstance(stream_id, str) or not re.fullmatch(
            r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', stream_id):
        raise ResultStreamError('Invalid job output stream ID')
    base = urlsplit(os.environ.get('CLOUDPSS_API_URL', 'https://cloudpss.net/'))
    if base.scheme not in ('https', 'http') or not base.netloc or base.username or base.password:
        raise ResultStreamError('Invalid CloudPSS API URL')
    return urlunsplit(('wss' if base.scheme == 'https' else 'ws', base.netloc,
                      '/api/streams/id/' + stream_id, '', ''))


def decode_frame(payload):
    """Decode outer UBJSON plus *all* concatenated inner UBJSON messages."""
    import ubjson
    try:
        outer = io.BytesIO(payload)
        envelope = ubjson.load(outer)
        if outer.tell() != len(payload) or not isinstance(envelope, dict):
            raise ValueError
        if not isinstance(envelope.get('id'), str):
            raise ValueError
        timestamp = envelope.get('timestamp')
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            raise ValueError
        raw = envelope['data']
        if not isinstance(raw, (bytes, bytearray, list)):
            raise ValueError
        if isinstance(raw, list) and any(type(n) is not int or not 0 <= n <= 255 for n in raw):
            raise ValueError
        data = bytes(raw)
        source, messages = io.BytesIO(data), []
        while source.tell() < len(data):
            messages.append(ubjson.load(source))
        return {'id': envelope['id'], 'timestamp': timestamp}, messages
    except Exception:
        raise ResultStreamError('Invalid UBJSON result frame') from None


class MessageTemplates:
    """Template declarations/invocations from official modules 42308/25563.

    Evaluate formula and interpolation strings through the installed MiraScript
    runtime rather than Python eval or the old SDK's broken interpolation parser.
    """
    def __init__(self):
        self.templates = {}

    def _expand(self, value, context):
        if isinstance(value, list):
            return [self._expand(v, context) for v in value]
        if isinstance(value, dict):
            return {self._expand(k, context): self._expand(v, context) for k, v in value.items()}
        if not isinstance(value, str) or len(value) <= 1 or value[0] not in '=$':
            return deepcopy(value)
        from mirascript import compile, VmContext
        source = value[1:]
        if value[0] == '=':
            # The official compiler first resolves a whole identifier-like key
            # from global, even for keys such as foo/bar, before parsing it.
            key_like = bool(source) and all(
                c in '-+_#$@\\/.' or ('a' + c).isidentifier() for c in source)
            if key_like and source in context:
                return deepcopy(context[source])
            mode = 'script'
        else:
            mode = 'template'
        try:
            script, _ = compile(source, input_mode=mode)
            if script is None:
                raise ValueError
            return deepcopy(script(VmContext(context)))
        except Exception:
            raise ResultStreamError('Result message template evaluation failed') from None

    def accept(self, value):
        if isinstance(value, dict):
            return [deepcopy(value)]
        if (not isinstance(value, list) or len(value) < 3
                or type(value[0]) not in (int, float) or value[1] != 1
                or not isinstance(value[2], dict)):
            raise ResultStreamError('Invalid result message/template')
        key = value[0]
        if len(value) > 3:
            self.templates[key] = deepcopy(value)
            return []
        template = self.templates.get(key)
        if template is None:
            # Do not silently drop plot data when its declaration was lost.
            raise ResultStreamError('Result message template declaration is missing')
        expanded = self._expand(template[3:], {**template[2], **value[2]})
        if any(not isinstance(item, dict) for item in expanded):
            raise ResultStreamError('Result template must produce message objects')
        return expanded


@dataclass
class StreamSnapshot:
    messages: list
    envelopes: list
    complete: bool
    termination: object = None
    received_at: object = None


def read_stream(stream_id, *, block, deadline, kind=None, keys=None,
                on_open=None, on_message=None, stop_event=None, connect_timeout=None):
    """Collect a complete stream or a nonblocking snapshot after 700ms quiet.

    A quiet stream is never cached as complete. Only normal server close
    (1000 and empty reason) establishes stream completeness. Network errors,
    abnormal close and deadlines propagate, without retrying or fabricating []
    on a missing stream. All message kinds are retained for later SDK reads.
    """
    import websocket
    url = stream_url(stream_id)
    token = os.environ.get('CLOUDPSS_TOKEN', '').strip()
    if not token:
        raise ResultStreamError('CLOUDPSS_TOKEN is required')
    ws = None
    messages, envelopes, received_at = [], [], []
    from datetime import datetime, timezone
    templates, termination = MessageTemplates(), None
    quiet_since = time.monotonic()
    try:
        if stop_event is not None and stop_event.is_set():
            raise ResultStreamStopped('SDK result receiver stopped')
        wait = remaining(deadline)
        if connect_timeout is not None:
            wait = min(wait, connect_timeout)
        ws = websocket.create_connection(url, timeout=wait,
            header={'Authorization': 'Bearer ' + token})
        if on_open is not None:
            on_open(ws)
        quiet_since = time.monotonic()
        while True:
            if stop_event is not None and stop_event.is_set():
                raise ResultStreamStopped('SDK result receiver stopped')
            wait = remaining(deadline)
            if stop_event is not None:
                wait = min(wait, .25)
            if not block:
                quiet_remaining = .7 - (time.monotonic() - quiet_since)
                if quiet_remaining <= 0:
                    return StreamSnapshot(messages, envelopes, False, termination, received_at)
                wait = min(wait, quiet_remaining)
            ws.settimeout(wait)
            try:
                opcode, payload = ws.recv_data(control_frame=True)
            except websocket.WebSocketTimeoutException:
                remaining(deadline)
                if not block and time.monotonic() - quiet_since >= .7:
                    return StreamSnapshot(messages, envelopes, False, termination, received_at)
                continue
            if opcode == websocket.ABNF.OPCODE_CLOSE:
                if len(payload) < 2:
                    raise ResultStreamError('Result stream closed without completion status')
                code = struct.unpack('!H', payload[:2])[0]
                reason = payload[2:].decode('utf-8')
                if reason.startswith('CMS_NO_STREAM_ID:'):
                    raise ResultStreamUnavailable('Result output stream is unavailable (CMS_NO_STREAM_ID)')
                if code != 1000 or reason:
                    raise ResultStreamError('Result stream did not complete normally (close code %s)' % code)
                return StreamSnapshot(messages, envelopes, True, termination, received_at)
            if opcode != websocket.ABNF.OPCODE_BINARY:
                continue  # Official client ignores string/control frames.
            envelope, values = decode_frame(payload)
            envelopes.append(envelope)
            for value in values:
                for message in templates.accept(value):
                    if termination is not None:
                        continue  # Official receiver stops storing after terminate.
                    messages.append(message)
                    stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
                    received_at.append(stamp)
                    if on_message is not None:
                        on_message(deepcopy(message), stamp)
                    if message.get('type') == kind and (keys is None or message.get('key') in keys):
                        quiet_since = time.monotonic()
                    if message.get('type') == 'terminate':
                        termination = deepcopy(message.get('data'))
    except (ResultStreamError, TimeoutError):
        raise
    except websocket.WebSocketTimeoutException:
        raise TimeoutError('Result stream connection deadline reached') from None
    except websocket.WebSocketBadStatusException as exc:
        if exc.status_code == 404:
            raise ResultStreamUnavailable('Result output stream is unavailable (HTTP 404)') from None
        raise ResultStreamError('Result stream handshake failed (HTTP %s)' % exc.status_code) from None
    except Exception:
        # Some libraries include request headers in exception text.
        raise ResultStreamError('Result stream transport failed') from None
    finally:
        if ws is not None:
            try:
                ws.close(timeout=0)
            except Exception:
                pass  # Cleanup must not replace the actual transport failure.


def read_job_results(job_id, *, block, deadline, kind=None, keys=None, info=None):
    """Get metadata and output directly from CloudPSS under one deadline."""
    from cloudpss.utils import graphql_request
    from .job_results import fetch_job_record_info
    def request(query, variables, **_):
        return graphql_request(query, variables, timeout=remaining(deadline))
    if info is None:
        info = fetch_job_record_info(job_id, requester=request)
    elif info.get("id") != job_id:
        raise ValueError("Task metadata does not match the requested ID")
    snapshot = read_stream(info.get('output'), block=block, deadline=deadline, kind=kind, keys=keys)
    terminal = {'COMPLETED', 'FAILED', 'TIMED_OUT', 'CANCELED', 'ABORTED', 'KILLED'}
    # A transport close alone must not be promoted to task completion. When
    # no terminal message was emitted, verify server task state independently.
    while block and snapshot.termination is None and info.get('status') not in terminal:
        time.sleep(min(.1, remaining(deadline)))
        info = fetch_job_record_info(job_id, requester=request)
    remaining(deadline)
    return info, snapshot
