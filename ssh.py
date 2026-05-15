import asyncio
import uuid
import os.path

from tornado.options import define, options, parse_command_line
from app import create_app

# Define base directory
base_dir = os.path.dirname(__file__)


# Define command-line options
define('address', default='0.0.0.0', help='Listen address for the application')
define('port', default=4500, help='Listen port for the application', type=int)


async def run():
    """
    Starts the tornado application server and listens on the specified address and port.
    """

    # Parse command line arguments
    parse_command_line()

    app = create_app({
        'template_path': os.path.join(base_dir, 'public'),
        'static_path': os.path.join(base_dir, 'public'),
        'cookie_secret': uuid.uuid1().hex,
        'xsrf_cookies': False,
        'debug': True
    })

    # Start the tornado server
    app.listen(options.port, options.address)
    print("Listening on http://{}:{}".format(options.address, options.port))
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(run())
