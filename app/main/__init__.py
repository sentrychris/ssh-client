import tornado.web

from .handlers.http import HttpHandler
from .handlers.websocket import WebsocketHandler


def create_app(settings):
    handlers = [
        (r'/', HttpHandler),
        (r'/ws', WebsocketHandler)
    ]

    if settings is None:
        return False

    app = tornado.web.Application(handlers, **settings)

    return app
