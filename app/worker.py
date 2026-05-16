import os
import signal
import socket as socket_mod
import time

from tornado.ioloop import IOLoop
from tornado.websocket import WebSocketClosedError

from .handlers.base import ip_limiter


class Worker:
    """
    Bridges a WebSocket handler to a per-session SSH subprocess via an
    abstract Unix domain socket. The subprocess (``app.session_worker``)
    holds the SSH client and credentials; this main-process proxy only
    sees opaque bytes.

    Wire protocol on the Unix socket:
      Outbound (this proxy → subprocess): line-delimited JSON envelopes
        identical to what the WebSocket client speaks ({"data":...} /
        {"resize":[cols, rows]}).
      Inbound  (subprocess → this proxy): raw bytes (terminal stdout),
        forwarded as-is into a binary WebSocket frame.
    """

    def __init__(self, worker_id, sock, subprocess_obj, dest_addr, client_ip):
        self.id = worker_id
        self.sock = sock                 # connected AF_UNIX socket (non-blocking)
        self.fd = sock.fileno()
        self.subprocess = subprocess_obj # tornado.process.Subprocess; .proc is Popen
        self.dest_addr = dest_addr
        self.client_ip = client_ip       # held until close() so ip_limiter can release
        self.handler = None
        self.loop = IOLoop.current()
        self.mode = IOLoop.READ
        self._pending_writes = b''       # bytes queued for the subprocess
        # Activity tracking for the idle / max-session reaper. Updated on
        # both inbound and outbound traffic so live-tail sessions (htop,
        # tail -f) aren't reaped while output is still flowing.
        self.created_at = time.monotonic()
        self.last_activity_at = self.created_at


    def __call__(self, fd, events):
        if events & IOLoop.READ:
            self._on_read()
        if events & IOLoop.WRITE:
            self._on_write()
        if events & IOLoop.ERROR:
            self.close()


    def set_handler(self, handler):
        if not self.handler:
            self.handler = handler


    def _update_mode(self, mode):
        if self.mode != mode:
            try:
                self.loop.update_handler(self.fd, mode)
            except (KeyError, OSError):
                return
            self.mode = mode


    def _on_read(self):
        try:
            data = self.sock.recv(4096)
        except (BlockingIOError, OSError):
            return
        if not data:
            self.close()
            return
        self.last_activity_at = time.monotonic()
        if not self.handler:
            return
        try:
            # Same wire format as the old paramiko-bridging Worker: binary
            # WS frames, so multi-byte UTF-8 split across recv() boundaries
            # doesn't trip the browser's text-frame UTF-8 decoder.
            self.handler.write_message(data, binary=True)
        except WebSocketClosedError:
            self.close()


    def _on_write(self):
        if not self._pending_writes:
            self._update_mode(IOLoop.READ)
            return
        try:
            sent = self.sock.send(self._pending_writes)
        except (BlockingIOError, OSError):
            return
        self._pending_writes = self._pending_writes[sent:]
        if not self._pending_writes:
            self._update_mode(IOLoop.READ)


    def send_to_session(self, message):
        """Forward a WS message (already a JSON envelope) to the subprocess.
        Appends a newline so the worker's line-delimited parser advances."""

        if isinstance(message, str):
            line = message.encode('utf-8') + b'\n'
        elif isinstance(message, (bytes, bytearray)):
            line = bytes(message) + b'\n'
        else:
            return

        self.last_activity_at = time.monotonic()
        self._pending_writes += line
        # Try a non-blocking write right away; if it would block, the
        # IOLoop WRITE event will drain the rest.
        try:
            sent = self.sock.send(self._pending_writes)
        except (BlockingIOError, OSError):
            sent = 0
        self._pending_writes = self._pending_writes[sent:]
        if self._pending_writes:
            self._update_mode(IOLoop.READ | IOLoop.WRITE)


    def close(self):
        # Drop from the active-sessions registry so the reaper / recycle
        # don't see us again. Local import to avoid a circular import at
        # module load time.
        from .handlers.base import workers
        workers.pop(self.id, None)

        # Release the per-IP slot first, idempotently — close() can be
        # called from multiple paths (WS close, reaper, recycle).
        if self.client_ip is not None:
            ip_limiter.release(self.client_ip)
            self.client_ip = None

        if self.handler:
            try:
                self.loop.remove_handler(self.fd)
            except (KeyError, OSError):
                pass
            try:
                self.handler.close()
            except Exception:  # noqa: BLE001
                pass
            self.handler = None

        if self.sock is not None:
            try:
                self.sock.shutdown(socket_mod.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

        # Reap the subprocess. Closing the socket should make it exit on its
        # own; SIGTERM ensures it does, and waitpid clears the zombie.
        if self.subprocess is not None:
            popen = getattr(self.subprocess, 'proc', None)
            if popen is not None and popen.poll() is None:
                try:
                    popen.terminate()
                except (ProcessLookupError, OSError):
                    pass
            if popen is not None:
                try:
                    popen.wait(timeout=2)
                except Exception:  # noqa: BLE001
                    try:
                        popen.kill()
                    except (ProcessLookupError, OSError):
                        pass
            self.subprocess = None
