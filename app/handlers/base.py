import tornado


# Dictionary to store active workers
workers = {}


# Content Security Policy. Alpine.js evaluates x-* attribute expressions, which
# requires 'unsafe-eval' in script-src. Style 'unsafe-inline' is needed because
# xterm.js writes inline styles on its terminal cells. Everything else is locked
# down to same-origin (plus the Google Fonts CDN that index.html links to).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def recycle(worker):
    """
    Recycles a worker by removing it from the workers dictionary if its handler is not set.

    Args:
        worker: The worker object to recycle.

    Returns:
        None
    """

    if worker.handler:
        return
    workers.pop(worker.id, None)
    worker.close()


class BaseHandler(tornado.web.RequestHandler):
    """
    BaseHandler - sets the security headers that apply to every response.
    """


    def set_default_headers(self):
        # HSTS only takes effect over HTTPS; harmless on plain HTTP because
        # browsers ignore it. Apache may also set this; duplicate is fine.
        self.set_header('Strict-Transport-Security',
                        'max-age=63072000; includeSubDomains')
        self.set_header('X-Content-Type-Options', 'nosniff')
        self.set_header('X-Frame-Options', 'DENY')
        self.set_header('Referrer-Policy', 'no-referrer')
        self.set_header('Permissions-Policy',
                        'camera=(), microphone=(), geolocation=()')
        self.set_header('Content-Security-Policy', _CSP)


    def post(self):
        self.write('silence is golden.')


    def get(self):
        self.write('silence is golden.')


    def options(self):
        self.set_status(204)
        self.finish()
