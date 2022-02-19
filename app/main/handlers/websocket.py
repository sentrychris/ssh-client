import tornado.websocket
import weakref

from tornado.ioloop import IOLoop
from .base import workers


class WebsocketHandler(tornado.websocket.WebSocketHandler):
    def __init__(self, *args, **kwargs):
        self.src_addr = None
        self.loop = IOLoop.current()
        self.worker_ref = None
        super(self.__class__, self).__init__(*args, **kwargs)


    def data_received(self, chunk):
        pass


    def check_origin(self, origin):
        return True


    def get_addr(self):
        ip = self.request.headers.get_list('X-Real-Ip')
        port = self.request.headers.get_list('X-Real-Port')
        addr = ':'.join(ip + port)

        if not addr:
            addr = '{}:{}'.format(*self.stream.socket.getpeername())
        return addr


    def open(self):
        self.src_addr = self.get_addr()
        worker = workers.pop(self.get_argument('id'), None)

        if not worker:
            self.close(reason='Invalid worker id')
            return

        self.set_nodelay(True)

        worker.set_handler(self)
        self.worker_ref = weakref.ref(worker)
        self.loop.add_handler(worker.fd, worker, IOLoop.READ)


    def on_message(self, message):
        worker = self.worker_ref()
        worker.data_to_dst.append(message)
        worker.on_write()


    def on_close(self):
        worker = self.worker_ref() if self.worker_ref else None

        if worker:
            worker.close()
