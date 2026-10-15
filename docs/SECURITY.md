# Security guide

This page explains what OneVoice exposes, what protects each part, and how to keep everything except the caption pages private. Port and proxy details are in [Ports & reverse proxy](REVERSE_PROXY.md).

## What can be reached, and what protects it

| Part | Who needs it | Protection inside OneVoice (works with or without a proxy) |
|---|---|---|
| Caption site (port 8080) | Everyone with a phone | Read-only: only `GET`/`HEAD` accepted. No database access at all. Its Redis login can only read published captions and status. Rate and connection limits. Strict Content-Security-Policy. Captions are rendered as plain text. |
| Admin dashboard (port 8081) | Staff | Username + password (argon2id), mandatory authenticator code, session cookies that are `HttpOnly`/`SameSite=Strict` (`Secure` with HTTPS), CSRF tokens, login throttling, roles (admin/operator), audit log. |
| Audio input (port 8082) | The OneVoice Sender at church | Per-campus sender tokens (hashed, revocable instantly), optional IP allow-list per sender, frame-size and byte-rate limits, one connection per campus. Not needed at all with **local audio input**. |
| Database, Redis, worker | Nobody | Internal Docker networks only, never published, a separate least-privilege login per service. |

Each part is a separate container on its own port and network, so you can expose them independently. **Typical setup: the caption site is public, the dashboard is private, and the audio input is limited to the church.**

## Keeping everything but the caption pages private

**Local setup:**

- Expose only what the church network needs.
- Set `ADMIN_BIND=127.0.0.1` if the dashboard should only open on the server itself.
- Put guests on a Wi-Fi network separate from staff computers, if your router supports it.

**Reverse proxy setup:**

- Bind all three ports to `127.0.0.1` (or don’t publish them; see the [Docker proxy](REVERSE_PROXY.md#proxy-running-in-docker) option).
- On the caption hostname, allow only `/campus/*`, `/assets/*`, `/api/public/*`, `/branding/*` and `/favicon.svg`. Block everything else, or require the proxy’s login for it.
- Put the dashboard on a **separate hostname**, behind the proxy’s login/SSO or reachable only from the church network or a VPN.
- If you use the Sender app, allow the audio hostname only from the church’s public IP. Also set **Allowed CIDRs** on each sender in the dashboard, so a leaked token only works from the church.

## Is that enough?

**For the public caption site: yes.** Proxy rules are a second layer, not the only one. Even with no proxy at all, the caption service can’t change anything:

- it accepts only reads;
- it has no database credentials;
- it has no admin code;
- its Redis account can’t write captions or settings.

The worst a stranger can do there is read the captions, which are meant to be public anyway.

**What deserves the most care:**

1. **The admin dashboard.** It’s the only place settings can change. Keep it off the public internet (or behind a proxy login), give every staff member their own account with a strong password, and keep two-factor on (it’s mandatory by default). Use the **operator** role for volunteers.
2. **Your GitHub account,** if you use the Updates page. It installs whatever is on the repository’s `main` branch, so anyone who can push there can change your server. Turn on GitHub two-factor authentication.
3. **The server itself:**
   - Keep the OS updated.
   - Use SSH keys only.
   - Open only the ports you need. Docker-published ports bypass `ufw`, so use the `*_BIND` settings.
   - Back up `secrets/` and the database to another machine.
4. **API cost abuse (minor).** Translation runs for each language someone is reading during a service. Someone opening every language at once could make you pay for all of them, about $0.55 per language per service-hour on Azure. Mitigations:
   - Enable only the languages you need.
   - Watch **Usage & cost**.
   - Set a budget alert with your provider.
   - Nothing is translated outside service times.
5. **Privacy of what is said.** Everything in the speech mix goes to the speech and translation providers during services, so keep private conversations off that mix. See [Providers, cost & privacy](PROVIDERS_AND_PRIVACY.md).

## Checking it from outside

From a phone on cellular data (not church Wi-Fi), with your caption hostname:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://captions.example.org/campus/main          # 200
curl -s -o /dev/null -w "%{http_code}\n" https://captions.example.org/api/public/config    # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://captions.example.org/api/public/config  # 405 (read-only)
curl -s -o /dev/null -w "%{http_code}\n" https://captions.example.org/api/overview         # blocked (not 200)
curl -s -o /dev/null -w "%{http_code}\n" https://captions.example.org/healthz              # blocked (not 200)
```

Then open a campus page and confirm captions load. The browser’s developer console should show no blocked requests.

## Reporting a vulnerability

Please use GitHub’s **private vulnerability reporting** (Security tab → *Report a vulnerability*) rather than a public issue.
