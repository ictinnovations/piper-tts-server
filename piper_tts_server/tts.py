"""
Streaming TTS engine: Piper (local, ONNX) + optional ElevenLabs (cloud).

Synthesizes text to PCM, resamples to the target sample rate, and yields
fixed-size frames (default 20 ms @ 8 kHz slin16 -- the Asterisk AudioSocket
format) so callers can stream them straight into a paced writer, an
AudioSocket connection, a WebSocket, or a WAV file.

Why this exists as a standalone package
---------------------------------------
Two hard-won details make Piper usable in a real-time voice pipeline, and
both are baked in here:

  1. Process-wide voice cache. `PiperVoice.load()` takes 2.5-5.5 s (ONNX
     model load). Loading per request means every call starts with that
     much dead air. Voices are cached process-wide, keyed by path.

  2. A single synthesis lock. Piper phonemizes via espeak-ng, whose C API
     is NOT thread-safe, and a cached PiperVoice is shared across requests.
     All synthesis is serialized behind one asyncio.Lock.

Providers (see StreamingTTS.provider):
  piper       -- local ONNX voice under `voices_dir`. Default voice is
                 configurable; resolution prefers `{voices_dir}/{voice_id}.onnx`.
  elevenlabs  -- cloud API (needs api_key + voice_id). Audio is requested as
                 pcm_16000 and resampled. Any failure falls back to the local
                 Piper default voice so the stream never goes silent; a
                 401/403 disables further ElevenLabs attempts for the session.
"""

import asyncio
import io
import logging
import os
import wave
from typing import AsyncIterator, Optional

import numpy as np

log = logging.getLogger("piper_tts_server.tts")

# ---- Defaults (all overridable via TTSConfig / constructor) ----------------
DEFAULT_TARGET_SAMPLE_RATE = 8000   # slin16 / Asterisk AudioSocket
DEFAULT_FRAME_MS           = 20

ELEVEN_URL_TMPL      = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
ELEVEN_DEFAULT_MODEL = "eleven_flash_v2_5"
ELEVEN_SAMPLE_RATE   = 16000  # we request output_format=pcm_16000

# Process-wide voice cache + a single synthesis lock (espeak-ng phonemizer is
# not thread-safe; a cached PiperVoice is shared across requests).
_VOICE_CACHE: dict = {}
_VOICE_LOCK: Optional[asyncio.Lock] = None


def _frame_bytes(sample_rate: int, frame_ms: int) -> int:
    """Bytes in one mono 16-bit PCM frame of `frame_ms` at `sample_rate`."""
    return int(sample_rate * (frame_ms / 1000.0)) * 2


def resolve_voice_path(voice_id: Optional[str], voices_dir: str,
                       default_voice_path: Optional[str] = None) -> str:
    """
    Pick a voice .onnx file. Priority:
      1. {voices_dir}/{voice_id}.onnx   if voice_id given and the file exists
      2. default_voice_path             if it exists
      3. the single .onnx in voices_dir if exactly one is present
    Raises RuntimeError if nothing resolves.
    """
    if voice_id:
        candidate = os.path.join(voices_dir, f"{voice_id}.onnx")
        if os.path.isfile(candidate):
            return candidate
        log.warning("voice_id=%r requested but %s not found", voice_id, candidate)
    if default_voice_path and os.path.isfile(default_voice_path):
        return default_voice_path
    if os.path.isdir(voices_dir):
        onnx = [f for f in os.listdir(voices_dir) if f.endswith(".onnx")]
        if len(onnx) == 1:
            return os.path.join(voices_dir, onnx[0])
    raise RuntimeError(
        f"no Piper voice available (voice_id={voice_id}, "
        f"default={default_voice_path}, voices_dir={voices_dir})")


