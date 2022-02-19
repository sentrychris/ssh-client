import tornado.web

from .handlers.index import IndexHandler
from .handlers.websocket import WebsocketHandler


def create_app(settings):
    handlers = [
        (r'/', IndexHandler),
        (r'/ws', WebsocketHandler)
    ]

    if settings is None:
        return False

    app = tornado.web.Application(handlers, **settings)

    return app
