import asyncio
import logging
import os
import os.path
import resource
import secrets
import sys
from logging.handlers import RotatingFileHandler

from tornado.options import define, options, parse_command_line
from app import create_app


# Define base directory
base_dir = os.path.dirname(__file__)


# Define command-line options
define('address', default='0.0.0.0', help='Listen address for the application')
define('port', default=4500, help='Listen port for the application', type=int)


def _env_bool(name, default=False):
    return os.environ.get(name, '').lower() in ('1', 'true', 'yes') if name in os.environ else default


def _harden_process():
    """OS-level hardening that runs before we start serving:
       - disable core dumps so a crash can't write the SSH key to disk
       - skip anything that would need extra capabilities (mlockall etc.)
    """
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def _setup_audit_logger():
    """Audit log records every connect attempt with ip / target / user /
    auth method / status - and never the password or key. Goes to a rotating
    file if WSSH_AUDIT_LOG is set, otherwise stderr (-> journald under
    systemd)."""
    log = logging.getLogger('wssh.audit')
    log.setLevel(logging.INFO)
    log.propagate = False
    if log.handlers:
        return
    fmt = logging.Formatter('%(asctime)s [audit] %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
    path = os.environ.get('WSSH_AUDIT_LOG')
    if path:
        handler = RotatingFileHandler(path, maxBytes=10_000_000, backupCount=10)
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    log.addHandler(handler)


async def run():
    """
    Starts the tornado application server and listens on the specified address and port.
    """

    # Parse command line arguments
    parse_command_line()

    _harden_process()
    _setup_audit_logger()

    # Cookie secret must persist across restarts for XSRF tokens to remain
    # valid; pin it in prod via WSSH_COOKIE_SECRET. Falling back to a fresh
    # random one is fine for dev (it just invalidates open sessions on
    # restart).
    cookie_secret = os.environ.get('WSSH_COOKIE_SECRET') or secrets.token_hex(32)
    if not os.environ.get('WSSH_COOKIE_SECRET'):
        print('warning: WSSH_COOKIE_SECRET not set; using ephemeral secret '
              '(XSRF tokens will not survive restart)', file=sys.stderr)

    app = create_app({
        'template_path': os.path.join(base_dir, 'public'),
        'static_path': os.path.join(base_dir, 'public'),
        'cookie_secret': cookie_secret,
        'xsrf_cookies': True,
        'debug': _env_bool('WSSH_DEBUG', False),
    })

    # xheaders=True so Tornado picks up X-Forwarded-For / X-Real-IP from the
    # Apache reverse proxy - without it, the audit log always says 127.0.0.1.
    app.listen(options.port, options.address, xheaders=True)
    print("Listening on http://{}:{}".format(options.address, options.port))
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(run())
