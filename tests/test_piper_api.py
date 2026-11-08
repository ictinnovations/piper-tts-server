import asyncio

import numpy as np
from piper_tts_server import tts
from piper_tts_server.tts import StreamingTTS

PCM = np.arange(-50, 50, dtype=np.int16)


def _write(wf):
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(8000)
    wf.writeframes(PCM.tobytes())


class _Config:
    sample_rate = 8000


class VoiceV12:
    """piper-tts 1.2: synthesize(text, wav_file) writes the WAV."""
    config = _Config()

    def synthesize(self, text, wav_file):
        _write(wav_file)


class VoiceV13:
    """piper-tts >= 1.3: synthesize(text) yields chunks; synthesize_wav writes the WAV."""
    config = _Config()

    def synthesize(self, text, syn_config=None):
        return iter(())  # writing nothing here is what broke issue #1

    def synthesize_wav(self, text, wav_file, syn_config=None, set_wav_format=True):
        _write(wav_file)


def _synth_with(voice):
    eng = StreamingTTS(provider="piper", target_sample_rate=8000)
    eng._voice = voice
    eng._native_sr = 8000

    async def go():
        tts._VOICE_LOCK = asyncio.Lock()
        return await eng.synthesise_pcm("Hello from Piper.")

    return asyncio.run(go())


def test_piper_12_api():
    assert np.array_equal(_synth_with(VoiceV12()), PCM)


def test_piper_13_api():
    assert np.array_equal(_synth_with(VoiceV13()), PCM)
