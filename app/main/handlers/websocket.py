import weakref
import tornado

from .base import workers


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
        Checks whether the websocket connection origin is allowed.

        Args:
            origin (str): The origin of the websocket connection.

        Returns:
            bool: Always returns True, allowing connections from any origin.
        """

        return True


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
        Handles incoming messages from the websocket.

        Args:
            message (str): The message received from the websocket.
        """

        worker = self.worker_ref()
        worker.data_to_dst.append(message)
        worker.on_write()


    def on_close(self):
        """
        Called when the websocket connection is closed.

        - Closes the associated worker if it exists.
        """

        worker = self.worker_ref() if self.worker_ref else None

        if worker:
            worker.close()
