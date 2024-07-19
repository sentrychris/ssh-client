import io
import socket
import paramiko
import tornado

from typing import Type, Union, Optional

from ..worker import Worker
from .base import BaseHandler, workers, recycle


# Define a type alias for the key classes
PrivateKey = Type[Union[
    paramiko.RSAKey,
    paramiko.DSSKey,
    paramiko.ECDSAKey,
    paramiko.Ed25519Key
]]


class HttpHandler(BaseHandler):
    """
    HTTPHandler class for managing SSH connections. This handler processes connection requests
    via HTTP POST and serves the connection index page via HTTP GET. 
    """


    def get_private_key(self):
        """
        Retrieves and decodes the private key from the request files.

        Returns:
            str on None: The decoded private key as a UTF-8 string, or None if the private key
            is not found or an error occurs.
        """

        try:
            data = self.request.files.get('privatekey')[0]['body']
        except TypeError:
            return

        return data.decode('utf-8')


    @staticmethod
    def get_private_key_by_class(private_key_class: PrivateKey, private_key: str, password: Optional[str]):
        """
        Parses a private key using the given class and password.

        Args:
            private_key_class (KeyClass): The class of the private key e.g. paramiko.RSAKey.
            private_key (str): The private key as a string.
            password (Optional[str]): The password for decrypting the private key.
        
        Returns:
            PrivateKey or None: The parsed private key object (or none if it fails).

        Raises:
            ValueError: If a password is required but not provided.
        """

        try:
            parsed_key = private_key_class.from_private_key(io.StringIO(private_key), password)
        except paramiko.PasswordRequiredException:
            raise ValueError('A password is required to decrypt the private key.')
        except paramiko.SSHException:
            pass
        else:
            return parsed_key


    def get_parsed_key(self, private_key: str, password: Optional[str]):
        """
        Attempts to parse the private key using different key classes.

        Args:
            private_key (str): The private key as a string.
            password (Optional[str]): The password for decrypting the private key.

        Returns:
            PrivateKey: The parsed private key object.

        Raises:
            ValueError: If the private key is invalid or the password is incorrect.
        """

        password = password.encode('utf-8') if password else None

        parsed_key = self.get_private_key_by_class(paramiko.RSAKey, private_key, password)\
            or self.get_private_key_by_class(paramiko.DSSKey, private_key, password)\
            or self.get_private_key_by_class(paramiko.ECDSAKey, private_key, password)\
            or self.get_private_key_by_class(paramiko.Ed25519Key, private_key, password)

        if not parsed_key:
            raise ValueError('Not a valid private key file or '
                             'wrong password for decrypting the private key.')
        return parsed_key


    @staticmethod
    def validate_port(port):
        """
        Validates and converts a port to an integer.

        Args:
            port (str): The port to validate.

        Returns:
            int: The validated port number.

        Raises:
            ValueError: If the port is not a valid integer or out of range.
        """

        try:
            port = int(port)
        except ValueError:
            port = 0

        if 0 < port < 65536:
            return port

        raise ValueError('Invalid port {}'.format(port))


    def get_post_args(self):
        """
        Extracts and validates arguments from the POST request body.

        Returns:
            tuple: A tuple containing (hostname, port, username, password, parsed_key),
            where `parsed_key` is None if no private key was provided.
        """

        req = tornado.escape.json_decode(self.request.body)

        hostname = req['hostname']
        port = self.validate_port(req['port'])

        username = req['username']
        password = req['password']

        private_key = self.get_private_key()
        parsed_key = self.get_parsed_key(private_key, password) if private_key else None

        args = (hostname, port, username, password, parsed_key)

        return args


    def ssh_connect(self):
        """
        Establishes an SSH connection based on HTTP POST request arguments.

        Returns:
            Worker: The worker object managing the SSH connection.

        Raises:
            ValueError: If the connection fails or authentication fails.
        """

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        args = self.get_post_args()
        dest_addr = '{}:{}'.format(*args[:2])

        try:
            ssh.connect(*args, timeout=6)
        except socket.error:
            raise ValueError('Unable to connect to {}'.format(dest_addr))
        except paramiko.BadAuthenticationType:
            raise ValueError('Authentication failed.')

        channel = ssh.invoke_shell(term='xterm')
        channel.setblocking(False)

        worker = Worker(ssh, channel, dest_addr)
        tornado.ioloop.IOLoop.current().call_later(3, recycle, worker)

        return worker


    def get(self):
        """
        Handles HTTP GET requests. Renders the connection index page.
        """

        self.render('index.html')


    def post(self):
        """
        Handles POST requests. Attempts to establish an SSH connection and returns the
        worker ID and status.

        Returns:
            dict: A dictionary containing `id` (worker ID) and `status` (status message).
        """

        worker_id = None
        status = None

        try:
            worker = self.ssh_connect()
        except Exception as e:
            status = str(e)
        else:
            worker_id = worker.id
            workers[worker_id] = worker

        self.write(dict(id=worker_id, status=status))
