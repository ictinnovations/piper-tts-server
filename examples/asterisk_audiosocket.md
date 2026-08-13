# Using piper-tts-server with Asterisk AudioSocket

The server emits **8 kHz mono slin16** in 20 ms frames by default — exactly the
[AudioSocket](https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/)
media format. Two ways to wire it up:

## A. Your sidecar owns the AudioSocket connection (recommended)

Your process accepts the AudioSocket TCP connection from Asterisk, and pulls
paced frames from the library directly (no HTTP hop in the media path):

```python
from piper_tts_server import StreamingTTS, PacedWriter

tts = StreamingTTS(voices_dir="voices", default_voice_path="voices/en_US-amy-medium.onnx")
await tts.start()

async def speak(text, audiosocket_write):
    writer = PacedWriter(audiosocket_write, frame_ms=20)   # audiosocket_write sends one AUDIO frame
    async for frame in tts.synthesise(text):
        await writer.write(frame)
```

`PacedWriter` releases one 320-byte frame every 20 ms on a deadline clock, so
you never overrun the far end's jitter buffer — the single most common cause of
"the caller only hears the tail of each sentence".

## B. Call the HTTP service

Run the service and POST text; stream the paced PCM back:

```bash
piper-tts-server &                # PIPER_TTS_VOICES_DIR=voices, port 8080
curl -N -X POST http://127.0.0.1:8080/synthesize/stream \
  -H 'Content-Type: application/json' \
  -d '{"text":"Your call is being connected.","paced":true}' \
  --output frames.slin
```

Feed `frames.slin` into your AudioSocket `AUDIO` frames. Prefer option A when
latency matters — it keeps HTTP out of the real-time path.

## Sanitizing LLM output before synthesis

If the text comes from an LLM, strip markdown/emoji first so Piper doesn't
pronounce them, and start synthesis at sentence boundaries as tokens stream in:

```python
from piper_tts_server import tts_sanitize, split_for_tts

buf = ""
for delta in llm_stream():
    buf += delta
    chunks, buf = split_for_tts(buf)
    for c in chunks:
        await speak(tts_sanitize(c), audiosocket_write)
chunks, buf = split_for_tts(buf, force_flush=True)   # flush the tail at end
```
