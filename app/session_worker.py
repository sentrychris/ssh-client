"""Per-session SSH subprocess.

Spawned by the main Tornado process for every accepted POST /. Owns one
SSH connection in its own address space — the main process never sees the
credentials beyond the brief window where it pipes the raw POST body
through this process's stdin.

CLI:
    python -m app.session_worker <abstract_socket_name>

Stdin (closed by parent after writing):
    A single JSON object:
        {"hostname": "...", "port": "22", "username": "...",
         "password": "...", "privateKey": "..."}

Stdout (one line, then the worker switches to socket mode):
    {"status": "ok"}                          - SSH connected, listening
    {"status": "error", "reason": "..."}     - failed; process exits non-zero

After "ok", the worker accepts ONE connection on the abstract Unix socket
``\\0<abstract_socket_name>`` and bridges bytes:

    Inbound  (main → worker), one JSON envelope per line:
        {"data":   "..."}                    - terminal stdin
        {"resize": [cols, rows]}             - PTY window-change

    Outbound (worker → main): raw bytes (terminal stdout). Main wraps them
        in a binary WebSocket frame.

Either side closing the socket ends the session and the subprocess exits.
"""

import io
import ipaddress
import json
import os
import select
import socket as socket_mod
import sys

import paramiko


def _is_safe_target(hostname):
    """SSRF check, mirrors the one in app.handlers.http."""

    if os.environ.get('WSSH_ALLOW_PRIVATE_TARGETS', '').lower() in ('1', 'true', 'yes'):
        return True
    try:
        infos = socket_mod.getaddrinfo(hostname, None, type=socket_mod.SOCK_STREAM)
    except socket_mod.gaierror:
        return False
    for _, _, _, _, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


def _parse_private_key(text, password):
    """Try RSA → ECDSA → Ed25519 and return a paramiko key object."""

    pwd = password.encode('utf-8') if password else None
    for cls in (paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key):
        try:
            return cls.from_private_key(io.StringIO(text), pwd)
        except paramiko.PasswordRequiredException:
            raise ValueError('A password is required to decrypt the private key.')
        except paramiko.SSHException:
            continue
    raise ValueError('Not a valid private key file or wrong password for '
                     'decrypting the private key.')


def _reply(obj):
    sys.stdout.write(json.dumps(obj) + '\n')
    sys.stdout.flush()


def _validate_port(value):
    try:
        port = int(value)
    except (ValueError, TypeError):
        port = 0
    if 0 < port < 65536:
        return port
    raise ValueError('Invalid port {}'.format(value))


def _connect(body):
    """Returns (ssh_client, channel) or raises ValueError with a user-facing message."""

    hostname = body.get('hostname', '').strip()
    port = _validate_port(body.get('port', 22))
    username = body.get('username', '')
    password = body.get('password', '')
    private_key_text = body.get('privateKey')

    if not hostname:
        raise ValueError('Hostname is required.')

    if not _is_safe_target(hostname):
        raise ValueError('Target host not allowed (private, loopback, and '
                         'link-local addresses are blocked).')

    parsed_key = _parse_private_key(private_key_text, password) if private_key_text else None

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(hostname, port, username, password, parsed_key, timeout=6)
    except socket_mod.error:
        raise ValueError('Unable to connect to {}:{}'.format(hostname, port))
    except paramiko.AuthenticationException as e:
        raise ValueError(str(e) or 'Authentication failed.')

    channel = ssh.invoke_shell(term='xterm-256color')
    channel.setblocking(False)
    return ssh, channel


def _bridge(client_sock, channel):
    """Pump bytes between the local Unix socket and the SSH channel until
    either side closes."""

    client_sock.setblocking(False)
    in_buf = b''

    while True:
        try:
            r, _, _ = select.select([client_sock, channel], [], [], 30)
        except (OSError, ValueError):
            break
        if not r:
            continue

        if client_sock in r:
            try:
                chunk = client_sock.recv(4096)
            except (BlockingIOError, OSError):
                chunk = b''
            if not chunk:
                break
            in_buf += chunk
            while b'\n' in in_buf:
                line, in_buf = in_buf.split(b'\n', 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(msg, dict):
                    continue
                if 'data' in msg and isinstance(msg['data'], str):
                    try:
                        channel.send(msg['data'])
                    except OSError:
                        return
                elif 'resize' in msg:
                    try:
                        cols, rows = msg['resize']
                        channel.resize_pty(width=int(cols), height=int(rows))
                    except (OSError, IOError, TypeError, ValueError):
                        pass

        if channel in r:
            try:
                data = channel.recv(4096)
            except (BlockingIOError, OSError):
                continue
            if not data:
                break
            try:
                client_sock.sendall(data)
            except (BrokenPipeError, OSError):
                break


def main():
    if len(sys.argv) != 2:
        _reply({'status': 'error', 'reason': 'usage: session_worker <abstract_name>'})
        sys.exit(2)
    abstract_name = sys.argv[1]
    addr = b'\0' + abstract_name.encode('ascii')

    raw = sys.stdin.read()
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
    except (ValueError, TypeError):
        _reply({'status': 'error', 'reason': 'invalid request body'})
        sys.exit(1)

    try:
        ssh, channel = _connect(body)
    except ValueError as e:
        _reply({'status': 'error', 'reason': str(e)})
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        _reply({'status': 'error', 'reason': str(e) or 'Connection failed.'})
        sys.exit(1)

    # Best-effort: drop credential references so the GC can reclaim the
    # strings sooner. Python doesn't guarantee zeroing, but holding fewer
    # live references narrows the post-connect leak window.
    body.clear()
    raw = None

    server = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
    try:
        server.bind(addr)
        server.listen(1)
        server.settimeout(10)
    except OSError as e:
        _reply({'status': 'error', 'reason': 'socket bind failed: {}'.format(e)})
        ssh.close()
        sys.exit(1)

    _reply({'status': 'ok'})

    try:
        client_sock, _ = server.accept()
    except socket_mod.timeout:
        ssh.close()
        sys.exit(1)
    finally:
        server.close()

    try:
        _bridge(client_sock, channel)
    finally:
        try:
            client_sock.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            channel.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            ssh.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()
