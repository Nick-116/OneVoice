## OneVoice Sender: audio sender for Mac, Windows and Raspberry Pi

Sends the speech mix from your sound board (Dante Virtual Soundcard, a Dante AVIO USB adapter, or any audio input) to your OneVoice server for live captions and translation.

| Download | For |
|---|---|
| `OneVoiceSender-*-macOS-AppleSilicon.dmg` | Macs with M1/M2/M3/M4 chips |
| `OneVoiceSender-*-macOS-Intel.dmg` | Intel Macs |
| `OneVoiceSender-*-Windows-Setup.exe` | Windows 10/11 installer (recommended) |
| `OneVoiceSender-*-Windows-Portable.zip` | Windows, no install (unzip and run) |
| `OneVoiceSender-*-RaspberryPi.img.xz` | Raspberry Pi 4/5 with a USB audio input: flash with Raspberry Pi Imager, then open http://onevoice-sender.local ([guide](https://nick-116.github.io/OneVoice/RASPBERRY_PI/)) |

### First launch
These builds are not yet signed with paid Apple / Microsoft certificates, so your computer asks once before opening them:
- **macOS:** open the DMG and drag the app to Applications. Open it once and click **Done** on the warning. Then go to **System Settings → Privacy & Security** and click **Open Anyway** next to *“OneVoice Sender” was blocked*. Allow microphone access when asked.
- **Windows:** if SmartScreen says *Windows protected your PC*, click **More info → Run anyway**.

Then enter your server's IP address or hostname, paste the sender token from the OneVoice admin dashboard (**Audio → Senders**), choose the input and channel, and click **Start streaming**.

The server itself runs with Docker; see the README.

Verify downloads with `SHA256SUMS.txt`.
