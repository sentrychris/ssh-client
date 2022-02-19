import tornado.web


workers = {}

def recycle(worker):
    if worker.handler:
        return
    workers.pop(worker.id, None)
    worker.close()


class BaseHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        pass


    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')


    def post(self):
        self.write('some post')


    def get(self):
        self.write('some get')


    def options(self):
        self.set_status(204)
        self.finish()
