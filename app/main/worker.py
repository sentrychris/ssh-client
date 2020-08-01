import tornado.websocket

from tornado.ioloop import IOLoop
from tornado.iostream import _ERRNO_CONNRESET
from tornado.util import errno_from_exception

BUF_SIZE = 1024


class Worker(object):
    def __init__(self, ssh, channel, dest_addr):
        self.loop = IOLoop.current()
        self.ssh = ssh
        self.channel = channel
        self.dest_addr = dest_addr
        self.fd = channel.fileno()
        self.id = str(id(self))
        self.data_to_dst = []
        self.handler = None
        self.mode = IOLoop.READ

    def __call__(self, fd, events):
        if events & IOLoop.READ:
            self.on_read()
        if events & IOLoop.WRITE:
            self.on_write()
        if events & IOLoop.ERROR:
            self.close()

    def set_handler(self, handler):
        if not self.handler:
            self.handler = handler

    def update_handler(self, mode):
        if self.mode != mode:
            self.loop.update_handler(self.fd, mode)
            self.mode = mode

    def on_read(self):
        try:
            data = self.channel.recv(BUF_SIZE)
        except (OSError, IOError) as e:
            if errno_from_exception(e) in _ERRNO_CONNRESET:
                self.close()
        else:
            if not data:
                self.close()
                return

            try:
                self.handler.write_message(data)
            except tornado.websocket.WebSocketClosedError:
                self.close()

    def on_write(self):
        if not self.data_to_dst:
            return

        data = ''.join(self.data_to_dst)

        try:
            sent = self.channel.send(data)
        except (OSError, IOError) as e:
            if errno_from_exception(e) in _ERRNO_CONNRESET:
                self.close()
            else:
                self.update_handler(IOLoop.WRITE)
        else:
            self.data_to_dst = []
            data = data[sent:]
            if data:
                self.data_to_dst.append(data)
                self.update_handler(IOLoop.WRITE)
            else:
                self.update_handler(IOLoop.READ)

    def close(self):
        if self.handler:
            self.loop.remove_handler(self.fd)
            self.handler.close()
        self.channel.close()
        self.ssh.close()
