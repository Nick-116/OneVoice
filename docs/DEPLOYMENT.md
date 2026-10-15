# Installation

OneVoice runs with Docker Compose on any Linux server, Mac or Windows PC: a computer at the church, a mini-PC, or a VPS. It publishes three ports. Use them directly on your local network, or put a reverse proxy in front of them for HTTPS. Both setups are explained in [Ports & reverse proxy](REVERSE_PROXY.md).

| Port | What it serves | Who uses it |
|---|---|---|
| **8080** | Caption site (`/campus/<campus>`) | Phones in the congregation |
| **8081** | Admin dashboard | Staff |
| **8082** | Audio input for the OneVoice Sender app | The Sender at church (not needed with local audio input) |

## Hardware

**No GPU needed.** Speech recognition and translation run through external APIs, so the server only relays audio and text.

| | Minimum (2 campuses, 500 viewers) | Comfortable |
|---|---|---|
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB SSD | 80 GB SSD |
| Network | under 100 GB/month in practice | – |

Load per campus:

- about 256 kbps of audio in;
- about 1 KB/s of captions per phone out. 200 phones is about 1.6 Mbps.

For a VPS, a 2 vCPU / 4 GB plan (about $24/month at most providers) in a region near the church is plenty.

## 1. Install Docker

**Linux (Ubuntu/Debian):**

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl git unattended-upgrades
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in afterwards
```

**macOS / Windows:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Git.

## 2. Get OneVoice

```bash
sudo mkdir -p /opt/onevoice && sudo chown "$USER" /opt/onevoice
git clone https://github.com/Nick-116/OneVoice.git /opt/onevoice
cd /opt/onevoice
./scripts/generate-secrets.sh          # random database/Redis passwords and app secret in ./secrets
cp .env.example .env
```

On macOS/Windows, any folder works; run the same commands from it.

## 3. Edit `.env`

The defaults work for a quick test on the same computer (`http://localhost:8080`, `http://localhost:8081`). For real use, set these:

| Setting | Local setup (church network) | Reverse proxy setup (HTTPS) |
|---|---|---|
| `PUBLIC_BASE_URL` | `http://192.168.1.20:8080` | `https://captions.example.org` |
| `ADMIN_ORIGIN` | `http://192.168.1.20:8081` | `https://admin.example.org` |
| `PUBLIC_BIND` / `ADMIN_BIND` / `INGEST_BIND` | `0.0.0.0` | `127.0.0.1` (or see [Docker proxies](REVERSE_PROXY.md#proxy-running-in-docker)) |
| `TRUSTED_PROXY_HOPS` | `0` | `1` |
| `COOKIE_SECURE` | `false` | `true` |

`192.168.1.20` stands for the server's address on your network. `PUBLIC_BASE_URL` is what the QR codes point to. `ADMIN_ORIGIN` must exactly match how you type the dashboard address in the browser, and can list several addresses separated by commas.

## 4. Start

```bash
docker compose up -d --build
docker compose ps                  # everything "healthy"; migrate "exited (0)"
```

The first build takes a few minutes. All OneVoice images are built on your machine from this repository; nothing is downloaded except standard images like PostgreSQL and Redis.

## 5. First-run setup

```bash
docker compose logs admin | grep "setup code"
```

Open the dashboard (port 8081) and follow the setup wizard:

1. Enter the **setup code** and create the first administrator.
2. Scan the QR code with an authenticator app (two-factor sign-in).
3. Enter the church name.
4. Choose and test the speech-to-text provider (Deepgram) and the translator (Azure).

The setup code only works while no administrator exists, so nobody else can claim a fresh install. A command-line fallback exists: `docker compose run --rm admin python -m captions.admin.cli create-user --username NAME --role admin`.

## 6. Configure

1. **Branding:** church name, logo (PNG), button color and fonts.
2. **Campuses:** create each campus. Its page is `<PUBLIC_BASE_URL>/campus/<slug>`.
   - Choose the languages.
   - Choose the **audio source**: a local input on this server, or the Sender app (see [Audio input](AUDIO.md)).
3. **Services:** add the weekly service times. The default time zone is America/New_York.
4. **Audio → Senders** (only for campuses using the Sender app): create a sender and paste its token into the OneVoice Sender.
5. **QR codes:** print one per campus. The addresses never change between services.
6. **Providers & Settings:** add Deepgram keyterms such as the church name, pastors’ names, local places and Bible book names.

## 7. Firewall

Docker opens published ports past most host firewalls (including `ufw`). So decide with `*_BIND` who can reach each port:

| Setup | Port 8080 (captions) | Port 8081 (admin) | Port 8082 (audio) |
|---|---|---|---|
| Local network | `0.0.0.0`: phones on the Wi-Fi | `0.0.0.0` or `127.0.0.1` (dashboard only on the server itself) | `0.0.0.0` if a Sender on another computer uses it |
| Reverse proxy on the same server | `127.0.0.1` | `127.0.0.1` | `127.0.0.1` |

On a VPS, keep SSH as the only directly open port. Let the reverse proxy be the only thing listening on 80/443.

## 8. Updates

Install the updater so the dashboard’s **Updates** page can install new versions from GitHub. See [Updates](UPDATES.md).

```bash
sudo cp deploy/updater/onevoice-updater.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now onevoice-updater
```

## 9. Test before Sunday

* Dashboard → Live overview → **Start service now**.
* Start the audio: local input, the Sender app, or the simulator below.
* Scan the QR code with a phone and pick a language. Captions should appear within a few seconds.
* **Stop service.** Phones should show “Today’s service has ended”.

To test without church audio, choose the **simulated** providers in the dashboard, create a sender, and run:

```bash
pip install websockets==13.1
python tools/simulate_sender.py --url ws://localhost:8082/ingest/v1/stream --token cs_...
```
