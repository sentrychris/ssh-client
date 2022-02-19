import io
import socket
import paramiko

from tornado.ioloop import IOLoop
from ..worker import Worker
from .base import BaseHandler, workers, recycle


class IndexHandler(BaseHandler):
    def get_privatekey(self):
        try:
            data = self.request.files.get('privatekey')[0]['body']
        except TypeError:
            return

        return data.decode('utf-8')


    def get_specific_pkey(self, pkeycls, privatekey, password):
        try:
            pkey = pkeycls.from_private_key(io.StringIO(privatekey), password=password)
        except paramiko.PasswordRequiredException:
            raise ValueError('Need password to decrypt the private key.')
        except paramiko.SSHException:
            pass
        else:
            return pkey


    def get_pkey(self, privatekey, password):
        password = password.encode('utf-8') if password else None

        pkey = self.get_specific_pkey(paramiko.RSAKey, privatekey, password)\
            or self.get_specific_pkey(paramiko.DSSKey, privatekey, password)\
            or self.get_specific_pkey(paramiko.ECDSAKey, privatekey, password)\
            or self.get_specific_pkey(paramiko.Ed25519Key, privatekey,
                                      password)
        if not pkey:
            raise ValueError('Not a valid private key file or '
                             'wrong password for decrypting the private key.')
        return pkey


    def get_port(self):
        value = self.get_value('port')
        try:
            port = int(value)
        except ValueError:
            port = 0

        if 0 < port < 65536:
            return port

        raise ValueError('Invalid port {}'.format(value))


    def get_value(self, name):
        value = self.get_argument(name)

        if not value:
            raise ValueError('Empty {}'.format(name))

        return value


    def get_args(self):
        hostname = self.get_value('hostname')
        port = self.get_port()
        username = self.get_value('username')
        password = self.get_argument('password')
        privatekey = self.get_privatekey()
        pkey = self.get_pkey(privatekey, password) if privatekey else None
        args = (hostname, port, username, password, pkey)

        return args


    def ssh_connect(self):
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        args = self.get_args()
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
        IOLoop.current().call_later(3, recycle, worker)

        return worker


    def get(self):
        self.render('index.html')


    def post(self):
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
