# Ports & addresses

OneVoice is three small web services, each on its own port.

| Port | Service | Who needs it |
|---|---|---|
| **8080** | Caption site: `/campus/<campus>` | Phones in the congregation |
| **8081** | Admin dashboard | Staff |
| **8082** | Audio input for the OneVoice Sender app (WebSocket `/ingest/v1/stream`) | The Sender at church. Not needed with local audio input. |

## Addresses

With `192.168.1.20` as the server’s address on your network:

| What | Address |
|---|---|
| Caption page (what the QR codes open) | `http://192.168.1.20:8080/campus/<campus>` |
| Dashboard | `http://192.168.1.20:8081` |
| Sender app server address | `ws://192.168.1.20:8082/ingest/v1/stream` |

Give the server a fixed address in your router, so the QR codes keep working.

## Settings in `.env`

```
PUBLIC_BASE_URL=http://192.168.1.20:8080    # what the QR codes point to
ADMIN_ORIGIN=http://192.168.1.20:8081       # dashboard address as typed in the browser (comma-separate several)

PUBLIC_PORT=8080
ADMIN_PORT=8081
INGEST_PORT=8082

PUBLIC_BIND=0.0.0.0
ADMIN_BIND=0.0.0.0
INGEST_BIND=0.0.0.0
```

* **`*_PORT`** changes the port number on the server.
* **`*_BIND`** decides who can connect:
  - `0.0.0.0` means any device on the network;
  - `127.0.0.1` means only the server itself. For example, set `ADMIN_BIND=127.0.0.1` to open the dashboard only on the server.

Run `docker compose up -d` after changing `.env`.

Docker opens published ports past most firewalls on the server (including `ufw`). Use `*_BIND` to control who can reach each port.
