import uuid
import os.path

from tornado.options import define, options
from tornado.ioloop import IOLoop
from app.main import create_app

base_dir = os.path.dirname(__file__)

app = create_app({
    'template_path': os.path.join(base_dir, 'public'),
    'static_path': os.path.join(base_dir, 'public'),
    'cookie_secret': uuid.uuid1().hex,
    'xsrf_cookies': False,
    'debug': True
})

define('address', default='0.0.0.0', help='listen address')
define('port', default=4200, help='listen port', type=int)


def run():
    app.listen(options.port, options.address)
    print("Listening on http://localhost:" + str(options.port))
    IOLoop.current().start()


if __name__ == '__main__':
    run()
