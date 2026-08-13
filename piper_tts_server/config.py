"""Runtime configuration, sourced from constructor args or environment."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    voices_dir: str = "voices"
    default_voice: Optional[str] = None          # basename without .onnx, or a path
    provider: str = "piper"                       # piper | elevenlabs
    elevenlabs_api_key: str = ""
    target_sample_rate: int = 8000
    frame_ms: int = 20
    warm_on_start: bool = True                    # preload default voice at boot

    @classmethod
    def from_env(cls) -> "ServerConfig":
        def _b(name: str, default: bool) -> bool:
            v = os.environ.get(name)
            return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")
        return cls(
            host=os.environ.get("PIPER_TTS_HOST", cls.host),
            port=int(os.environ.get("PIPER_TTS_PORT", cls.port)),
            voices_dir=os.environ.get("PIPER_TTS_VOICES_DIR", cls.voices_dir),
            default_voice=os.environ.get("PIPER_TTS_DEFAULT_VOICE") or None,
            provider=os.environ.get("PIPER_TTS_PROVIDER", cls.provider),
            elevenlabs_api_key=os.environ.get("PIPER_TTS_ELEVENLABS_API_KEY", ""),
            target_sample_rate=int(os.environ.get("PIPER_TTS_SAMPLE_RATE", cls.target_sample_rate)),
            frame_ms=int(os.environ.get("PIPER_TTS_FRAME_MS", cls.frame_ms)),
            warm_on_start=_b("PIPER_TTS_WARM_ON_START", cls.warm_on_start),
        )

    def default_voice_path(self) -> Optional[str]:
        """Resolve default_voice (basename or path) to a filesystem path."""
        if not self.default_voice:
            return None
        if os.path.isfile(self.default_voice):
            return self.default_voice
        cand = os.path.join(self.voices_dir, f"{self.default_voice}.onnx")
        return cand if os.path.isfile(cand) else None
