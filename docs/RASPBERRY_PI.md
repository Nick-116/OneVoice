# Raspberry Pi sender

A Raspberry Pi with a USB audio input can stand in for the OneVoice Sender app. Flash the ready-made image, plug in the audio and Ethernet, and the Pi streams the speech mix to OneVoice from every boot. No computer needs to stay on at church.

You set it up from a web page on the Pi, which has the same settings and level meter as the desktop app.

## What you need

| | |
|---|---|
| **Raspberry Pi 4 or 5** | Any memory size. A Pi 3B+ also runs the 64-bit image. |
| **Power supply** | The official one for your model (USB-C, 5 V 3 A for Pi 4, 5 A for Pi 5). |
| **microSD card** | 16 GB or larger. |
| **USB audio input** | Any class-compliant USB interface or adapter, e.g. a USB sound card, a small USB mixer, or a Dante AVIO USB adapter. |
| **Ethernet cable** | To the church network. Wi-Fi works too but is less reliable during a service. |

## 1. Flash the image

1. Download `OneVoiceSender-<version>-RaspberryPi.img.xz` from the [latest release](https://github.com/Nick-116/OneVoice/releases/latest).
2. Install and open [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
3. **Choose Device:** your Pi model.
4. **Choose OS:** scroll down to **Use custom** and pick the downloaded `.img.xz` file. No need to unzip it.
5. **Choose Storage:** your microSD card.
6. Click **Next**, then **Edit settings** when asked about OS customisation. This step is required:
   - **Set hostname:** `onevoice-sender`. If you have several Pis, use `onevoice-sender-north` and so on.
   - **Set username and password:** you sign in to the web page with these. The image ships with no default password, so without this step you can't sign in.
   - **Configure wireless LAN:** only if you can't use Ethernet.
   - **Set locale settings:** your time zone.
   - **Services → Enable SSH:** optional, only needed for troubleshooting.
7. Click **Save**, then **Yes** to apply the settings, and write the card.

## 2. First boot

1. Put the card in the Pi, then connect the USB audio input, Ethernet and power.
2. Wait about two minutes. The Pi may restart once while it applies your settings.
3. On a computer or phone on the same network, open **http://onevoice-sender.local**.
   - If the name doesn't open, which happens on some Windows and Android devices, use the Pi's IP address from your router's device list, e.g. `http://192.168.1.50`.
   - Give the Pi a fixed address in your router so it's easy to find again.
4. Sign in with the username and password you set in Imager.

## 3. Set it up

This works the same as the desktop app:

1. In the OneVoice dashboard, set the campus's **audio source** to **Remote sender app**. Then under **Audio → Senders**, create a sender for the campus and copy its token.
2. On the Pi's page, fill in:
   - **Server address:** your OneVoice server's IP address or hostname, e.g. `192.168.1.20`.
   - **Sender token:** paste the token.
   - **Device:** your USB audio input. If it's missing, check the cable and click the refresh button next to the list.
   - **Channel:** the input your speech mix is on.
3. Click **Test input** and check that the meter moves when someone talks. Aim for −30 to −12 dBFS.
4. Click **Save settings**, then **Start streaming**.

**Start streaming whenever the Pi starts** (under *Startup & advanced*) is on by default. After a power cut or reboot, the Pi reconnects on its own. If the USB input is plugged in after boot, streaming starts within a few seconds of it appearing.

**Stop streaming** on the page pauses the Pi until you click Start again or the Pi restarts.

## Updating

To install a newer version, flash the new image the same way. The card is erased, so keep the sender token handy or create a new one in the dashboard. It takes about five minutes.

Raspberry Pi OS security updates install automatically.

## Troubleshooting

| Problem | What to do |
|---|---|
| `onevoice-sender.local` doesn't open | Use the IP address from your router. Check the Pi's green light flickers (it's reading the card) and the Ethernet lights are on. |
| "Wrong username or password" | Use the account you set in Imager. Only accounts in the `sudo` group can sign in (Imager's account is). After 10 wrong tries, sign-in pauses for 5 minutes. |
| No input devices listed | Plug the USB audio input straight into the Pi rather than through a hub, then click refresh. |
| Captions say "not connected" | Check the status at the top of the page and the activity log at the bottom. The usual causes are a wrong server address, a revoked token, or a campus set to local audio. |
| Need the logs | With SSH enabled: `ssh <user>@onevoice-sender.local`, then `sudo journalctl -u onevoice-sender -f`. |

## Security

- **Web page:** it is plain HTTP on your local network. Sign-in uses the Pi's own account, sessions expire after 12 hours, and every change requires a signed-in session.
- **Sender token:** stored in a file only the OneVoice service can read, never shown on the page again.
- **Service account:** the sender runs as an unprivileged `onevoice` user. The root account is locked.
- **Network exposure:** keep the Pi on the church network and don't forward port 80 to it from the internet.
