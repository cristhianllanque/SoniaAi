import threading
import time
from collections import OrderedDict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.responses import JSONResponse

from .config import MAX_BODY_BYTES


class RateLimiter:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def check(self, key, maximum, period):
        now = time.monotonic()
        with self.lock:
            events = self.entries.setdefault(key, deque())
            self.entries.move_to_end(key)
            while events and events[0] <= now - period:
                events.popleft()
            if len(events) >= maximum:
                raise HTTPException(429, 'Demasiadas solicitudes. Intenta de nuevo en un momento.', headers={'Retry-After': str(period)})
            events.append(now)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)


limiter = RateLimiter()


class RequestGuard:
    """Limit bodies before multipart parsing and reject cross-site writes."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        origin = headers.get(b'origin')
        host = headers.get(b'host', b'').decode()
        if origin and (urlsplit(origin.decode()).netloc != host or urlsplit(origin.decode()).scheme != scope['scheme']):
            return await JSONResponse({'detail': 'Origen no permitido.'}, 403)(scope, receive, send)
        if headers.get(b'sec-fetch-site') == b'cross-site':
            return await JSONResponse({'detail': 'Origen no permitido.'}, 403)(scope, receive, send)
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            length = MAX_BODY_BYTES + 1
        if length > MAX_BODY_BYTES:
            return await JSONResponse({'detail': 'El archivo es demasiado grande.'}, 413)(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return await JSONResponse({'detail': 'El archivo es demasiado grande.'}, 413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
