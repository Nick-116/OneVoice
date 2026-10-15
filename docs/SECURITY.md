# Security guide

This page explains what is exposed, what protects it, and how to configure a reverse proxy so that **only the caption pages are reachable from the internet**. It uses Pangolin as the example, but the same allow-list works for any proxy.

## What can be reached, and what protects it

| Part | Who needs it | Protection inside OneVoice (independent of the proxy) |
|---|---|---|
| Caption site (port 8080) | Everyone with a phone | Read-only: only `GET`/`HEAD` accepted. No database access at all. Its Redis login can only read published captions and status. Rate and connection limits. Strict Content-Security-Policy. Captions are rendered as plain text. |
| Admin dashboard (port 8081) | Staff | Username + password (argon2id), mandatory authenticator code, session cookies that are `HttpOnly`/`Secure`/`SameSite=Strict`, CSRF tokens, login throttling, roles (admin/operator), audit log. |
| Audio input (port 8082) | The OneVoice Sender at church | Per-campus sender tokens (hashed, revocable instantly), optional IP allow-list per sender, frame-size and byte-rate limits, one connection per campus. Not needed at all when using **local audio input**. |
| Database, Redis, worker | Nobody | Internal Docker networks only, no published ports, a separate least-privilege login per service. |

Each part is a separate container on a separate port, so the proxy can expose them independently. **The usual setup: the caption site is public, the dashboard is private, and the audio input is restricted to the church.**

## Recommended Pangolin setup

Example domain: `translation.example.org`. Campus pages are at `/campus/<campus>` (that's also what the QR codes use).

### 1. Caption site: `translation.example.org` → target `public:8080`

Turn **authentication on** for the resource, then add these rules in priority order. Everything that doesn’t match an *Allow* rule hits the Pangolin login, so it is effectively blocked for the public.

| # | Match | Value | Action |
|---|---|---|---|
| 1 | Path | `/campus/*` | Allow (bypass auth) |
| 2 | Path | `/assets/*` | Allow |
| 3 | Path | `/api/public/*` | Allow |
| 4 | Path | `/branding/*` | Allow |
| 5 | Path | `/favicon.svg` | Allow |

All five are needed: the campus page loads its scripts and styles from `/assets/`, its live captions and status from `/api/public/`, and the church logo from `/branding/`. With only `/campus/*` allowed, phones get a blank page.

To hard-block instead of showing a login, add a last rule `Path` `/*` → **Drop**. The campus chooser at `/` is then unavailable, which is fine because the QR codes link straight to `/campus/<campus>`.

### 2. Admin dashboard: separate host, e.g. `onevoice-admin.example.org` → `admin:8081`

- Authentication **on** (Pangolin SSO), with access limited to staff accounts.
- Optionally add a rule `CIDR` `<church public IP>/32` → *Pass to Auth* (or *Allow*) so it only works from the church network.
- Even more private: don’t create a public resource at all. Reach it only over Pangolin’s client/VPN or on the local network.

Don’t put the dashboard under the caption hostname. A separate host keeps its cookies and rules completely separate.

### 3. Audio input (only if using the Sender app): e.g. `onevoice-audio.example.org` → `ingest:8082`

| # | Match | Value | Action |
|---|---|---|---|
| 1 | CIDR | `<church public IP>/32` | Allow |
| 2 | Path | `/*` | Drop |

Also set **Allowed CIDRs** on each sender in the dashboard, so a leaked token only works from the church. If every campus uses **local audio input**, skip this resource completely.

### 4. DNS (Cloudflare)

Point the hostnames at the Pangolin server.

- Keep the admin and audio records **DNS-only** (grey cloud) so IP rules see real client IPs.
- The caption site can be proxied (orange cloud) for extra DDoS absorption. If you do that, set `PUBLIC_TRUSTED_PROXY_HOPS=2` in `.env`.

## Is that enough?

**For the public caption site: yes.** The path rules are a second layer, not the only one. Even with no proxy rules, the caption service can’t change anything:

- it accepts only reads;
- it has no database credentials;
- it has no admin code;
- its Redis account can’t write captions or settings.

The worst a stranger can do there is read the captions, which are meant to be public anyway.

**What deserves the most care:**

1. **The admin dashboard.** It’s the only place settings can change. Keep it off the public internet (or behind Pangolin SSO), give every staff member their own account with a strong password, and keep two-factor on (it’s mandatory by default). Use the **operator** role for volunteers.
2. **Your GitHub account.** The Updates page installs whatever is on the repository’s `main` branch, so anyone who can push there can change your server. Turn on GitHub two-factor authentication.
3. **The server itself:**
   - SSH keys only, with password login turned off.
   - `ufw` allowing only SSH, plus automatic security updates.
   - Back up `secrets/` and the database off the server.
4. **API cost abuse (minor).** Translation runs for each language someone is reading during a service. Someone opening every language at once could make you pay for all of them, about $0.55 per language per service-hour on Azure. Mitigations:
   - Enable only the languages you need.
   - Watch **Usage & cost**.
   - Set a budget alert in Azure.
   - Nothing is translated outside service times.
5. **Privacy of what is said.** Everything in the speech mix goes to the speech and translation providers during services, so keep private conversations off that mix. See [PROVIDERS_AND_PRIVACY.md](PROVIDERS_AND_PRIVACY.md).

## Checking it from outside

From a phone on cellular data (not church Wi-Fi):

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://translation.example.org/campus/east-hartford   # 200
curl -s -o /dev/null -w "%{http_code}\n" https://translation.example.org/api/public/config       # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://translation.example.org/api/public/config  # 405 (read-only)
curl -s -o /dev/null -w "%{http_code}\n" https://translation.example.org/api/overview            # login/blocked (not 200)
curl -s -o /dev/null -w "%{http_code}\n" https://translation.example.org/healthz                 # login/blocked
```

Then open a campus page and confirm captions load. The browser’s developer console should show no blocked requests.

## Reporting a vulnerability

Please use GitHub’s **private vulnerability reporting** (Security tab → *Report a vulnerability*) rather than a public issue.
