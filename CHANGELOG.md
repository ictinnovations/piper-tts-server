# Changelog

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