def resample_linear(pcm16: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Cheap linear resampler. Aliasing acceptable for <=16 kHz phone audio."""
    if src_sr == dst_sr:
        return pcm16
    ratio = dst_sr / src_sr
    out_len = int(len(pcm16) * ratio)
    if out_len <= 1:
        return np.zeros(0, dtype=np.int16)
    src_idx = np.linspace(0, len(pcm16) - 1, out_len, dtype=np.float32)
    lo = src_idx.astype(np.int32)
    hi = np.minimum(lo + 1, len(pcm16) - 1)
    frac = src_idx - lo
    out = (1.0 - frac) * pcm16[lo].astype(np.float32) + frac * pcm16[hi].astype(np.float32)
    return out.astype(np.int16)


def iter_frames(pcm: np.ndarray, frame_bytes: int) -> AsyncIterator[bytes]:
    """Yield PCM as fixed-size frames, padding the final partial frame with
    silence to keep a constant cadence."""
    view = pcm.tobytes()
    for off in range(0, len(view), frame_bytes):
        chunk = view[off:off + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
        yield chunk


def pcm_to_wav_bytes(pcm: np.ndarray, sample_rate: int) -> bytes:
    """Wrap slin16 mono PCM in a WAV container (for the non-streaming API)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class StreamingTTS:
    """One synthesis context. Reusable across many synthesise() calls."""

    def __init__(self, provider: str = "piper", voice_id: Optional[str] = None,
                 model: str = "", api_key: Optional[str] = None,
                 voices_dir: str = "voices",
                 default_voice_path: Optional[str] = None,
                 target_sample_rate: int = DEFAULT_TARGET_SAMPLE_RATE,
                 frame_ms: int = DEFAULT_FRAME_MS):
        self.provider   = (provider or "piper").strip().lower()
        self.voice_id   = voice_id
        self.model      = model
        self.api_key    = api_key or ""
        self.voices_dir = voices_dir
        self.default_voice_path = default_voice_path
        self.target_sr  = int(target_sample_rate)
        self.frame_ms   = int(frame_ms)
        self.frame_bytes = _frame_bytes(self.target_sr, self.frame_ms)
        self.voice_path = default_voice_path
        self._voice     = None
        self._native_sr = None
        self._eleven          = False
        self._eleven_disabled = False
        self._client          = None

    async def start(self) -> None:
        if self.provider == "elevenlabs":
            if self.api_key and self.voice_id:
                import httpx  # lazy: only needed for cloud TTS
                self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
                self._eleven = True
                log.info("TTS ready: elevenlabs voice=%s model=%s (piper fallback armed)",
                         self.voice_id, self.model or ELEVEN_DEFAULT_MODEL)
                return
            log.warning("provider=elevenlabs but %s missing; using piper",
                        "api_key" if not self.api_key else "voice_id")
        elif self.provider != "piper":
            log.warning("provider=%s not implemented; using piper", self.provider)
        await self._ensure_piper()
        log.info("TTS ready: voice=%s native_sr=%d -> %d Hz",
                 os.path.basename(self.voice_path), self._native_sr, self.target_sr)

    async def _ensure_piper(self) -> None:
        """Load (or fetch from cache) the local Piper voice."""
        global _VOICE_LOCK
        if self._voice is not None:
            return
        piper_voice_id = None if self._eleven else self.voice_id
        self.voice_path = resolve_voice_path(piper_voice_id, self.voices_dir,
                                             self.default_voice_path)
        log.info("TTS voice file resolved: %s", self.voice_path)
        if _VOICE_LOCK is None:
            _VOICE_LOCK = asyncio.Lock()
        async with _VOICE_LOCK:
            voice = _VOICE_CACHE.get(self.voice_path)
            if voice is None:
                from piper import PiperVoice  # lazy: clean import without piper installed
                voice = await asyncio.to_thread(PiperVoice.load, self.voice_path)
                _VOICE_CACHE[self.voice_path] = voice
                log.info("TTS voice loaded + cached: %s", os.path.basename(self.voice_path))
        self._voice = voice
        self._native_sr = self._voice.config.sample_rate

    async def _eleven_pcm(self, text: str) -> np.ndarray:
        url = ELEVEN_URL_TMPL.format(voice_id=self.voice_id)
        model = self.model if (self.model or "").startswith("eleven") else ELEVEN_DEFAULT_MODEL
        resp = await self._client.post(
            url,
            params={"output_format": f"pcm_{ELEVEN_SAMPLE_RATE}"},
            headers={"xi-api-key": self.api_key},
            json={"text": text, "model_id": model},
        )
        resp.raise_for_status()
        raw = resp.content
        pcm = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16)
        return resample_linear(pcm, ELEVEN_SAMPLE_RATE, self.target_sr)

    async def _piper_pcm(self, text: str) -> np.ndarray:
        await self._ensure_piper()

        def _synth() -> bytes:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                # piper-tts >= 1.3 (piper1-gpl) writes WAV via synthesize_wav();
                # its synthesize() now returns audio chunks and leaves the file
                # headerless ("# channels not specified"). 1.2 only has synthesize().
                synth_wav = getattr(self._voice, "synthesize_wav", None)
                if synth_wav is not None:
                    synth_wav(text, wf)
                else:
                    self._voice.synthesize(text, wf)
            buf.seek(0)
            with wave.open(buf) as wf:
                return wf.readframes(wf.getnframes())

        # Serialize synthesis: espeak-ng phonemizer is not thread-safe and the
        # PiperVoice is shared across requests.
        async with _VOICE_LOCK:
            pcm_bytes = await asyncio.to_thread(_synth)
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        if self._native_sr != self.target_sr:
            pcm = resample_linear(pcm, self._native_sr, self.target_sr)
        return pcm

    async def synthesise_pcm(self, text: str) -> np.ndarray:
        """Return the whole utterance as one slin16 PCM array at target_sr."""
        if not text.strip():
            return np.zeros(0, dtype=np.int16)
        pcm = None
        if self._eleven and not self._eleven_disabled:
            try:
                pcm = await self._eleven_pcm(text)
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (401, 403):
                    self._eleven_disabled = True
                    log.error("elevenlabs auth failed (%s); piper fallback for the session", status)
                else:
                    log.warning("elevenlabs synthesis failed (%s); piper fallback for this utterance", exc)
        if pcm is None:
            pcm = await self._piper_pcm(text)
        return pcm

    async def synthesise(self, text: str) -> AsyncIterator[bytes]:
        """Yield slin16 PCM bytes as fixed-size (frame_ms) chunks."""
        pcm = await self.synthesise_pcm(text)
        for chunk in iter_frames(pcm, self.frame_bytes):
            yield chunk

    async def close(self) -> None:
        self._voice = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


async def warm(voice_path: str) -> None:
    """Preload a Piper voice into the process-wide cache (call at startup)."""
    global _VOICE_LOCK
    if _VOICE_LOCK is None:
        _VOICE_LOCK = asyncio.Lock()
    async with _VOICE_LOCK:
        if voice_path in _VOICE_CACHE:
            return
        from piper import PiperVoice
        _VOICE_CACHE[voice_path] = await asyncio.to_thread(PiperVoice.load, voice_path)
        log.info("warmed voice: %s", os.path.basename(voice_path))
