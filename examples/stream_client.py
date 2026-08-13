#!/usr/bin/env python3
"""
Stream synthesized frames from a running piper-tts-server and save to a WAV.

    python examples/stream_client.py "Hello from Piper" out.wav

Demonstrates the paced streaming endpoint: frames arrive on the 20 ms deadline
clock, exactly as a real-time transport would consume them.
"""
import sys
import wave
import urllib.request
import json

URL = "http://127.0.0.1:8080/synthesize/stream"
SAMPLE_RATE = 8000


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello from Piper TTS server."
    out = sys.argv[2] if len(sys.argv) > 2 else "out.wav"
    req = urllib.request.Request(
        URL, data=json.dumps({"text": text, "paced": True}).encode(),
        headers={"Content-Type": "application/json"})
    pcm = bytearray()
    with urllib.request.urlopen(req) as resp:
        sr = int(resp.headers.get("X-Sample-Rate", SAMPLE_RATE))
        while True:
            frame = resp.read(320)
            if not frame:
                break
            pcm += frame
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(pcm))
    print(f"wrote {out}: {len(pcm)} bytes @ {sr} Hz")


if __name__ == "__main__":
    main()
