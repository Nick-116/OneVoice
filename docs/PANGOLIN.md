# Pangolin configuration

Your Pangolin server is already running, so this guide only covers connecting the VPS and defining the **three resources**. Exactly one of them is public.

```
                      Cloudflare DNS
                            │
                     Pangolin server (Traefik + Gerbil)
            ┌───────────────┼──────────────────────────┐
  captions.example.com   admin.example.com       audio.example.com
   PUBLIC, no auth        SSO + allow-list        church IPs only
            │               │                          │
            └────── WireGuard tunnel to Newt on the caption VPS ─────┘
                 public:8080       admin:8081         ingest:8082
```

## 1. Site (Newt)

1. Pangolin dashboard → **Sites → Add Site → Newt**. Name it e.g. `captions-vps`.
2. Copy the endpoint, ID and secret into `.env` on the VPS:
   ```
   PANGOLIN_ENDPOINT=https://pangolin.example.com
   NEWT_ID=...
   NEWT_SECRET=...
   ```
3. `docker compose up -d newt` and confirm the site shows **Online** in Pangolin.

The `newt` container is attached to three isolated networks (`public_edge`, `admin_edge`, `ingest_edge`), so it can reach those three targets by container name and nothing else. No port is published on the VPS itself.

> If you prefer to run Newt outside this compose project, delete the `newt` service and connect your Newt container to the three `captions_*_edge` networks with `docker network connect`.

## 2. Resources

Create three **HTTP resources** on the `captions-vps` site.

| Resource | Domain | Target (method / host / port) | Authentication |
|---|---|---|---|
| Public captions | `captions.example.com` | `http` / `public` / `8080` | **Disabled**: the only public resource |
| Admin | `admin.example.com` | `http` / `admin` / `8081` | **Enabled**: Pangolin SSO, restricted to staff users/roles |
| Audio ingest | `audio.example.com` | `http` / `ingest` / `8082` | **Enabled**, with the IP rules below |

Enable **SSL** on all three (Pangolin issues Let's Encrypt certificates).

### Public: `captions.example.com`
* Authentication: off ("Not protected"). This is intended.
* The app enforces read-only access itself:
  - Only `GET`/`HEAD` are accepted; everything else gets `405` before any routing.
  - The container has no database credentials.
  - Its Redis user can only read public keys.
  - It contains no admin routes.
* Optional hardening rules (Resource → Rules), in priority order:
  1. `Path` `/api/public/*` → **Allow**
  2. `Path` `/branding/*` → **Allow**
  3. `Path` `/assets/*` → **Allow**
  4. `Path` `/*` → **Allow** (the single-page app)

  You don't need any rules for safety; the app is already locked down.

### Admin: `admin.example.com`
* Authentication: **on**. Under Users & Roles, allow only your production staff.
* Turn on Pangolin 2FA for those accounts if your Pangolin supports it.
* Optional rule to make the dashboard reachable only from church networks (plus SSO from elsewhere):
  1. `CIDR` `<church public IP>/32` → **Pass to Auth**
* The app still requires its own login. Every staff member signs in with a username, password and TOTP code. Pangolin is an outer layer, not the only one.

### Audio ingest: `audio.example.com`
The desktop sender can't complete an SSO login, so lock this resource to your campuses' static IPs:
* Authentication: **on**.
* Rules (enable rules, in this priority order):
  1. `CIDR` `203.0.113.10/32` (East Hartford public IP) → **Allow** (bypasses SSO)
  2. `CIDR` `198.51.100.20/32` (East Windsor public IP) → **Allow**
  3. `Path` `/*` → **Drop**
* Anyone else gets nothing back. On top of that, the ingest service requires a per-campus sender token. Tokens are revocable and stored only as hashes. You can also set **Allowed CIDRs** on each sender in the admin dashboard, so a stolen token only works from that campus.
* WebSockets work through Pangolin without extra configuration.

## 3. Cloudflare DNS

| Record | Type | Target | Proxy |
|---|---|---|---|
| `captions` | A/CNAME | Pangolin server | DNS-only (grey) recommended; orange works too |
| `admin` | A/CNAME | Pangolin server | **DNS-only** |
| `audio` | A/CNAME | Pangolin server | **DNS-only** (otherwise Pangolin sees Cloudflare IPs and the IP allowlist fails) |

If you turn on Cloudflare proxying (orange cloud) for `captions`:
* Set `PUBLIC_TRUSTED_PROXY_HOPS=2` in `.env`, so rate limits use the real phone IP instead of Cloudflare's.
* SSE works through Cloudflare. The 15-second keepalive stays well under Cloudflare's 100-second idle timeout.

## 4. Verify

From a phone on cellular (outside the church):
```bash
curl -I https://captions.example.com/                       # 200
curl -X POST https://captions.example.com/api/public/config  # 405
curl -I https://captions.example.com/api/overview           # 404 (admin API does not exist here)
curl -I https://admin.example.com/                          # Pangolin login page / 302
curl -I https://audio.example.com/                          # connection dropped / 403 from outside church IPs
```
From the church: start the sender. The admin dashboard → Audio should show **Connected** within a few seconds.
