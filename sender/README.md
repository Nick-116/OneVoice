# Church Audio Sender

A small desktop app for macOS and Windows. It takes the speech mix from the Yamaha console over Dante, sends it to the caption server, and shows you the input level and the connection state.

```
Yamaha console ──Dante──▶ church computer ──▶ Church Audio Sender ──WSS──▶ audio.example.com/ingest/v1/stream
                          (Dante Virtual Soundcard
                           or Dante AVIO USB adapter)
```

The app records **one channel** of the input device you pick. It resamples that channel to 16 kHz (24 or 48 kHz if you choose), converts it to 16-bit PCM and sends a 100 ms frame over a TLS WebSocket. While the server says a service is **live**, the audio goes on to transcription. Outside a service window the server uses it only for the level meter in the admin dashboard.

---

## 1. Install from source

You need Python **3.11 or newer**, from python.org or the Microsoft Store. On macOS, use the python.org installer because it includes Tk.

```bash
cd sender
python3 -m venv .venv
# macOS:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m church_sender            # GUI
python -m church_sender --list-devices
```

The `sounddevice` wheels for macOS and Windows include PortAudio, so nothing else needs installing. On Linux, which is useful for development only, install `libportaudio2` and `python3-tk`.

## 2. First-time setup

1. In the **admin dashboard → Audio senders**, create a sender for the campus and copy the token (`cs_…`). The dashboard shows it only once. If the sender has an IP allowlist, it must include the church's public IP.
2. Start the app and fill in the following:
   * **Server URL**: `wss://audio.example.com/ingest/v1/stream`
   * **Sender token**: paste the token. The app stores it in the macOS Keychain or the Windows Credential Manager, never in the config file.
   * **Extra headers** (optional): headers the reverse proxy may require, such as Pangolin resource access-token headers. Their values also go into the keychain.
   * **Input device** and **Input channel**: see section 3.
   * **Send sample rate**: 16000 is the default and is all speech recognition needs.
   * **Input gain**: a trim from −20 to +20 dB. Aim for speech peaks around −12 to −6 dBFS that never light the **CLIP** indicator.
3. Click **Test input** and confirm the meter moves while someone talks.
4. Click **Save settings**, then **Start streaming**.
5. Tick **Start streaming automatically when the app opens** and **Launch at login**. The computer then streams unattended after a reboot.

Settings are stored in a JSON file in the platform config folder:
* macOS: `~/Library/Application Support/ChurchCaptionsSender/config.json`
* Windows: `%LOCALAPPDATA%\ChurchCaptions\ChurchCaptionsSender\config.json`

## 3. Dante setup

### Option A: Dante Virtual Soundcard (DVS)

1. Install and license DVS on the church computer, then start it.
   * **Windows**: choose **ASIO** for the lowest CPU use with many channels, or **WDM** to use WASAPI.
   * **macOS**: DVS shows up as a Core Audio device.
