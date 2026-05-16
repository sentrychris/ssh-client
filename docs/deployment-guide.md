# wssh - production deployment guide

Step-by-step for deploying wssh behind Apache with TLS, includes a systemd
unit, the security configuration, and rate limiting at the edge.

This is targeted at Ubuntu 22.04 / Debian 12 but can be adjusted for other distros.

---

## 1. Architecture

```
┌──────────┐  HTTPS   ┌──────────┐   HTTP+WS   ┌────────────┐
│ Browser  │─────────▶│  Apache  │────────────▶│  Tornado   │
│          │   :443   │  reverse │   :9001     │  (wssh)    │
└──────────┘          │  proxy   │  127.0.0.1  │  ssh.py    │
                      └──────────┘             └────────────┘
                          │
                       Let's
                      Encrypt
```

Apache proxies everything to the Tornado app on
`127.0.0.1:9001`. `/ws` goes through `mod_proxy_wstunnel` and everything else
through `mod_proxy_http`. Tornado serves the built static bundle from
`/opt/wssh` (or wherever you decide to put it).

---

## 2. Prerequisites

- A domain (e.g. `wssh.app`) with an A/AAAA record pointing at the server.
- root or sudo.
- Python 3.10 or newer.
- Node 18 or newer (for the Vite build).

Install the system packages:

```sh
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip \
    nodejs npm \
    apache2 libapache2-mod-evasive \
    certbot python3-certbot-apache \
    git
```

Enable the required Apache modules:

```sh
sudo a2enmod proxy proxy_http proxy_wstunnel headers ssl rewrite evasive
sudo systemctl restart apache2
```

---

## 3. Create the unprivileged service user

```sh
sudo useradd --system --no-create-home --shell /usr/sbin/nologin wssh
```

This user owns the install directory and runs the Tornado process. It cannot
log in interactively.

---

## 4. Deploy the application

```sh
sudo git clone https://github.com/sentrychris/wssh.git /opt/wssh
cd /opt/wssh

sudo python3 -m venv .venv
sudo .venv/bin/pip install .

sudo npm install
sudo npm run build

sudo chown -R wssh:wssh /opt/wssh
```

The build produces `/opt/wssh/public/{index.html,js,css,img}` - Tornado's
`static_path` and `template_path` both point here.

---

## 5. Audit log directory

```sh
sudo mkdir -p /var/log/wssh
sudo chown wssh:wssh /var/log/wssh
sudo chmod 750 /var/log/wssh
```

The audit log records every connection attempt with IP / target / user /
auth method / status. **Passwords and key contents are never logged.**

---

## 6. Generate a stable cookie secret

```sh
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Save the output. It goes into the systemd unit as `WSSH_COOKIE_SECRET`.
Without a stable secret, every restart invalidates issued XSRF tokens, so
users mid-form would get a 403 after a redeploy.

---

## 7. systemd unit

A ready-to-edit template lives in the repo at
[`systemd/wssh.service`](../systemd/wssh.service). Copy it into place and
fill in the placeholders (`<user>`, `<group>`, the cookie secret, your
install path):

```sh
sudo cp /opt/wssh/systemd/wssh.service /etc/systemd/system/wssh.service
sudo $EDITOR /etc/systemd/system/wssh.service
```

For reference, the unit:

```ini
[Unit]
Description=wssh - web-based SSH client
Documentation=https://github.com/sentrychris/ssh-client
After=network.target

[Service]
Type=simple
User=<user>
Group=<group>
Environment=WSSH_DEBUG=0
Environment=WSSH_COOKIE_SECRET=<32-byte hex secret from step 6>
Environment=WSSH_AUDIT_LOG=/var/log/wssh/audit.log
Environment=WSSH_ALLOWED_ORIGINS=https://wssh.app
WorkingDirectory=/opt/wssh
ExecStart=/opt/wssh/.venv/bin/python /opt/wssh/ssh.py --address=127.0.0.1 --port=9001
Restart=on-failure
RestartSec=5

# --- resource limits ---
# Each active session = one Python subprocess (~30 MB resident). Tune for
# your host; values below are reasonable for a 2 GB / 2 vCPU VPS.
MemoryHigh=768M
MemoryMax=1G
CPUQuota=200%
TasksMax=512
LimitNOFILE=4096

# --- kernel hardening (safe, no impact on outbound SSH) ---
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

> **About the resource limits.** `MemoryMax` triggers an OOM kill on the
> *whole* service if it's exceeded - protecting the host but ending all
> active sessions. `MemoryHigh` is a softer throttle. `TasksMax` caps the
> total threads/processes (each session = one subprocess + Tornado's
> couple of helpers). `CPUQuota=200%` allows up to two full cores. Tune
> for your hardware: at the defaults above and ~30 MB per subprocess, the
> service handles roughly 25–30 concurrent sessions before OOM, well
> matched to a 2 GB VPS with everything else running on it.

