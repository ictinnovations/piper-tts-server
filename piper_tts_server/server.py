"""
HTTP microservice around StreamingTTS (aiohttp).

Endpoints
---------
GET  /health
    -> {"status":"ok","provider":..,"sample_rate":..,"cached_voices":[..]}

POST /warm            {"voice_id": "en_US-amy-medium"}
    Preload a voice into the process-wide cache. Returns {"warmed": path}.

POST /synthesize      {"text": "...", "voice_id": "...", "provider": "...",
                       "format": "wav"|"pcm"}
    One-shot synthesis. Returns audio/wav (default) or raw slin16 PCM
    (application/octet-stream) at the configured sample rate.

POST /synthesize/stream   same body, plus optional "paced": true
    Chunked transfer of fixed-size frames (frame_ms). With "paced": true the
    frames are released on the pacing deadline clock -- feed this straight to
    a real-time transport. Without it, frames are sent as fast as synthesized.

A per-voice StreamingTTS is cached and reused; the underlying PiperVoice is
shared process-wide via tts._VOICE_CACHE.
"""

import asyncio
import logging
from typing import Dict

from aiohttp import web

from .config import ServerConfig
from .pacing import PacedWriter
from . import tts as tts_mod

log = logging.getLogger("piper_tts_server.server")


class TTSService:
    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self._engines: Dict[str, tts_mod.StreamingTTS] = {}
        self._lock = asyncio.Lock()

    async def engine_for(self, voice_id: str, provider: str) -> tts_mod.StreamingTTS:
        key = f"{provider}:{voice_id}"
        eng = self._engines.get(key)
        if eng is not None:
            return eng
        async with self._lock:
            eng = self._engines.get(key)
            if eng is None:
                eng = tts_mod.StreamingTTS(
                    provider=provider,
                    voice_id=voice_id or self.cfg.default_voice,
                    api_key=self.cfg.elevenlabs_api_key,
                    voices_dir=self.cfg.voices_dir,
                    default_voice_path=self.cfg.default_voice_path(),
                    target_sample_rate=self.cfg.target_sample_rate,
                    frame_ms=self.cfg.frame_ms,
                )
                await eng.start()
                self._engines[key] = eng
        return eng


async def health(request: web.Request) -> web.Response:
    cfg: ServerConfig = request.app["cfg"]
    return web.json_response({
        "status": "ok",
        "provider": cfg.provider,
        "sample_rate": cfg.target_sample_rate,
        "frame_ms": cfg.frame_ms,
        "cached_voices": sorted(tts_mod._VOICE_CACHE.keys()),
    })


async def warm(request: web.Request) -> web.Response:
    cfg: ServerConfig = request.app["cfg"]
    body = await request.json()
    voice_id = body.get("voice_id") or cfg.default_voice
    path = tts_mod.resolve_voice_path(voice_id, cfg.voices_dir, cfg.default_voice_path())
    await tts_mod.warm(path)
    return web.json_response({"warmed": path})


async def synthesize(request: web.Request) -> web.Response:
    cfg: ServerConfig = request.app["cfg"]
    svc: TTSService = request.app["svc"]
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)
    provider = body.get("provider") or cfg.provider
    voice_id = body.get("voice_id") or cfg.default_voice
    fmt = (body.get("format") or "wav").lower()

    eng = await svc.engine_for(voice_id, provider)
    pcm = await eng.synthesise_pcm(text)

    if fmt == "pcm":
        return web.Response(body=pcm.tobytes(), content_type="application/octet-stream",
                            headers={"X-Sample-Rate": str(cfg.target_sample_rate)})
    wav = tts_mod.pcm_to_wav_bytes(pcm, cfg.target_sample_rate)
    return web.Response(body=wav, content_type="audio/wav")


async def synthesize_stream(request: web.Request) -> web.StreamResponse:
    cfg: ServerConfig = request.app["cfg"]
    svc: TTSService = request.app["svc"]
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)
    provider = body.get("provider") or cfg.provider
    voice_id = body.get("voice_id") or cfg.default_voice
    paced = bool(body.get("paced", False))

    eng = await svc.engine_for(voice_id, provider)

    resp = web.StreamResponse(status=200, headers={
        "Content-Type": "application/octet-stream",
        "X-Sample-Rate": str(cfg.target_sample_rate),
        "X-Frame-Ms": str(cfg.frame_ms),
    })
    await resp.prepare(request)

    if paced:
        writer = PacedWriter(resp.write, frame_ms=cfg.frame_ms)
        async for frame in eng.synthesise(text):
            await writer.write(frame)
    else:
        async for frame in eng.synthesise(text):
            await resp.write(frame)
    await resp.write_eof()
    return resp


def build_app(cfg: ServerConfig) -> web.Application:
    app = web.Application()
    app["cfg"] = cfg
    app["svc"] = TTSService(cfg)
    app.add_routes([
        web.get("/health", health),
        web.post("/warm", warm),
        web.post("/synthesize", synthesize),
        web.post("/synthesize/stream", synthesize_stream),
    ])

    async def _on_start(app: web.Application) -> None:
        if cfg.warm_on_start and cfg.provider == "piper":
            path = cfg.default_voice_path()
            if path:
                try:
                    await tts_mod.warm(path)
                except Exception as exc:  # pragma: no cover
                    log.warning("warm_on_start failed: %s", exc)

    app.on_startup.append(_on_start)
    return app


def run(cfg: ServerConfig = None) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = cfg or ServerConfig.from_env()
    log.info("piper-tts-server on %s:%d (provider=%s, %d Hz, voices=%s)",
             cfg.host, cfg.port, cfg.provider, cfg.target_sample_rate, cfg.voices_dir)
    web.run_app(build_app(cfg), host=cfg.host, port=cfg.port, print=None)
