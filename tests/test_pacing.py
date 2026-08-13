import asyncio
from piper_tts_server.pacing import PacedWriter, make_silence_frame


def test_silence_frame_size():
    assert len(make_silence_frame(8000, 20)) == 320
    assert make_silence_frame(8000, 20) == b"\x00" * 320


def test_paced_writer_uses_deadline_clock():
    # A virtual clock that does not advance on its own: proves pacing is driven
    # by the deadline, and that a stalled clock never causes negative sleeps.
    t = {"now": 0.0}
    sleeps = []

    async def sink(_frame):
        pass

    async def fake_sleep(d):
        sleeps.append(d)
        t["now"] += d               # advance virtual time by the slept amount

    async def run():
        w = PacedWriter(sink, frame_ms=20, clock=lambda: t["now"])
        orig_sleep = asyncio.sleep
        asyncio.sleep = fake_sleep   # type: ignore
        try:
            for _ in range(5):
                await w.write(b"\x00" * 320)
        finally:
            asyncio.sleep = orig_sleep  # type: ignore
        return w

    w = asyncio.get_event_loop().run_until_complete(run())
    assert w.frames_out == 5
    # every scheduled delay is one frame interval, never a burst / negative
    assert all(abs(d - 0.02) < 1e-9 for d in sleeps)


def test_reset_clears_deadline():
    w = PacedWriter(lambda _f: None, frame_ms=20)
    w._deadline = 123.0
    w.reset()
    assert w._deadline == 0.0