2. Open **Dante Controller** → **Routing**. Find the Yamaha console (for example `CL5-xxxx` or `QL1-xxxx`) under *Dante Transmitters* and the computer under *Dante Receivers*.
3. Subscribe the console output that carries the **speech mix** to a DVS receive channel, for example console *Mix 16* → computer channel *01*. Wait for the green tick.
   * On the console, patch the speech mix (pastor's mic plus any lectern or presenter mics, without music) to a Dante output. Use a **pre-fader** (or dedicated) mix so that a FOH fader move doesn't change caption quality.
4. In the app, choose the DVS device and the **channel number you subscribed to** (channel *01* in the example).
5. In DVS / Dante Controller, set the sample rate to match the console, normally 48 kHz. The app resamples automatically.

### Option B: Dante AVIO USB adapter

The AVIO USB adapter appears as a normal two-channel USB audio device ("Dante AVIO USB…"). Route the speech mix to AVIO channel 1 (or 2) in Dante Controller, then choose that device and channel in the app. No DVS licence is needed.

## 4. Platform notes

### macOS: microphone permission

macOS treats any audio input, Dante included, as the "microphone". The first time you click **Test input** or **Start streaming**, macOS asks for permission. Click **Allow**.

* If you clicked *Don't Allow*, the meter shows **digital silence**. Fix it in **System Settings → Privacy & Security → Microphone** by enabling *Church Audio Sender*, or *Terminal* / *Python* when running from source. Then restart the app.
* The bundled `.app` contains the required `NSMicrophoneUsageDescription`.

### Windows: host APIs

The device list shows each device once per host API. The host API is shown in brackets.

* **ASIO** (DVS in ASIO mode): the app opens only the selected channel. This is best with 64 channels. The `sounddevice` wheel's PortAudio includes ASIO **only if it was built with it**. If no ASIO devices are listed, switch DVS to **WDM** mode and use WASAPI.
* **Windows WASAPI**: recommended for WDM / AVIO USB. The app opens the device at its shared-mode rate (set it in *Sound settings → Device properties → Advanced*, normally 48000 Hz).
* **MME / DirectSound**: avoid these. They may resample or limit the channel count.
* Turn off "audio enhancements" and "allow applications to take exclusive control" for the device if levels look wrong.

## 5. Building the app bundles (PyInstaller)

Build on each target OS, because PyInstaller does not cross-compile:

```bash
pip install -r requirements-dev.txt
python build.py                 # or: pyinstaller --noconfirm --clean sender.spec
```

* **macOS** → `dist/Church Audio Sender.app`. Copy it to `/Applications`. For distribution beyond your own computers, sign and notarise it (`codesign --deep --options runtime -s "Developer ID Application: …"`, then `xcrun notarytool submit`). Otherwise, right-click → **Open** the first time to get past Gatekeeper.
* **Windows** → `dist\ChurchAudioSender\` containing `ChurchAudioSender.exe` (the GUI, no console) and `ChurchAudioSender-cli.exe` (a console build for `--headless` and `--list-devices`). Copy the folder to `C:\Program Files\ChurchAudioSender\`.

## 6. Headless / service use

```bash
python -m church_sender --list-devices      # find the device name / channels
python -m church_sender --headless          # uses the saved settings, logs to file + stdout
```

Configure the app once in the GUI on the same user account. The token is read from that user's keychain or Credential Manager. Headless mode waits for the audio device if it is not present yet, which helps when DVS starts after login. It reconnects forever and exits with code 3 if the sender is revoked.

* **macOS**: the **Launch at login** checkbox writes `~/Library/LaunchAgents/church.captions.sender.plist`, which starts the GUI minimised. To run headless at login instead, edit `ProgramArguments` in that plist to end with `--headless`. It must stay a *LaunchAgent* in the user session (not a system LaunchDaemon) because the keychain and the microphone permission are per user.
* **Windows**: the checkbox adds a `ChurchCaptionsSender` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. For headless at logon, point a Task Scheduler task ("At log on", "Run only when user is logged on") at `ChurchAudioSender-cli.exe --headless`. Configure Windows to auto-login the streaming account.

Logs (rotating, 5 × 2 MB). The token is never written, and anything token-shaped is redacted:
* macOS: `~/Library/Logs/ChurchCaptionsSender/sender.log`
* Windows: `%LOCALAPPDATA%\ChurchCaptions\ChurchCaptionsSender\Logs\sender.log`

## 7. How the link behaves

* The app keeps one persistent WebSocket open. It reconnects with exponential backoff from 1 s to 30 s with jitter, and the backoff resets after one stable minute.
* The server sends a status frame every 2 s. If none arrives for 10 s, the app treats the link as dead and reconnects.
* Audio is buffered for at most 2 s, and the oldest audio is dropped when the buffer is full. On reconnect, anything older than 1 s is discarded, so live audio always takes priority over backlog.
* Server responses and close codes:

  | Server response | App shows | App does |
  |---|---|---|
  | HTTP 403 / close 1008 | *Authentication failed — check token / IP allowlist* | retries every 60 s |
  | close 4009 | warning *Replaced by another sender…* | reconnects with backoff |
  | close 4003 | *This sender was revoked* | stops |
  | close 4008 | *no audio received for 15 s* | reconnects |
  | close 1003 | audio format rejected | retries every 60 s |

* TLS certificate verification is always on. Plain `ws://` is accepted only for `localhost` / `127.0.0.1` testing and shows a warning.

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| **Authentication failed — check token / IP allowlist** | Re-paste the token, since it is easy to miss a character. In the admin dashboard, check that the sender is not revoked and that its IP allowlist contains the church's current public IP (search "what is my IP" from that computer). After repeated failures, the server blocks the IP for about 5 minutes. |
| Rejected with HTTP 401/403 even with a correct token | A reverse proxy such as Pangolin may require access-token headers. Add them under **Extra headers**. |
| **TLS certificate verification failed** | Check the computer's clock and date. A corporate proxy that intercepts TLS won't work. |
| **No levels at all** (meter shows nothing) | Wrong device, or the device is used exclusively by another app. Click **Refresh**, check the host API, and try WASAPI instead of MME. On macOS, check the microphone permission. |
| **Digital silence** (meter shows −120 dBFS) | Silence that is *exactly zero* almost always means a **broken Dante subscription**. Open Dante Controller and check that the subscription has a green tick, not a red X, that the clock is locked, and that the sample rate matches. On macOS, also check the microphone permission. |
| Levels present but very low | Check that you picked the right **channel**: DVS has many and only one carries the speech mix. Raise the console's Dante output level, or use **Input gain**. |
| **CLIP** lights up | Lower the gain or the console send level. Clipping hurts recognition more than a slightly low level does. |
| *Replaced by another sender* | Another computer (or a second copy of the app) is streaming for the same campus. Only the newest connection is kept. |
| *No audio from the input device* | The audio callback stopped, for example because the USB adapter was unplugged or DVS restarted. The app tries to reopen the device every 10 s. |
| "old audio dropped" counter rising | The network or the computer couldn't keep up for a moment. Occasional drops are harmless. |

## 9. Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests need no audio device and no PortAudio. The client tests run against a local fake ingest server built with `websockets.asyncio.server.serve`. With Docker:

```bash
docker run --rm -v "$PWD":/src -w /src python:3.12-slim sh -c \
  "pip install -q -r requirements.txt pytest==8.3.3 pytest-asyncio==0.24.0 && python -m pytest -q"
```

Code layout (`church_sender/`):

| Module | Purpose |
|---|---|
| `audio.py` | device listing, capture callback, channel pick, levels, drop-oldest buffer, soxr resample + framing |
| `client.py` | asyncio WebSocket loop, reconnect/backoff, status watchdog, close codes |
| `config.py` | platformdirs JSON + keyring secrets |
| `autostart.py` | LaunchAgent / HKCU Run entry |
| `runner.py` | headless service mode and the GUI's background client thread |
| `logsetup.py` | rotating log file with token redaction |
| `gui.py` | Tkinter UI |
| `__main__.py` | CLI: GUI (default), `--headless`, `--list-devices`, `--minimized` |
