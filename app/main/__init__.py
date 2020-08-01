import tornado.web

from .handler import IndexHandler, WebsocketHandler


def create_app(settings):
    app_handlers = [
        (r'/', IndexHandler),
        (r'/ws', WebsocketHandler)
    ]

    if settings is None:
        return False

    app = tornado.web.Application(app_handlers, **settings)

    return app




