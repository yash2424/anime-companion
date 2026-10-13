"""Tiny HTTP helpers (stdlib only) with readable errors from cloud APIs."""
import json
import urllib.error
import urllib.request
import uuid

_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_default = urllib.request.build_opener()


class ApiError(RuntimeError):
    pass


def _opener(url):
    # Loopback traffic must not go through environment HTTP proxies.
    return _direct if url.startswith(('http://127.0.0.1', 'http://localhost')) else _default


def _open(url, body, headers, timeout, method):
    headers = dict(headers or {})
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode('utf-8')
        headers.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, body, headers, method=method)
    try:
        return _opener(url).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')
        try:
            parsed = json.loads(detail)
            err = parsed.get('error', parsed.get('detail', parsed))
            if isinstance(err, dict):
                err = err.get('message') or err.get('status') or json.dumps(err)
            detail = str(err)
        except ValueError:
            pass
        host = urllib.request.urlparse(url).netloc
        hint = ' (check the API key)' if e.code in (401, 403) else ''
        raise ApiError(f'{host} returned {e.code}{hint}: {detail[:400]}') from None
    except urllib.error.URLError as e:
        raise ApiError(f'Could not reach {urllib.request.urlparse(url).netloc}: {e.reason}') from None


def request(url, body=None, headers=None, timeout=120, method=None):
    with _open(url, body, headers, timeout, method) as response:
        return response.read(), response.headers.get('Content-Type', '')


def stream_events(url, body=None, headers=None, timeout=120):
    """POST and yield each JSON `data:` payload of a server-sent event stream (OpenAI/Anthropic streaming)."""
    with _open(url, body, headers, timeout, None) as response:
        for line in response:
            line = line.strip()
            if not line.startswith(b'data:'):
                continue
            data = line[5:].strip()
            if data == b'[DONE]':
                return
            try:
                yield json.loads(data)
            except ValueError:
                continue


def request_json(url, body=None, headers=None, timeout=120, method=None):
    data, _ = request(url, body, headers, timeout, method)
    return json.loads(data)


def multipart(fields, files):
    """fields: {name: str}; files: {name: (filename, bytes, content_type)} → (body, content_type)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (filename, data, ctype) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                     f'Content-Type: {ctype}\r\n\r\n'.encode() + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'
