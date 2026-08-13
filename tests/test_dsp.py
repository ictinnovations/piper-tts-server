import numpy as np
from piper_tts_server.tts import resample_linear, iter_frames, pcm_to_wav_bytes, _frame_bytes


def test_resample_identity():
    pcm = np.arange(100, dtype=np.int16)
    out = resample_linear(pcm, 8000, 8000)
    assert np.array_equal(out, pcm)


def test_resample_downsamples_length():
    pcm = np.zeros(2205, dtype=np.int16)          # 0.1 s @ 22050
    out = resample_linear(pcm, 22050, 8000)
    assert abs(len(out) - 800) <= 1               # ~0.1 s @ 8000


def test_frame_bytes():
    assert _frame_bytes(8000, 20) == 320          # 160 samples * 2 bytes
    assert _frame_bytes(16000, 20) == 640


def test_iter_frames_pads_tail():
    pcm = np.zeros(170, dtype=np.int16)           # 340 bytes -> 2 frames (320 + padded)
    frames = list(iter_frames(pcm, 320))
    assert len(frames) == 2
    assert all(len(f) == 320 for f in frames)


def test_wav_roundtrip_header():
    pcm = np.zeros(160, dtype=np.int16)
    wav = pcm_to_wav_bytes(pcm, 8000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
