"""Tiny mock SSH server for manual UI testing of the web SSH client.

Listens on 127.0.0.1:2222, accepts any username/password, and bridges each
session to a real local /bin/bash.

Run it::

    .venv/bin/python /tmp/mock_sshd.py

Then connect from the web UI:

    Hostname: 127.0.0.1
    Port:     2222
    Username: <anything>
    Password: <anything>

Ctrl-C to stop. Multiple back-to-back connections are fine.
"""
import fcntl
import os
import pty
import select
import socket
import struct
import sys
import termios
import threading

import paramiko

HOST = '127.0.0.1'
PORT = 2222


class MockServer(paramiko.ServerInterface):
    def __init__(self):
        self.shell_event = threading.Event()
        self.initial_size = (80, 24)
        self.master_fd = None  # set by the session before window-change can fire

    def get_allowed_auths(self, username):
        return 'password,publickey'

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == 'session' \
            else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height,
                                  pixelwidth, pixelheight, modes):
        self.initial_size = (width, height)
        return True

    def check_channel_shell_request(self, channel):
        self.shell_event.set()
        return True

    def check_channel_window_change_request(self, channel, width, height,
                                            pixelwidth, pixelheight):
        if self.master_fd is None:
            return True
        try:
            fcntl.ioctl(
                self.master_fd, termios.TIOCSWINSZ,
                struct.pack('HHHH', height, width, 0, 0),
            )
        except OSError:
            return False
        return True


def spawn_pty_shell(initial_cols, initial_rows):
    """Fork a /bin/bash attached to a fresh PTY. Returns (pid, master_fd)."""
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(
        master_fd, termios.TIOCSWINSZ,
        struct.pack('HHHH', initial_rows, initial_cols, 0, 0),
    )
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os.close(master_fd)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        try:
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        except OSError:
            pass
        os.environ['TERM'] = 'xterm-256color'
        os.execvp('bash', ['bash', '-i'])
    os.close(slave_fd)
    return pid, master_fd


def handle_session(client_sock, client_addr, host_key):
    print(f'[mock-sshd] connection from {client_addr}')
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(host_key)
    server = MockServer()
    try:
        transport.start_server(server=server)
    except paramiko.SSHException as e:
        print(f'[mock-sshd] handshake failed: {e}')
        return

    channel = transport.accept(timeout=10)
    if channel is None:
        print('[mock-sshd] no channel opened')
        transport.close()
        return

    if not server.shell_event.wait(timeout=10):
        print('[mock-sshd] client never requested a shell')
        channel.close()
        transport.close()
        return

    cols, rows = server.initial_size
    pid, master_fd = spawn_pty_shell(cols, rows)
    server.master_fd = master_fd
    print(f'[mock-sshd] spawned bash pid={pid} fd={master_fd} {cols}x{rows}')

    # Bridge bytes between the SSH channel and the PTY master fd until either
    # side closes. select() over both readers is the simplest reliable form.
    try:
        while True:
            r, _, _ = select.select([channel, master_fd], [], [], 1.0)
            if channel in r:
                try:
                    data = channel.recv(4096)
                except OSError:
                    data = b''
                if not data:
                    break
                os.write(master_fd, data)
            if master_fd in r:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                channel.send(data)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        try:
            channel.close()
        except Exception:
            pass
        try:
            transport.close()
        except Exception:
            pass
        print(f'[mock-sshd] {client_addr} disconnected')


def main():
    host_key = paramiko.RSAKey.generate(2048)
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind((HOST, PORT))
    except OSError as e:
        print(f'[mock-sshd] bind {HOST}:{PORT} failed: {e}', file=sys.stderr)
        sys.exit(1)
    server_sock.listen(5)
    print(f'[mock-sshd] listening on {HOST}:{PORT} '
          f'(any username/password accepted)')
    try:
        while True:
            client_sock, client_addr = server_sock.accept()
            t = threading.Thread(
                target=handle_session,
                args=(client_sock, client_addr, host_key),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        print('\n[mock-sshd] shutting down')
    finally:
        server_sock.close()


if __name__ == '__main__':
    main()
