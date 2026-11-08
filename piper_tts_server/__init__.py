"""piper-tts-server: a paced, streaming Piper (+ElevenLabs) TTS microservice."""

from .tts import StreamingTTS, resample_linear, resolve_voice_path, warm, pcm_to_wav_bytes
from .pacing import PacedWriter, make_silence_frame
from .sanitize import tts_sanitize, split_for_tts
from .config import ServerConfig

__version__ = "0.1.1"

__all__ = [
    "StreamingTTS", "resample_linear", "resolve_voice_path", "warm", "pcm_to_wav_bytes",
    "PacedWriter", "make_silence_frame",
    "tts_sanitize", "split_for_tts",
    "ServerConfig",
    "__version__",
]
