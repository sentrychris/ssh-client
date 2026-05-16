import logging
import os
import time

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


# --- Session lifetime & concurrency caps (set any to 0 to disable) ----------
# Read once at import. The reaper sweep is scheduled by ssh.py at startup.
IDLE_TIMEOUT_S = int(os.environ.get('WSSH_IDLE_TIMEOUT_S', '600'))
MAX_SESSION_S = int(os.environ.get('WSSH_MAX_SESSION_S', '14400'))
MAX_SESSIONS_PER_IP = int(os.environ.get('WSSH_MAX_SESSIONS_PER_IP', '5'))


_audit = logging.getLogger('wssh.audit')


class IPLimiter:
    """Tracks active sessions per client IP. Single-threaded use only
    (Tornado's IOLoop is single-threaded; we never touch this from
    subprocesses)."""

    def __init__(self):
        self._counts = {}

    def has_capacity(self, ip):
        if MAX_SESSIONS_PER_IP <= 0:
            return True
        return self._counts.get(ip, 0) < MAX_SESSIONS_PER_IP

    def acquire(self, ip):
        self._counts[ip] = self._counts.get(ip, 0) + 1

    def release(self, ip):
        n = self._counts.get(ip, 0)
        if n <= 1:
            self._counts.pop(ip, None)
        else:
            self._counts[ip] = n - 1

    def count(self, ip):
        return self._counts.get(ip, 0)


ip_limiter = IPLimiter()


def recycle(worker):
    """
    Recycles a worker by removing it from the workers dictionary if its handler is not set.
    Called by a one-shot 3s timer after the POST, in case the client never
    opens its WebSocket.
    """

    if worker.handler:
        return
    workers.pop(worker.id, None)
    worker.close()


def reaper():
    """
    Periodic sweep: closes sessions that have exceeded the idle or max-age
    cap, logs each expiry to the audit log. Called by a PeriodicCallback
    scheduled in ssh.py.
    """

    now = time.monotonic()
    expired = []
    for wid, w in list(workers.items()):
        last = getattr(w, 'last_activity_at', None)
        born = getattr(w, 'created_at', None)
        if last is None or born is None:
            continue
        if IDLE_TIMEOUT_S > 0 and (now - last) > IDLE_TIMEOUT_S:
            expired.append((wid, w, 'idle'))
        elif MAX_SESSION_S > 0 and (now - born) > MAX_SESSION_S:
            expired.append((wid, w, 'max_age'))

    for wid, w, reason in expired:
        duration = int(now - w.created_at)
        _audit.info('expire ip=%s worker=%s reason=%s duration_s=%d',
                    getattr(w, 'client_ip', '?'), wid, reason, duration)
        workers.pop(wid, None)
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass


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
