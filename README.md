<p align="center">
  <img src="docs/assets/onevoice-logo.svg" alt="OneVoice" width="420" />
</p>

<p align="center">
  <b>Live captions and translation for church services, on everyone’s phone.</b><br />
  Scan a QR code, pick a language, follow along. No app, no account.
</p>

<p align="center">
  <a href="https://github.com/Nick-116/OneVoice/actions/workflows/ci.yml"><img src="https://github.com/Nick-116/OneVoice/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/Nick-116/OneVoice/releases/latest"><img src="https://img.shields.io/github/v/release/Nick-116/OneVoice?label=sender%20app" alt="Latest release" /></a>
</p>

---

## Why OneVoice exists

OneVoice was designed for a church that wanted a **cheap, simple way to give live captions to members who speak other languages**. Hardware interpretation systems and human interpreters for every language are expensive. OneVoice instead uses the sound board’s speech mix, turns it into text, translates it, and shows it on people’s own phones in their language, live.

* **For the congregation:** scan the campus QR code, choose a language once (it’s remembered), read along. Text is large, adjustable and works in 12 languages out of the box, including right-to-left Arabic.
* **For the church:**
  - It runs on a small server (no GPU) and costs a few dollars of API usage per service.
  - A web dashboard handles service times, languages, campuses, branding and updates.

## How it works

```
 Sound board ──Dante / USB──► OneVoice Sender ──► OneVoice server ──► speech-to-text API ──► translation API
 (speech mix)                 (Mac or Windows        (Docker)              (Deepgram…)           (Azure…)
                               on the church network)     │
                                                          └──► phones in the room (live captions, per language)
```

**Our setup:**
- The OneVoice server runs on a **VPS** (a small cloud server).
- The **OneVoice Sender** app runs on a computer on the **church’s local network** and sends the speech mix to the VPS.
- Phones reach the caption site over the internet with HTTPS.

**Other setups work too:**

| Setup | When it fits |
|---|---|
| **VPS + Sender on the church network** (what we use) | Most reliable; phones can use cellular data or Wi-Fi; easy to reach from anywhere. |
| **Everything on one computer at the church** | No VPS cost. Run the server with Docker on the same Mac/PC as the Sender (or another machine on the network). |
| **Local network only, plain HTTP** | Simplest. Phones on the church Wi-Fi open `http://<server-ip>:8080/<campus>`. |
| **HTTPS through a reverse proxy** | Recommended whenever it’s reachable from the internet. Works behind Pangolin (guide included), Caddy, Nginx, Traefik or Cloudflare Tunnel. The public site, admin dashboard and audio input are separate ports, so each can be exposed (or not) independently. |

## Features

- **Live captions** in the original language (word-by-word) and **translated** captions per sentence, delivered with Server-Sent Events.
- **Scheduling:**
  - Weekly services, special and holiday services, cancellations.
  - Manual start, stop and extend, plus an early-access window.
  - A countdown before the service and a thank-you screen after.
  - Daylight-saving-time correct.
- **Honest status:** viewers see “Waiting for live captions…” or “The streaming service is currently not connected. Please check with the production team.” Captions never pretend to be live.
- **Multi-campus:** each campus has its own schedule, audio sender, languages, QR code and stream.
- **Pays only for what’s used:**
  - One translation per language, shared by every phone reading it.
  - A language is only translated while someone is reading it. When the last person switches away, it stops about 15 seconds later.
  - Nothing runs outside service times.
- **Branding:** church name, logo (PNG), button color and fonts (text and church name separately), all set in the dashboard. Colors are automatically adjusted for readable contrast.
- **First-run setup wizard:** create the first admin (protected by a one-time setup code), enable two-factor sign-in, choose and test the speech-to-text and translation providers.
- **One-click updates** from GitHub in the dashboard, with an automatic database backup and rollback.
- **Security:**
  - Only the caption site is meant to be public, and it’s read-only.
  - The admin dashboard requires a password plus an authenticator code.
  - Audio senders use revocable tokens and can be restricted by IP.
  - Containers run as non-root.
- **Monitoring:** live latency (p50/p95), viewers per language, audio levels, provider health, usage and estimated cost.

## Speech and translation providers (API usage)

OneVoice doesn’t run AI models itself. It uses **external speech-to-text and translation APIs**, which bill for usage: minutes of audio and characters translated. You create the accounts and paste the keys into the setup wizard. Keys are stored encrypted in your own database.

| | **Tested with** (what we use) | Also supported |
|---|---|---|
| Speech-to-text | **Deepgram** (Nova-3, streaming) | AssemblyAI (Universal-Streaming) |
| Translation | **Azure AI Translator** | Google Cloud Translation |
| Testing | Simulated providers (free, no keys) | |

