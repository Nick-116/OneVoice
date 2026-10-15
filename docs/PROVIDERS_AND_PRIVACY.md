# Speech, translation providers, cost and privacy

## Defaults

| Function | Default | Alternative(s) | Why |
|---|---|---|---|
| Streaming speech-to-text | **Deepgram Nova-3** | AssemblyAI Universal-Streaming | Lowest partial latency (~300 ms), strong English accuracy, punctuation and smart formatting, *keyterm prompting* for names, places and scripture books |
| Translation | **Azure AI Translator** | Google Cloud Translation (Basic v2) | Lowest price per character; supports all 12 launch languages, including Haitian Creole |
| Development | `simulated` STT + `simulated` translation | – | No keys, no cost, deterministic output (`[es] …`) |

You switch providers in **Admin → Providers & Settings** without a redeploy.

Adding a provider (including a self-hosted model later, such as Whisper or NLLB on a GPU box) means:

* writing one class in `backend/captions/providers/stt/` or `providers/translate/`, implementing `STTProvider`/`STTSession` or `TranslationProvider`;
* registering it in that package's `__init__.py`;
* adding its default settings to `config_store.py`.

Nothing else changes.

## Pricing models (verify current prices before budgeting)

| Provider | Model | Approx. list price | Notes |
|---|---|---|---|
| Deepgram Nova-3 streaming | per audio minute streamed | ~$0.0077 / min | Billed while audio is sent. The worker closes the stream after 10 s without audio and never streams outside a service window. |
| AssemblyAI Universal-Streaming | per session hour | ~$0.15 / hr | English-only streaming model |
| Azure Translator (S1) | per character translated, per target language | ~$10 / million chars | F0 free tier has 2M chars/month but is rate-limited; use S1 for live services |
| Google Translation Basic | per character | ~$20 / million chars | First 500K chars/month free |

Set each unit price in the provider's settings. The worker multiplies it by metered usage to produce the **estimated cost** on the dashboard.

### Rough monthly estimate
Assumptions: 2 campuses × ~6 service-hours/week ≈ 52 hours/month. Speech runs about 150 words/min, which is about 900 characters/min, or ~54K characters/hour.

* Speech-to-text: 52 h × 60 × $0.0077 ≈ **$24/month**
* Translation: ~2.8M characters per language that is *actually being viewed* ≈ **$28/month per active language** on Azure

### How cost is kept down
* **One translation per language, not per viewer.** 100 Spanish viewers share one Spanish stream.
* **Only languages someone is watching are translated.** Each campus's translation channel starts when the first viewer of that language connects. It stops 60 s after the last one leaves (configurable).
* **Only finalized sentences are translated** by default. Translating partials (`translate_partials`) multiplies translation cost roughly 3–5×, so it's off unless you turn it on.
* **No processing outside service windows.** Outside a window, ingest drops audio (it only drives the level meter) and no STT session exists.
* HTTP keep-alive and connection pooling to the translation API.

## Latency strategy

* **English (source) viewers see partial results** as they're recognized, typically 300–800 ms after the words are spoken.
* **Partial vs final:**
  - Partials are shown in grey on the same line and replaced in place by the final version, so nothing unstable is presented as final.
  - A caption line becomes final when the provider marks it stable and it ends in punctuation, at a speaker pause, or once ~60 characters have built up and there is a clause break (comma, semicolon, colon or dash) to cut at. Long sentences are translated in pieces instead of waiting for the period. A run-on with no break is split at a space after ~140 characters.
* **Translated viewers get each finalized sentence** about 1.5–4 s after it's spoken: STT finalization plus one translation round trip of ~100–300 ms.
* **Metrics:** the dashboard shows measured p50/p95 for STT partials, STT finals, translation round trips, and audio-to-translated-caption end to end, per language.

## Privacy

* **Audio** is sent to the speech provider only during scheduled service windows. **Raw audio is never stored** on the VPS: it passes through a ~30-second bounded Redis buffer in memory.
* **Transcripts** are kept only if an administrator turns on *Retain transcripts* for a campus. They're automatically deleted after `transcript_retention_days` (default 30). Live captions otherwise exist only in a 50-line in-memory buffer that gives late joiners context.
* **Congregation members:**
  - No accounts, cookies, analytics or third-party scripts.
  - The site stores only the chosen language and text size in the phone's local storage.
  - The server keeps an aggregate count of viewers per language, nothing per person.
  - IP addresses appear only in short-lived rate-limit memory and in security logs for blocked requests.
* **Third-party processing:**
  - Spoken content (sermons, announcements, prayers, possibly names or personal prayer requests) is processed by the speech and translation providers under their terms.
  - Check each provider's data-retention settings. Deepgram and Azure both offer options so customer data isn't used for model training. Consider a brief notice in the bulletin or on screen that captions are machine-generated by third-party services.
  - Ask the production team not to route private conversations (green room, prayer counseling) into the speech mix.
* **Machine translation** can be wrong, especially for theological terms and Scripture references. Add frequent terms as Deepgram *keyterms*. Have native speakers review the UI translations in `public-web/src/locales/`.
