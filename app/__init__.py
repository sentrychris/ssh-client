import tornado

from .handlers.http import HttpHandler
from .handlers.websocket import WebsocketHandler


def create_app(settings: dict):
    """
    Creates and returns an application instance with specified settings.

    Args:
        settings (dict): Configuration settings for the application. 

    Returns:
        tornado.web.Application or bool: 
            - Returns an instance configured with HTTP and websocket handlers.

    Raises:
        TypeError: If `settings` is not a dictionary or `None`.

    Example:
        settings = {
            'debug': True,
            'static_path': '/path/to/static',
            'template_path': '/path/to/templates'
        }
        app = create_app(settings)
    """

    handlers = [
        (r'/', HttpHandler),
        (r'/ws', WebsocketHandler)
    ]

    app = tornado.web.Application(handlers, **settings)

    return app
