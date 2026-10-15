# Audio input

Each campus takes its speech mix from one of two sources, chosen in **Campuses → Edit → Audio source**.

| Source | Use it when | How it connects |
|---|---|---|
| **Local input on this server** (default) | The OneVoice server is at the church and has the audio interface plugged in (USB interface, Dante AVIO adapter, Dante Virtual Soundcard on Linux). | The `local-audio` service captures the chosen device and channel directly. There is no network hop and no token. |
| **Remote sender app** | The server is a VPS (or any machine without the audio), and a computer at church has the audio. | The **OneVoice Sender** app streams the chosen channel to the server's audio input (port 8082) using a per-campus token. |

Only one source is used per campus. A campus set to *local* refuses Sender connections, and the Sender shows a message explaining why. Campuses that already had a Sender when this option was added were switched to *remote* automatically.

## Local input on the server

1. Plug the audio interface into the server and route the speech mix to one of its inputs.
2. Enable the service in `.env`:
   ```
   COMPOSE_PROFILES=local-audio          # add ",newt" if you also use the Pangolin tunnel
   ```
3. Start with the local-network overlay, which gives the container access to `/dev/snd`:
   ```bash
   docker compose -f compose.yml -f compose.local.yml up -d --build
   ```
4. In **Campuses → Edit**:
   - choose **Local input on this server**;
   - pick the **input device** (the list comes from the server);
   - pick the **channel** that carries the speech mix.
5. **Audio** shows the level meter. During a service it shows *Forwarding to STT*.

**Linux only.** Docker on macOS and Windows can't reach audio hardware. On a Mac or Windows server, use the **Sender app on the same computer** instead: set the campus to *Remote sender app* and point the Sender at `ws://localhost:8082/ingest/v1/stream`.

**Trying it without hardware:** set `LOCAL_AUDIO_TEST_TONE=1` in `.env`. A simulated **Test tone** input then appears in the device list.

If the device disappears (unplugged, renamed), **Audio** shows *Device … not found on the server*. Captions show "The streaming service is currently not connected…" until it returns. Capture restarts automatically when it does.

## Remote sender app

1. Set the campus to **Remote sender app**.
2. Under **Audio → Senders**, create a sender for the campus. Optionally restrict it to the church's public IP. Copy the token, which is shown once.
3. Install the OneVoice Sender ([Releases](https://github.com/Nick-116/OneVoice/releases/latest)) at church. Paste the server address and the token, then choose the input and channel.
4. Expose the audio input only to the church. See [SECURITY.md](SECURITY.md).

Both sources produce the same 16 kHz mono audio. Captions, levels, *digital silence* detection and the "not connected" message all work the same way.
