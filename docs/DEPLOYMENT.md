# Deployment (clean Ubuntu VPS)

## VPS sizing

**No GPU needed.** Speech recognition and translation run through external APIs. The VPS only relays audio and text.

| | Minimum (fine for 2 campuses, 500 viewers) | Comfortable headroom |
|---|---|---|
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB SSD | 80 GB NVMe |
| Bandwidth | <100 GB/month in practice | – |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |

The New York / New Jersey regions of DigitalOcean (NYC3), Vultr (New Jersey) or Akamai/Linode (Newark) are all about 5–10 ms from Connecticut. The 2 vCPU / 4 GB tier costs roughly $24/month. Pangolin runs elsewhere, so this VPS hosts only the caption stack and Newt.

Load per campus: about 256 kbps of audio in, and about 1 KB/s of captions per viewer out. 200 viewers is about 1.6 Mbps.

## 1. Prepare the server

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ca-certificates curl git ufw unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# Firewall: only SSH inbound. Newt makes an OUTBOUND tunnel to Pangolin; no web ports are opened here.
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw enable

# Docker Engine + Compose plugin (official repository)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in afterwards
```

Docker can bypass ufw for *published* ports. This stack publishes **none**, so that doesn't apply here. `docker compose ps` should show no `0.0.0.0:` port mappings.

## 2. Install the application

```bash
sudo mkdir -p /opt/church-captions && sudo chown "$USER" /opt/church-captions
git clone https://github.com/Nick-116/OneVoice.git /opt/church-captions
cd /opt/church-captions

./scripts/generate-secrets.sh          # creates ./secrets/* (random DB/Redis passwords, app secret)
cp .env.example .env && nano .env      # set domains + Newt credentials
```

Optionally put provider keys in `secrets/deepgram_api_key` and `secrets/azure_translator_key`, or enter them later in the dashboard, where they are stored encrypted.

## 3. Build and start

```bash
APP_COMMIT=$(git rev-parse HEAD) docker compose build
docker compose up -d
docker compose ps        # all services "healthy"; migrate "exited (0)"
```

## 4. Create the first administrator

```bash
docker compose run --rm admin python -m captions.admin.cli create-user --username yourname --role admin
```

Then:
1. Open `https://admin.example.com`. Pangolin SSO comes first, then the app login.
2. Scan the QR code with an authenticator app to enrol MFA.

## 5. Configure in the dashboard

1. **Branding:** church name, button color and logo (PNG). Phones pick changes up within a minute.
2. **Providers & Settings:**
   - Choose Deepgram + Azure, paste the keys and set the Azure region.
   - Set the public base URL, e.g. `https://captions.example.com`.
   - Add Deepgram keyterms such as the church name, pastors' names, local towns and scripture book names.
3. **Campuses:** create each campus. The slug becomes the URL, e.g. `east-hartford` → `https://captions.example.com/east-hartford`. Choose its languages.
4. **Services:** add the recurring services (e.g. Sunday 9:00–10:30, 11:00–12:30; Wednesday 19:00–20:30). Default timezone is America/New_York.
5. **Audio → Senders:**
   - Create one sender per campus and add the campus's public IP under *Allowed CIDRs*.
   - Copy the token, which is shown once, into the church computer's sender app.
6. **QR codes:** download or print per campus. The URLs never change between services.

## 6. Updates

Install the host updater so the dashboard's **Updates** page can install new versions from GitHub. See [UPDATES.md](UPDATES.md).

```bash
sudo cp deploy/updater/onevoice-updater.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now onevoice-updater
```

## 7. Pangolin

Follow [PANGOLIN.md](PANGOLIN.md): one public resource, two private ones.

## 8. Test before Sunday

* Admin → Overview → **Start service now** (15 min).
* Start the sender at the church, or simulate one (below).
* Scan the QR code with a phone and pick Spanish. Captions should appear. Check that the latency numbers on the Overview are sensible.
* **Stop service.** Phones should show the "service has ended" message.

To simulate without the church computer, run this from any machine that can reach `audio.example.com`:
```bash
pip install websockets==13.1
python tools/simulate_sender.py --url wss://audio.example.com/ingest/v1/stream --token cs_... --wav sermon.wav
```
(Simulating from outside church needs a temporary IP rule in Pangolin and on the sender.)

## Local development (laptop)

```bash
./scripts/generate-secrets.sh
cat > .env <<'EOF'
PUBLIC_BASE_URL=http://localhost:8080
ADMIN_ORIGIN=http://localhost:8081
PANGOLIN_ENDPOINT=https://unused.invalid
NEWT_ID=unused
NEWT_SECRET=unused
COOKIE_SECURE=false
TRUSTED_PROXY_HOPS=0
PUBLIC_TRUSTED_PROXY_HOPS=0
EOF
docker compose -f compose.yml -f compose.dev.yml up -d --build postgres redis migrate worker ingest public admin
```

`compose.dev.yml` publishes the three app ports on 127.0.0.1 only (for development, never in production). Select the `simulated` providers in the dashboard, create a campus and a sender, then run `python tools/simulate_sender.py --token ...`.