> **About the omitted sandbox flags.** `NoNewPrivileges`, `PrivateTmp`,
> `ProtectSystem=strict`, `ReadWritePaths`, and `ProtectHome=true` are
> deliberately *not* in this unit - `ProtectHome=true` in particular
> hides `~/.ssh/known_hosts` from paramiko, which causes confusing
> outbound SSH behaviour even though paramiko's loader silently swallows
> the IOError. If you don't need outbound SSH from `~/.ssh/*` at all and
> want to add the rest back, copy from the previous version of this
> guide; just leave `ProtectHome` off.

Enable and start:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now wssh
sudo systemctl status wssh
journalctl -u wssh -f
```

---

## 8. Apache vhost

File: `/etc/apache2/sites-available/<domain>.conf`

```apache
<VirtualHost *:80>
    ServerName <domain>

    ProxyRequests Off
    ProxyPreserveHost On

    # WebSocket - must come BEFORE the catch-all
    ProxyPass        /ws ws://127.0.0.1:9001/ws
    ProxyPassReverse /ws ws://127.0.0.1:9001/ws

    # Everything else (HTML, CSS, JS, SVG, POST /)
    ProxyPass        / http://127.0.0.1:9001/
    ProxyPassReverse / http://127.0.0.1:9001/
</VirtualHost>
```

> The Tornado app already emits the security headers (HSTS, CSP,
> X-Frame-Options, X-Content-Type-Options, Referrer-Policy,
> Permissions-Policy) on every response, so you do not need to add them at
> the Apache layer. Doing so would be harmless but redundant.

Enable and reload:

```sh
sudo a2ensite wssh.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

---

## 9. TLS certificate

Issue a Let's Encrypt cert via certbot:

```sh
sudo certbot --apache -d <domain>
```

Certbot will offer to write the redirect block automatically.

Auto-renewal is installed by the certbot package; verify with:

```sh
sudo systemctl list-timers | grep certbot
```

---

## 10. Rate limiting (mod_evasive)

File: `/etc/apache2/mods-available/evasive.conf`

```apache
<IfModule mod_evasive20.c>
    DOSHashTableSize    3097
    DOSPageCount        8         # max requests to same URI per interval
    DOSSiteCount        50        # max requests to whole site per interval
    DOSPageInterval     1         # interval (seconds)
    DOSSiteInterval     1
    DOSBlockingPeriod   300       # block IP for 5 minutes after threshold
    DOSLogDir           "/var/log/apache2/evasive"
</IfModule>
```

Pre-create the log dir:

```sh
sudo mkdir -p /var/log/apache2/evasive
sudo chown www-data:www-data /var/log/apache2/evasive
sudo systemctl reload apache2
```

This kills password-spraying through wssh: any IP that hammers `POST /`
with bad credentials gets a 403 wall for 5 minutes.

---

## 11. Smoke tests

```sh
# Security headers present
curl -sI https://wssh.app/ | grep -iE \
    '(strict-transport|content-security|x-content|x-frame|referrer|permissions)'

# XSRF cookie issued on the page load
curl -sI https://wssh.app/ -c /tmp/c.txt -o /dev/null && grep _xsrf /tmp/c.txt

# Audit log shows attempts (after a failed login from the UI)
sudo tail -f /var/log/wssh/audit.log

# Live application logs
journalctl -u wssh -f
```

Then load `https://wssh.app/` in a browser, try connecting. The audit log
should show one line per attempt:

```
2026-05-16 12:34:56 [audit] connect ip=1.2.3.4 target=example.com:22 user=root auth=password status=ok worker=12345
```

---

## 12. Updating

```sh
cd /opt/wssh
sudo -u wssh git pull
sudo .venv/bin/pip install .
sudo npm install
sudo npm run build
sudo chown -R wssh:wssh /opt/wssh
sudo systemctl restart wssh
```

---

## 13. Environment variables reference

| Variable | Default | Purpose |
|---|---|---|
| `WSSH_DEBUG` | `0` | If `1`, enables Tornado autoreload and emits Python tracebacks in HTTP responses. **Never enable in prod.** |
| `WSSH_COOKIE_SECRET` | random per-restart | HMAC key for XSRF tokens and signed cookies. Set to a stable hex string in prod (32 bytes recommended). |
| `WSSH_AUDIT_LOG` | stderr | Path to the rotating audit log. Leave unset to log to stderr (→ journald under systemd). |
| `WSSH_ALLOWED_ORIGINS` | same-origin only | Comma-separated extra origins permitted to open the WebSocket. Same-origin is always allowed. |
| `WSSH_ALLOW_PRIVATE_TARGETS` | `0` | If `1`, disables the SSRF check and allows SSH to RFC1918 / loopback / link-local. Use only for local dev with `mock_sshd.py`. |

