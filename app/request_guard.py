"""Bound streamed request bodies before parsers, including missing Content-Length."""
import asyncio
from starlette.responses import JSONResponse


class RequestGuard:
    def __init__(self, app, json_limit=1024 * 1024, upload_limit=9 * 1024 * 1024, read_timeout=15):
        self.app, self.json_limit, self.upload_limit, self.read_timeout = app, json_limit, upload_limit, read_timeout

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        if sum(len(key) + len(value) for key, value in scope.get('headers', [])) > 16384:
            return await JSONResponse({'detail': 'Request headers too large'}, status_code=431)(scope, receive, send)
        limit = self.upload_limit if scope['path'] == '/api/admin/upload-image' else self.json_limit
        if len(scope.get('query_string', b'')) > 8192:
            return await JSONResponse({'detail': 'Request URL too long'}, status_code=414)(scope, receive, send)
        length = headers.get(b'content-length')
        if length is not None and (len(length) > 20 or not length.isdigit() or int(length) > limit):
            return await JSONResponse({'detail': 'Request body too large'}, status_code=413)(scope, receive, send)
        chunks = []; size = 0
        async def read():
            nonlocal size
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect': return False
                chunk = message.get('body', b''); size += len(chunk)
                if size > limit: return False
                chunks.append(chunk)
                if not message.get('more_body'): return True
        try:
            complete = await asyncio.wait_for(read(), self.read_timeout)
        except asyncio.TimeoutError:
            return await JSONResponse({'detail': 'Request timeout'}, status_code=408)(scope, receive, send)
        if not complete:
            return await JSONResponse({'detail': 'Request body too large'}, status_code=413)(scope, receive, send)
        consumed = False
        async def buffered_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()
        return await self.app(scope, buffered_receive, send)
