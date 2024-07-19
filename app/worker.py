from tornado.ioloop import IOLoop
from tornado.iostream import _ERRNO_CONNRESET
from tornado.util import errno_from_exception
from tornado.websocket import WebSocketClosedError
from paramiko import SSHClient, Channel

from .handlers.websocket import WebsocketHandler


class Worker(object):
    """
    Manages communication between an SSH channel and a websocket handler.

    Attributes:
        loop (IOLoop): The IOLoop instance used for handling events.
        ssh (paramiko.SSHClient): The SSH client instance associated with the worker.
        channel (paramiko.Channel): The SSH channel used for communication.
        dest_addr (str): The destination address for the SSH connection.
        fd (int): The file descriptor for the SSH channel.
        id (str): Unique identifier for the worker instance.
        data_to_dest (list of str): Buffer to hold data that needs to be sent to the SSH channel.
        handler (WebSocketHandler | None): The websocket handler associated with the worker.
        mode (int): The IOLoop mode for handling the worker's file descriptor (READ or WRITE).

    Methods:
        __call__(fd, events): Handles IOLoop events for the worker (READ, WRITE, ERROR).
        set_handler(handler): Sets the websocket handler for the worker if not already set.
        update_handler(mode): Updates the IOLoop handler mode (READ or WRITE).
        on_read(): Reads data from the SSH channel and sends it to the websocket handler.
        on_write(): Sends buffered data to the SSH channel.
        close(): Closes the worker, SSH channel, and SSH client.
    """

    def __init__(self, ssh: SSHClient, channel: Channel, dest_addr: str):
        """
        Initializes the Worker instance.

        Args:
            ssh (paramiko.SSHClient): The SSH client instance.
            channel (paramiko.Channel): The SSH channel for communication.
            dest_addr (str): The destination address for the SSH connection.
        """

        self.loop = IOLoop.current()
        self.ssh = ssh
        self.channel = channel
        self.dest_addr = dest_addr
        self.fd = channel.fileno()
        self.id = str(id(self))
        self.data_to_dest = []
        self.handler = None
        self.mode = IOLoop.READ


    def __call__(self, fd: int, events: int):
        """
        Handles IOLoop events for the worker.

        Args:
            fd (int): The file descriptor for the event.
            events (int): The bitmask of events (READ, WRITE, ERROR) to handle.
        """

        if events & IOLoop.READ:
            self.on_read()
        if events & IOLoop.WRITE:
            self.on_write()
        if events & IOLoop.ERROR:
            self.close()


    def set_handler(self, handler: WebsocketHandler):
        """
        Sets the websocket handler for the worker if it is not already set.

        Args:
            handler (WebSocketHandler): The websocket handler to be set.
        """

        if not self.handler:
            self.handler = handler


    def update_handler(self, mode: int):
        """
        Updates the IOLoop handler mode if it has changed.

        Args:
            mode (int): The new IOLoop mode (READ or WRITE).
        """

        if self.mode != mode:
            self.loop.update_handler(self.fd, mode)
            self.mode = mode


    def on_read(self):
        """
        Reads data from the SSH channel and sends it to the websocket handler.
        Closes the worker if there is an error or if the channel is closed.
        """

        try:
            data = self.channel.recv(1024)
        except (OSError, IOError) as e:
            if errno_from_exception(e) in _ERRNO_CONNRESET:
                self.close()
        else:
            if not data:
                self.close()
                return

            try:
                self.handler.write_message(data)
            except WebSocketClosedError:
                self.close()


    def on_write(self):
        """
        Sends buffered data to the SSH channel.
        Updates the IOLoop handler mode based on whether more data needs to be sent or read.
        """

        if not self.data_to_dest:
            return

        data = ''.join(self.data_to_dest)

        try:
            sent = self.channel.send(data)
        except (OSError, IOError) as e:
            if errno_from_exception(e) in _ERRNO_CONNRESET:
                self.close()
            else:
                self.update_handler(IOLoop.WRITE)
        else:
            self.data_to_dest = []
            data = data[sent:]
            if data:
                self.data_to_dest.append(data)
                self.update_handler(IOLoop.WRITE)
            else:
                self.update_handler(IOLoop.READ)


    def close(self):
        """
        Closes the worker, SSH channel, and SSH client.
        Removes the worker's file descriptor from the IOLoop and closes the websocket handler if set.
        """

        if self.handler:
            self.loop.remove_handler(self.fd)
            self.handler.close()

        self.channel.close()
        self.ssh.close()
