# Changelog

## 0.1.1 - 2026-11-08

- Fix `/synthesize` and `/synthesize/stream` failing with
  `wave.Error: # channels not specified` on piper-tts 1.3 and later (#1).
  Those releases moved WAV output to `PiperVoice.synthesize_wav()`; the server
  now uses it when present and still supports piper-tts 1.2.
- CI also runs on Python 3.13.

## 0.1.0 — 2026-08-13

Initial release. Extracted and generalized from the ICTContact AI Voice Agent
TTS layer.

- `StreamingTTS`: Piper (local ONNX) + ElevenLabs (cloud, with local fallback).
- Process-wide voice cache; single espeak-ng-safe synthesis lock.
- `PacedWriter`: deadline-based 20 ms frame pacing with per-frame re-clamp.
- `tts_sanitize` / `split_for_tts`: markdown/emoji stripping and streaming-LLM
  sentence chunking (Latin + Urdu + Devanagari terminators).
- aiohttp microservice: `/health`, `/warm`, `/synthesize`, `/synthesize/stream`.
- Configurable sample rate / frame size (default 8 kHz slin16 / 20 ms).
