# Security guide

This page explains what OneVoice exposes and what protects each part. Ports are listed in [Ports & addresses](PORTS.md).

## What can be reached, and what protects it

| Part | Who needs it | Protection inside OneVoice |
|---|---|---|
| Caption site (port 8080) | Everyone with a phone | Read-only: only `GET`/`HEAD` accepted. No database access at all. Its Redis login can only read published captions and status. Rate and connection limits. Strict Content-Security-Policy. Captions are rendered as plain text. |
| Admin dashboard (port 8081) | Staff | Username + password (argon2id), mandatory authenticator code, session cookies that are `HttpOnly`/`SameSite=Strict`, CSRF tokens, login throttling, roles (admin/operator), audit log. |
| Audio input (port 8082) | The OneVoice Sender at church | Per-campus sender tokens (hashed, revocable instantly), optional IP allow-list per sender, frame-size and byte-rate limits, one connection per campus. Not needed at all with **local audio input**. |
| Database, Redis, worker | Nobody | Internal Docker networks only, never published, a separate least-privilege login per service. |

Each part is a separate container on its own port and network, so you can expose them independently. **Typical setup: the caption site is public, the dashboard is private, and the audio input is limited to the church.**

## Keeping the dashboard and audio input private

- Set `ADMIN_BIND=127.0.0.1` if the dashboard should only open on the server itself.
- Set `INGEST_BIND=127.0.0.1` when every campus uses local audio input (no Sender app).
- Put guests on a Wi-Fi network separate from staff computers, if your router supports it.
- For each Sender, set **Allowed CIDRs** in the dashboard so its token only works from the church.

## Is that enough?

**For the public caption site: yes.** The caption service can’t change anything:

- it accepts only reads;
- it has no database credentials;
- it has no admin code;
- its Redis account can’t write captions or settings.

The worst a stranger can do there is read the captions, which are meant to be public anyway.

**What deserves the most care:**

1. **The admin dashboard.** It’s the only place settings can change. Keep it off the public internet, give every staff member their own account with a strong password, and keep two-factor on (it’s mandatory by default). Use the **operator** role for volunteers.
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

## Checking it

From another device on the network:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.1.20:8080/campus/main          # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://192.168.1.20:8080/api/public/config  # 405 (read-only)
curl -s -o /dev/null -w "%{http_code}\n" http://192.168.1.20:8080/api/overview         # 404 (no admin API here)
```

## Reporting a vulnerability

Please use GitHub’s **private vulnerability reporting** (Security tab → *Report a vulnerability*) rather than a public issue.