---

## 14. What's protected

| Threat | Mitigation |
|---|---|
| Cross-Site WebSocket Hijacking | `check_origin` allowlist (same-origin + `WSSH_ALLOWED_ORIGINS`) |
| CSRF on `POST /` | Tornado XSRF tokens; client sends `X-XSRFToken` header |
| SSRF (cloud metadata, internal services) | Pre-connect resolver check rejects RFC1918 / loopback / link-local / multicast / reserved |
| Information disclosure via tracebacks | `debug=False` |
| Clickjacking | `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'` |
| MIME-sniff XSS | `X-Content-Type-Options: nosniff` |
| TLS downgrade | `Strict-Transport-Security` (HSTS) |
| Referrer leakage | `Referrer-Policy: no-referrer` |
| Power-API abuse | `Permissions-Policy: camera=(), microphone=(), geolocation=()` |
| Inline XSS / script injection | CSP locked to `'self'` (Alpine needs `'unsafe-eval'` for `x-*` expressions) |
| Brute force / password spraying | `mod_evasive` blocks aggressive IPs for 5 min |
| Crash dumps leaking key bytes | `RLIMIT_CORE = 0` |
| One session's bug exposing another's credentials | Per-session subprocess isolation (each `app.session_worker` runs in its own address space) |
| Runaway resource usage taking down the host | systemd `MemoryMax`/`MemoryHigh`/`CPUQuota`/`TasksMax`/`LimitNOFILE` |
| Kernel-level escalation primitives | `ProtectKernelTunables` / `ProtectKernelModules` / `ProtectControlGroups` / `LockPersonality` / `RestrictAddressFamilies` |
| Untraceable activity | Audit log of every connect attempt (without credentials) |

---

## 15. Troubleshooting

### `systemctl status wssh` shows `status=226/NAMESPACE`

systemd refused to set up the sandbox before the process started - namespace
setup fails *before* Python runs, so `journalctl -u wssh` is empty. Run
`journalctl -xeu wssh` to see the specific systemd-side error. Common causes
when you've added sandbox flags to the unit:

- A path in `ReadWritePaths=` that doesn't exist on disk.
- `ProtectHome=true` while the service user is something like `chris` whose
  `~/.ssh/known_hosts` paramiko then can't read (silent breakage rather
  than 226, but still confusing - leave `ProtectHome` out).
- `PrivateTmp=true` combined with anything that expects a shared `/tmp`.

Fix the offending line then:

```sh
sudo systemctl daemon-reload
sudo systemctl restart wssh
```

### Browser shows "Authentication failed"

Generic `paramiko.AuthenticationException`. Most common cause: the **target**
server has `PasswordAuthentication no` in `/etc/ssh/sshd_config` and you're
trying password auth. Verify with:

```sh
ssh -o PubkeyAuthentication=no -o PasswordAuthentication=yes user@target
```

Either upload the private key via the form or enable password auth on the
target.

### Browser console shows `403` on `POST /`

The `_xsrf` cookie wasn't issued (or wasn't sent back). Hard-refresh the
page (Ctrl-Shift-R) - the GET handler issues the cookie, then the JS reads
it and includes `X-XSRFToken` on the POST.

### Browser shows "Target host not allowed"

SSRF protection rejected the destination. The hostname resolved to a
private/loopback/link-local/multicast/reserved IP. For local dev with
`mock_sshd.py`, set `WSSH_ALLOW_PRIVATE_TARGETS=1`. **Don't set this in
prod.**

### WebSocket fails with "Could not decode a text frame as UTF-8"

Check that you're on the latest build - the worker should be using
`write_message(data, binary=True)` ([app/worker.py](../app/worker.py)). The
old text-frame mode breaks on multi-byte UTF-8 sequences split across
recv() boundaries (htop, vim, anything full-screen triggers it).

### `journalctl -u wssh` is silent

Likely a unit-level failure (sandbox setup) before Python starts. Try
`journalctl -xeu wssh` for the systemd-side error.

### Apache returns 502 Bad Gateway

The Tornado app isn't running, or isn't listening on `127.0.0.1:9001`.
Check `systemctl status wssh` and confirm the `ExecStart` line uses
`--address=127.0.0.1 --port=9001` (must match the `ProxyPass` target in
the vhost).
