import os
import weakref
from urllib.parse import urlparse

import tornado

from .base import workers


# Comma-separated extra origins (e.g. "https://wssh.app,https://staging.wssh.app").
# Same-origin (where the Origin host matches the request Host) is always allowed.
_ALLOWED_ORIGIN_HOSTS = {
    urlparse(o.strip()).netloc.lower()
    for o in os.environ.get('WSSH_ALLOWED_ORIGINS', '').split(',')
    if o.strip()
}


class WebsocketHandler(tornado.websocket.WebSocketHandler):
    """
    Handles websocket connections for the tornado application.

    Attributes:
        src_addr (str): The source address of the websocket connection.
        loop (IOLoop): The IOLoop instance used for handling events.
        worker_ref (weakref.ReferenceType): A weak reference to the associated worker.

    Methods:
        data_received(chunk): A placeholder for handling data received from the websocket.
        check_origin(origin): Checks whether the websocket connection origin is allowed.
        get_addr(): Retrieves the address of the websocket connection - IP and port.
        open(): Called when a websocket connection is established.
        on_message(message): Handles incoming messages from the websocket.
        on_close(): Called when the websocket connection is closed.
    """

    def __init__(self, application: tornado.web.Application,
                 request: tornado.httputil.HTTPServerRequest, **kwargs):
        """
        Initializes the WebSocketHandler.

        Args:
            application (Application): The Tornado application instance.
            request (HTTPServerRequest): The HTTP request associated with the websocket.
            **kwargs: Additional keyword arguments.
        """

        self.src_addr = None
        self.loop = tornado.ioloop.IOLoop.current()
        self.worker_ref = None
        super(self.__class__, self).__init__(application, request, **kwargs)


    def data_received(self, chunk: bytes):
        """
        Placeholder method for handling data received from the websocket.

        Args:
            chunk (bytes): The data chunk received from the websocket.
        """

        pass


    def check_origin(self, origin: str):
        """
        Restricts WebSocket connections to same-origin (or a configured
        allow-list via the ``WSSH_ALLOWED_ORIGINS`` env var). Prevents
        Cross-Site WebSocket Hijacking; the previous "always True" was the
        WS equivalent of CORS wide-open.
        """

        try:
            origin_host = urlparse(origin).netloc.lower()
        except Exception:
            return False
        if not origin_host:
            return False
        if origin_host == self.request.host.lower():
            return True
        return origin_host in _ALLOWED_ORIGIN_HOSTS


    def get_addr(self):
        """
        Retrieves the address of the websocket connection.

        Returns:
            str: The address of the websocket connection in the format 'IP:Port'.
        """

        ip = self.request.headers.get_list('X-Real-Ip')
        port = self.request.headers.get_list('X-Real-Port')
        addr = ':'.join(ip + port)

        if not addr:
            addr = self.request.remote_ip
            connection = self.request.connection
            if connection and connection.stream and connection.stream.socket:
                addr = '{}:{}'.format(addr, connection.stream.socket.getpeername()[1])
        return addr


    def open(self):
        """
        Called when a websocket connection is established.

        - Retrieves the worker associated with the websocket using the 'id' argument.
        - Sets the websocket to non-blocking mode.
        - Sets the handler for the worker.
        - Adds the worker file descriptor to the IOLoop for reading.
        """

        self.src_addr = self.get_addr()
        worker = workers.pop(self.get_argument('id'), None)

        if not worker:
            self.close(reason='Invalid worker id')
            return

        self.set_nodelay(True)

        worker.set_handler(self)
        self.worker_ref = weakref.ref(worker)
        self.loop.add_handler(worker.fd, worker, tornado.ioloop.IOLoop.READ)


    def on_message(self, message: str):
        """
        Forwards the WS message verbatim to the per-session subprocess.
        The subprocess parses the JSON envelope and dispatches:
            {"data":   "..."}                     -> SSH stdin
            {"resize": [cols, rows]}              -> channel.resize_pty
        Keeping the parsing in the subprocess means the credential-bearing
        process is the only one that ever touches terminal IO logic.
        """

        worker = self.worker_ref()
        if worker:
            worker.send_to_session(message)


    def on_close(self):
        """
        Called when the websocket connection is closed.

        - Closes the associated worker if it exists.
        """

        worker = self.worker_ref() if self.worker_ref else None

        if worker:
            worker.close()
