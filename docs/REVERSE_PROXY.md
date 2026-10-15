# Ports & reverse proxy

OneVoice is three small web services on three ports. Nothing else needs to be reachable.

| Port | Service | Paths | Who needs it |
|---|---|---|---|
| **8080** | Caption site | `/campus/<campus>` plus the page’s own files | Everyone with a phone |
| **8081** | Admin dashboard | everything | Staff only |
| **8082** | Audio input (WebSocket `/ingest/v1/stream`) | everything | The OneVoice Sender at church, if used |

Ports can be changed with `PUBLIC_PORT`, `ADMIN_PORT` and `INGEST_PORT` in `.env`. Who can reach them is set with `PUBLIC_BIND`, `ADMIN_BIND` and `INGEST_BIND`.

There are two ways to run it.

---

## Local setup (church network, no HTTPS)

The simplest option: OneVoice runs on a computer at the church and phones connect over the church Wi-Fi.

`.env` (with `192.168.1.20` as the server's address on your network):

```
PUBLIC_BASE_URL=http://192.168.1.20:8080
ADMIN_ORIGIN=http://192.168.1.20:8081
PUBLIC_BIND=0.0.0.0
ADMIN_BIND=0.0.0.0        # or 127.0.0.1 to allow the dashboard only on the server itself
INGEST_BIND=0.0.0.0
TRUSTED_PROXY_HOPS=0
COOKIE_SECURE=false
```

Addresses:

| What | Address |
|---|---|
| Caption page (QR codes) | `http://192.168.1.20:8080/campus/<campus>` |
| Dashboard | `http://192.168.1.20:8081` |
| Sender app server address | `ws://192.168.1.20:8082/ingest/v1/stream` |

Give the server a fixed address in your router, so the QR codes keep working. Phones must be on the church Wi-Fi.

---

## Reverse proxy setup (HTTPS)

Use this when phones should reach OneVoice from anywhere (including cellular data), or when it runs on a VPS. A reverse proxy handles HTTPS and forwards to OneVoice. Pangolin, Caddy, Nginx, Traefik, Nginx Proxy Manager and Cloudflare Tunnel all work.

### Proxy on the same machine (installed normally, not in Docker)

Bind OneVoice to the server only, so the ports can’t be reached from outside, and point the proxy at `127.0.0.1`:

```
PUBLIC_BIND=127.0.0.1
ADMIN_BIND=127.0.0.1
INGEST_BIND=127.0.0.1
PUBLIC_BASE_URL=https://captions.example.org
ADMIN_ORIGIN=https://admin.example.org
TRUSTED_PROXY_HOPS=1
COOKIE_SECURE=true
```

| Hostname (example) | Forward to |
|---|---|
| `captions.example.org` | `http://127.0.0.1:8080` |
| `admin.example.org` | `http://127.0.0.1:8081` |
| `audio.example.org` (only if using the Sender app) | `http://127.0.0.1:8082` (WebSocket) |

### Proxy running in Docker

Inside a container, `127.0.0.1` means that container itself, not the server. So a Docker-based proxy (or a tunnel connector such as Pangolin’s Newt or `cloudflared` running as a container) can reach OneVoice in one of two ways:

1. **Join OneVoice’s networks and use the service names** (recommended):

   ```bash
   docker network connect captions_public_net <proxy-container>
   docker network connect captions_admin_net  <proxy-container>
   docker network connect captions_ingest_net <proxy-container>   # only if using the Sender app
   ```

   | Hostname | Forward to |
   |---|---|
   | `captions.example.org` | `http://public:8080` |
   | `admin.example.org` | `http://admin:8081` |
   | `audio.example.org` | `http://ingest:8082` |

   The ports don’t need to be published at all in this case. Set the three `*_BIND` values to `127.0.0.1` so nothing is exposed directly.

2. **Forward to the server’s address:** `http://host.docker.internal:8080` (Docker Desktop, or Linux with `extra_hosts: ["host.docker.internal:host-gateway"]` on the proxy). The `*_BIND` values must then be `0.0.0.0`, so protect those ports with a firewall.

Docker names the networks after the Compose project `captions`, hence `captions_public_net` and so on. Check with `docker network ls`.

### What to make public

Only the caption pages need to be public. Configure the proxy so the caption hostname allows just these paths:

| Path | Why the caption page needs it |
|---|---|
| `/campus/*` | the campus pages (what QR codes open) |
| `/assets/*` | the page’s scripts and styles |
| `/api/public/*` | live captions and service status |
| `/branding/*` | the church logo |
| `/favicon.svg` | browser tab icon |

Allowing only `/campus/*` breaks the page: it loads blank. Everything else on that hostname can be blocked or put behind the proxy’s login. The service is read-only either way; see [Security](SECURITY.md).

- **Admin hostname:** keep it behind the proxy’s own login/SSO, or don’t publish it at all and use the dashboard only on the local network.
- **Audio hostname:** only needed for the Sender app. Allow only the church’s public IP address.

### Proxy settings to check

- **Live captions use Server-Sent Events:** turn response buffering off for the caption host (Nginx: `proxy_buffering off;`), and allow long-lived connections (read timeout of at least 60 s; OneVoice sends a keep-alive every 15 s).
- **The audio input uses WebSockets:** the proxy must pass `Upgrade`/`Connection` headers. Most proxies do this automatically.
- **Client IP:** the proxy should send `X-Forwarded-For`. Set `TRUSTED_PROXY_HOPS` to the number of proxies in front: `1` for one proxy, `2` if a CDN such as Cloudflare sits in front of it.

**Caddy example**, with automatic HTTPS:

```
captions.example.org {
    @public path /campus/* /assets/* /api/public/* /branding/* /favicon.svg
    handle @public {
        reverse_proxy 127.0.0.1:8080 {
            flush_interval -1
        }
    }
    respond 404
}
admin.example.org {
    reverse_proxy 127.0.0.1:8081
}
```

**Nginx example** (caption host):

```
location ~ ^/(campus/|assets/|api/public/|branding/|favicon\.svg$) {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_read_timeout 1h;
}
location / { return 404; }
```
