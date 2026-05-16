# wssh - production deployment guide

Step-by-step for deploying wssh behind Apache with TLS, the hardened systemd
unit, the Tier 1 security configuration, and rate limiting at the edge.

Targeted at Ubuntu 22.04 / Debian 12. Adjust paths for other distros.

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

Apache terminates TLS, proxies everything to the Tornado app on
`127.0.0.1:9001`. `/ws` goes through `mod_proxy_wstunnel`; everything else
through `mod_proxy_http`. Tornado serves the built static bundle from
`/var/www/wssh/public/`.

---

## 2. Prerequisites

- A domain (e.g. `wssh.app`) with an A/AAAA record pointing at the server.
- Ubuntu 22.04+ / Debian 12+ with root or sudo.
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
sudo git clone https://github.com/sentrychris/wssh.git /var/www/wssh
cd /var/www/wssh

sudo python3 -m venv .venv
sudo .venv/bin/pip install .

sudo npm install
sudo npm run build

sudo chown -R wssh:wssh /var/www/wssh
```

The build produces `/var/www/wssh/public/{index.html,js,css,img}` - Tornado's
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

File: `/etc/systemd/system/wssh.service`

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
Environment=WSSH_COOKIE_SECRET=<paste output of `python -c "import secrets; print(secrets.token_hex(32))"`>
Environment=WSSH_AUDIT_LOG=/var/log/wssh/audit.log
Environment=WSSH_ALLOWED_ORIGINS=https://wssh.app
WorkingDirectory=/opt/wssh
ExecStart=/opt/wssh/.venv/bin/python /opt/wssh/ssh.py --address=127.0.0.1 --port=9001
Restart=on-failure
RestartSec=5

ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

> **`ReadWritePaths` must list every directory the process writes to.** If you
> change the install dir or move the audit log, update this line - otherwise
> systemd fails namespace setup with `status=226/NAMESPACE` *before* the
> Python process even starts (and `journalctl -u wssh` looks empty; use
> `journalctl -xeu wssh` to see the namespace error).

Enable and start:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now wssh
sudo systemctl status wssh
journalctl -u wssh -f
```

---

## 8. TLS certificate

Issue a Let's Encrypt cert via certbot:

```sh
sudo certbot --apache -d wssh.app
```

Certbot will offer to write the redirect block automatically. If you'd rather
manage the vhost yourself, use `certbot --apache --certonly -d wssh.app` and
point the vhost at `/etc/letsencrypt/live/wssh.app/fullchain.pem` and
`privkey.pem`.

Auto-renewal is installed by the certbot package; verify with:

```sh
sudo systemctl list-timers | grep certbot
```

---

## 9. Apache vhost

File: `/etc/apache2/sites-available/wssh.conf`

```apache
<VirtualHost *:80>
    ServerName wssh.app
    Redirect permanent / https://wssh.app/
</VirtualHost>

<VirtualHost *:443>
    ServerName wssh.app

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/wssh.app/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/wssh.app/privkey.pem

    ProxyRequests Off
    ProxyPreserveHost On

    # WebSocket - must come BEFORE the catch-all
    ProxyPass        /ws ws://127.0.0.1:9001/ws
    ProxyPassReverse /ws ws://127.0.0.1:9001/ws

    # Everything else (HTML, CSS, JS, SVG, POST /)
    ProxyPass        / http://127.0.0.1:9001/
    ProxyPassReverse / http://127.0.0.1:9001/

    RequestHeader set X-Forwarded-Proto "https"

    ErrorLog  ${APACHE_LOG_DIR}/wssh_error.log
    CustomLog ${APACHE_LOG_DIR}/wssh_access.log combined
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
    DOSEmailNotify      you@wssh.app
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
cd /var/www/wssh
sudo -u wssh git pull
sudo .venv/bin/pip install .
sudo npm install
sudo npm run build
sudo chown -R wssh:wssh /var/www/wssh
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

## 14. What's protected (Tier 1 summary)

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
| Filesystem writes from compromised process | `ProtectSystem=strict` + narrow `ReadWritePaths` |
| Process privilege escalation | `NoNewPrivileges`, dedicated `wssh` user, sandbox flags |
| Untraceable activity | Audit log of every connect attempt (without credentials) |

---

## 15. Troubleshooting

### `systemctl status wssh` shows `status=226/NAMESPACE`

systemd refused to set up the sandbox before the process started. The
process never ran, so `journalctl -u wssh` is empty. Run
`journalctl -xeu wssh` to see the actual namespace error - almost always a
path in `ReadWritePaths` that doesn't exist. Fix it, then:

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
