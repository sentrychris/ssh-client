import json
import logging
import os
import socket as socket_mod
import sys
import uuid

import tornado
from tornado.process import Subprocess

from ..worker import Worker
from .base import BaseHandler, workers, recycle


audit = logging.getLogger('wssh.audit')


class HttpHandler(BaseHandler):
    """Spawns a per-session SSH subprocess and hands a SessionProxy
    (``app.worker.Worker``) to the WebSocket handler."""


    async def _spawn_session(self, body_bytes):
        """Spawn ``app.session_worker``, pipe the raw POST body to its
        stdin, read back the status line, and connect to its abstract
        Unix socket. Returns (worker_id, sock, subprocess) on success.
        Raises ValueError with a user-facing message on failure."""

        worker_id = uuid.uuid4().hex
        abstract_name = 'wssh-' + worker_id
        addr = b'\0' + abstract_name.encode('ascii')

        proc = Subprocess(
            [sys.executable, '-m', 'app.session_worker', abstract_name],
            stdin=Subprocess.STREAM,
            stdout=Subprocess.STREAM,
            stderr=None,  # let it inherit so worker tracebacks reach journald
        )

        try:
            await proc.stdin.write(body_bytes)
        finally:
            proc.stdin.close()

        try:
            status_line = await proc.stdout.read_until(b'\n')
        except tornado.iostream.StreamClosedError:
            raise ValueError('Session worker exited before reporting status.')

        try:
            status = json.loads(status_line)
        except (ValueError, TypeError):
            raise ValueError('Session worker returned invalid status.')

        if status.get('status') != 'ok':
            raise ValueError(status.get('reason') or 'Session worker failed.')

        # Connect to the worker's listening socket. The worker's accept()
        # has a 10s timeout; we connect immediately so this should never
        # be slow.
        sock = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
        try:
            sock.connect(addr)
        except OSError as e:
            sock.close()
            raise ValueError('Could not attach to session worker: {}'.format(e))
        sock.setblocking(False)

        return worker_id, sock, proc


    def get(self):
        """Renders the connection page. Touches ``self.xsrf_token`` so
        Tornado issues the ``_xsrf`` cookie that the JS reads back into
        the X-XSRFToken header."""

        self.xsrf_token  # noqa: B018
        self.render('index.html')


    async def post(self):
        """Spawns a session worker for the supplied credentials and
        registers the resulting Worker proxy in the active sessions map.
        Logs the attempt to the audit log (without credentials)."""

        body_bytes = self.request.body

        # Best-effort metadata extraction for the audit log only — never
        # touches the password or key. If JSON is malformed the audit
        # entry will say "?".
        target = user = auth = '?'
        try:
            meta = json.loads(body_bytes)
            if isinstance(meta, dict):
                target = '{}:{}'.format(meta.get('hostname', '?'), meta.get('port', '?'))
                user = meta.get('username', '?')
                auth = 'key' if (isinstance(meta.get('privateKey'), str)
                                 and meta['privateKey'].strip()) else 'password'
        except (ValueError, TypeError):
            pass
        meta = None  # release reference

        worker_id = None
        status = None
        try:
            worker_id, sock, proc = await self._spawn_session(body_bytes)
        except Exception as e:  # noqa: BLE001
            status = str(e)
        finally:
            # Drop our reference to the credential-bearing body bytes.
            body_bytes = None

        if worker_id is not None:
            worker = Worker(worker_id, sock, proc, target)
            workers[worker_id] = worker
            tornado.ioloop.IOLoop.current().call_later(3, recycle, worker)

        if status:
            audit.info('connect ip=%s target=%s user=%s auth=%s status=fail reason=%r',
                       self.request.remote_ip, target, user, auth, status)
        else:
            audit.info('connect ip=%s target=%s user=%s auth=%s status=ok worker=%s',
                       self.request.remote_ip, target, user, auth, worker_id)

        self.write(dict(id=worker_id, status=status))
