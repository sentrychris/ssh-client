import tornado


# Dictionary to store active workers
workers = {}


def recycle(worker):
    """
    Recycles a worker by removing it from the workers dictionary if its handler is not set.

    Args:
        worker: The worker object to recycle.
    
    Returns:
        None
    """

    if worker.handler:
        return
    workers.pop(worker.id, None)
    worker.close()


class BaseHandler(tornado.web.RequestHandler):
    """
    BaseHandler class for handling HTTP requests. CORS headers are set by default.
    """


    def set_default_headers(self):
        """
        Sets default headers for CORS.
        """

        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')


    def post(self):
        """
        Base HTTP POST request handler.
        """

        self.write('silence is golden.')


    def get(self):
        """
        Base HTTP GET request handler.
        """

        self.write('silence is golden.')


    def options(self):
        """
        Base HTTP OPTIONS request handler.
        """

        self.set_status(204)
        self.finish()
