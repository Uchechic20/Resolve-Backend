"""Resolve: security headers on every response.

These tell the browser to switch off risky behaviour. Resolve is an API, so the
policy is deliberately strict:

  X-Content-Type-Options: nosniff      never guess a file's type (stops uploads being run as scripts)
  X-Frame-Options: DENY                the app can never be shown inside someone else's page (clickjacking)
  Content-Security-Policy              API answers may not load or run anything at all
  Referrer-Policy: no-referrer         links out of the app do not leak URLs (they can contain ticket ids)
  Permissions-Policy                   camera, microphone, location etc. are off
  Cross-Origin-Opener-Policy           isolates the page from other windows
  Cross-Origin-Resource-Policy         other sites cannot embed our responses
  Cache-Control: no-store              complaints and attachments are never kept in browser or proxy caches
  Strict-Transport-Security            HTTPS only (switched on in production, see HSTS_ENABLED)

A header the route already set is never overwritten, so a route can choose its own
(for example a download that sets its own Content-Disposition keeps it).

The interactive docs (/docs, /redoc) need scripts from a CDN, so they get a slightly
looser Content-Security-Policy. The docs are switched off in production anyway.

Written as a plain ASGI middleware, not BaseHTTPMiddleware, so streaming responses
and file downloads pass through without being buffered in memory.

Two things this cannot do:
  * the `Server: uvicorn` header is added by uvicorn itself; start the server with
    `--no-server-header` to hide it
  * an unhandled crash (HTTP 500) is answered by Starlette's outermost layer, outside
    this middleware, so that rare response will not carry these headers
"""
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "connect-src 'self'; worker-src blob:; child-src blob:; "
    "frame-ancestors 'none'; base-uri 'none'"
)

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Cache-Control": "no-store",
}

DOCS_PATHS = ("/docs", "/redoc")


class SecurityHeadersMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        hsts: bool = False,
        hsts_max_age: int = 31_536_000,
        docs_paths: tuple[str, ...] = DOCS_PATHS,
    ):
        self.app = app
        self.docs_paths = docs_paths
        self.api_headers = {**BASE_HEADERS, "Content-Security-Policy": API_CSP}
        self.docs_headers = {**BASE_HEADERS, "Content-Security-Policy": DOCS_CSP}
        if hsts:
            value = f"max-age={hsts_max_age}; includeSubDomains"
            self.api_headers["Strict-Transport-Security"] = value
            self.docs_headers["Strict-Transport-Security"] = value

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # websockets and lifespan pass straight through
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_docs = any(path == p or path.startswith(p + "/") for p in self.docs_paths)
        wanted = self.docs_headers if is_docs else self.api_headers

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in wanted.items():
                    if name not in headers:  # never override what the route chose
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)