**Typical cost:** 4 services a week of 1.5 hours each, with 3 translated languages:
- Deepgram: about **$12/month**
- Azure: about **$30–40/month**

**Credits for nonprofits and new accounts:**
- **Microsoft for Nonprofits:** eligible 501(c)(3)s can get **$2,000/year in Azure credits**, which covers translation entirely at this scale.
- **Deepgram:** new accounts get **$200 of free credit** (well over a year at the usage above). Deepgram doesn’t publish a nonprofit discount, but it’s worth asking their sales team.
- **Azure Translator** also has a free tier of 2 million characters per month.
- Prices and programs change, so check the providers’ current terms. See [docs/PROVIDERS_AND_PRIVACY.md](docs/PROVIDERS_AND_PRIVACY.md) for details and privacy notes.

The provider system is modular: a self-hosted speech or translation model can be added later as a single class.

## Downloads: OneVoice Sender (Mac and Windows)

Get the latest from **[Releases](https://github.com/Nick-116/OneVoice/releases/latest)**:

| File | For |
|---|---|
| `OneVoiceSender-…-macOS-AppleSilicon.dmg` | Macs with M-series chips |
| `OneVoiceSender-…-macOS-Intel.dmg` | Intel Macs |
| `OneVoiceSender-…-Windows-Setup.exe` | Windows 10/11 installer |
| `OneVoiceSender-…-Windows-Portable.zip` | Windows without installing |

The Sender captures one channel of an audio input, such as Dante Virtual Soundcard, a Dante AVIO USB adapter or any audio interface. It shows a live level meter and sends the audio to your OneVoice server. It reconnects automatically and can start when the computer boots.

**First launch:** the apps aren’t signed with paid Apple/Microsoft certificates yet, so your computer asks once:
- **macOS:** right-click the app → **Open** → **Open**.
- **Windows:** in the SmartScreen prompt, click **More info → Run anyway**.

The release pipeline signs and notarizes automatically once certificates are added; see [.github/workflows/release.yml](.github/workflows/release.yml).

## Quick start

You need Docker with the Compose plugin; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for a full Ubuntu VPS walkthrough.

```bash
git clone https://github.com/Nick-116/OneVoice.git onevoice && cd onevoice
./scripts/generate-secrets.sh           # random passwords and keys into ./secrets (never committed)
cp .env.example .env                     # set your addresses (see comments in the file)
docker compose up -d --build
docker compose logs admin | grep "setup code"
```

Open the admin dashboard and enter the setup code. The wizard walks you through:
1. creating the first admin;
2. setting up two-factor sign-in;
3. connecting Deepgram and Azure (or other providers).

Then add campuses, service times and a sender token, and print the QR codes.

* **On one computer / your local network:** `docker compose -f compose.yml -f compose.local.yml up -d --build` publishes the caption site on port 8080, the dashboard on 8081 and the audio input on 8082. Phones on the church Wi-Fi open `http://<computer-ip>:8080/<campus>`. The comments in [compose.local.yml](compose.local.yml) list the `.env` values to set (plain HTTP needs `COOKIE_SECURE=false`).
* **On a VPS behind a reverse proxy:** keep the ports private and point the proxy at the three services: public site `:8080`, admin `:8081`, audio `:8082`. [docs/PANGOLIN.md](docs/PANGOLIN.md) shows exactly which should be public and which private.

## Documentation

| | |
|---|---|
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Server sizing (no GPU) and step-by-step install |
| [PANGOLIN.md](docs/PANGOLIN.md) | Reverse proxy setup: what’s public, what’s private |
| [UPDATES.md](docs/UPDATES.md) | One-click updates from GitHub |
| [PROVIDERS_AND_PRIVACY.md](docs/PROVIDERS_AND_PRIVACY.md) | Providers, pricing, cost controls, privacy |
| [OPERATIONS.md](docs/OPERATIONS.md) | Monitoring, backups, troubleshooting |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) / [API.md](docs/API.md) | How it’s built |
| [TESTING.md](docs/TESTING.md) | Test suites, simulated mode, load testing |
| [PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md) | Before your first live service |
| [sender/README.md](sender/README.md) | Sender app, Dante setup, building from source |

## Privacy and what’s never in this repository

* **Audio:** sent to the speech provider only during scheduled services. It’s never recorded or stored.
* **Transcripts:** stored only if an admin turns that on for a campus.
* **Congregation:** no accounts, cookies or tracking.
* **Not in Git:** `.env`, `secrets/`, backups and updater state are in `.gitignore`. API keys, the church name and logo live in your database. A secret scanner runs on every push.

## License

OneVoice is released under the [MIT License](LICENSE). Fonts bundled with the caption site are under the SIL Open Font License.
