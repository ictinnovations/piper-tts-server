# piper-tts-server

**Paced, streaming [Piper](https://github.com/OHF-Voice/piper1-gpl) TTS for real-time voice pipelines** — Asterisk AudioSocket, RTP, or a browser WebSocket. Optional ElevenLabs cloud voices with automatic local fallback.

[![CI](https://github.com/ictinnovations/piper-tts-server/actions/workflows/ci.yml/badge.svg)](https://github.com/ictinnovations/piper-tts-server/actions)
[![PyPI](https://img.shields.io/pypi/v/piper-tts-server.svg)](https://pypi.org/project/piper-tts-server/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

If you have tried to bolt Piper onto a phone call and hit **dead air before the greeting**, **the first few words clipped**, or **the caller only hearing the tail of each sentence** — this library is the fix. It packages the three things that make Piper work in a real-time loop:

1. **Process-wide voice cache.** `PiperVoice.load()` costs 2.5–5.5 s. Loading per request means that much dead air before every utterance. Voices load once and are reused.
2. **A single synthesis lock.** Piper phonemizes via espeak-ng, whose C API is **not thread-safe**. All synthesis is serialized behind one lock so concurrent calls don't corrupt each other.
3. **Deadline-based frame pacing.** Real-time transports forward each frame the instant it arrives; bursting a whole utterance overruns the far end's jitter buffer. `PacedWriter` releases exactly one frame per interval on a monotonic deadline — and **re-clamps every frame** so a synthesis stall never turns into a catch-up burst that clips the next words.

## Install

```bash
pip install "piper-tts-server[all]"     # library + server + piper + elevenlabs
# or minimal:
pip install piper-tts-server            # library core (numpy only)
pip install "piper-tts-server[piper,server]"
```

Download a Piper voice (`.onnx` + `.onnx.json`) into a `voices/` directory — see the [Piper voices list](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/voices.md).

## Run the service

```bash
PIPER_TTS_VOICES_DIR=voices PIPER_TTS_DEFAULT_VOICE=en_US-amy-medium \
  piper-tts-server            # listens on 127.0.0.1:8080
```

```bash
# one-shot WAV
curl -X POST localhost:8080/synthesize \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from Piper."}' --output hello.wav

# paced streaming slin16 frames (feed straight to AudioSocket/RTP)
curl -N -X POST localhost:8080/synthesize/stream \
  -H 'Content-Type: application/json' \
  -d '{"text":"Your call is being connected.","paced":true}' --output frames.slin
```

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | status + cached voices |
| `POST /warm` `{voice_id}` | preload a voice into the cache |
| `POST /synthesize` `{text, voice_id, provider, format}` | one-shot `wav` (default) or raw `pcm` |
| `POST /synthesize/stream` `{text, …, paced}` | chunked frames; `paced:true` = deadline-clocked |

## Use as a library (no HTTP in the media path)

```python
from piper_tts_server import StreamingTTS, PacedWriter, tts_sanitize

tts = StreamingTTS(voices_dir="voices", default_voice_path="voices/en_US-amy-medium.onnx")
await tts.start()

writer = PacedWriter(my_audiosocket_write, frame_ms=20)   # sink: async fn(bytes)
async for frame in tts.synthesise(tts_sanitize(text)):
    await writer.write(frame)                              # 320 bytes / 20 ms, paced
```

See [`examples/asterisk_audiosocket.md`](examples/asterisk_audiosocket.md) for the full AudioSocket wiring and streaming-LLM sentence chunking.

## Configuration

All via env (or `ServerConfig`): `PIPER_TTS_HOST`, `PIPER_TTS_PORT`, `PIPER_TTS_VOICES_DIR`, `PIPER_TTS_DEFAULT_VOICE`, `PIPER_TTS_PROVIDER` (`piper`|`elevenlabs`), `PIPER_TTS_ELEVENLABS_API_KEY`, `PIPER_TTS_SAMPLE_RATE` (default `8000`), `PIPER_TTS_FRAME_MS` (default `20`), `PIPER_TTS_WARM_ON_START`.

Default output is **8 kHz slin16 / 20 ms frames** (telephony). Set `PIPER_TTS_SAMPLE_RATE=16000` for wideband.

### ElevenLabs with local fallback

Set `PIPER_TTS_PROVIDER=elevenlabs` + `PIPER_TTS_ELEVENLABS_API_KEY` and pass a `voice_id`. Any failure falls back to the local Piper default voice so the stream never goes silent; a `401/403` disables further cloud attempts for that engine.

## Development

```bash
pip install "piper-tts-server[dev]"
pytest          # pure-DSP, sanitize, and pacing tests run without Piper installed
```

## Licensing

This package is **MIT licensed** and contains no Piper source code. Piper is an optional extra, imported lazily only when the local engine is used — the core library installs with numpy alone, and the test suite runs without Piper present.

Piper itself is a separate project under a different licence. The maintained release ([`OHF-Voice/piper1-gpl`](https://github.com/OHF-Voice/piper1-gpl), PyPI [`piper-tts`](https://pypi.org/project/piper-tts/)) is **GPL-3.0-or-later**; the older MIT `rhasspy/piper` is archived. If you install the `[piper]` or `[all]` extra, the resulting combined installation is subject to GPL-3.0 terms. The ElevenLabs provider, and the pacing and sanitising helpers on their own, pull in no GPL code.

**Not affiliated with, or endorsed by, the Open Home Foundation or the Piper project.** This is an independent server and library that drives Piper as one of several backends.

## Provenance & credits

Extracted and generalized from the TTS layer of **[ICTContact](https://www.ictcontact.com)**'s AI Voice Agent, by **[ICT Innovations](https://www.ictinnovations.com)** / **[ICT Vision](https://ict.vision)**. Author: **Tahir Almas**. Companion project: [`asterisk-ai-voice-agent`](https://github.com/ictinnovations/asterisk-ai-voice-agent).

MIT licensed — see [LICENSE](LICENSE).
