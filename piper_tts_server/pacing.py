"""
Deadline-based frame pacing.

Why pace at all
---------------
When TTS output is forwarded to a real-time transport (Asterisk AudioSocket,
an RTP leg, a WebSocket to a browser), each frame is sent onward the instant
it arrives. Bursting a whole utterance overruns the far end's ~100-200 ms
jitter buffer and the listener hears only the tail of each chunk.

The fix is to release exactly one frame per frame-interval on a *deadline*
clock, never faster. The subtle bug this solves (and re-solves every frame):
if synthesis latency stalls the loop, the deadline goes stale and the next
frames would burst to "catch up". `PacedWriter.write` re-clamps the deadline to
`now` every frame, so a stall never produces a burst -- pacing resumes cleanly
from the present instant.
"""

import asyncio
import time
from typing import Awaitable, Callable, Optional


class PacedWriter:
    """Releases frames at a fixed cadence on a monotonic deadline clock.

    Parameters
    ----------
    sink:
        async callable invoked with each frame's bytes (write to socket, etc.).
    frame_ms:
        frame interval in milliseconds (default 20).
    clock:
        monotonic time source in seconds. Defaults to a loop-relative clock;
        pass ``time.monotonic`` for a loop-independent one.
    """

    def __init__(self, sink: Callable[[bytes], Awaitable[None]],
                 frame_ms: int = 20,
                 clock: Optional[Callable[[], float]] = None):
        self._sink = sink
        self._frame_sec = frame_ms / 1000.0
        self._clock = clock
        self._deadline = 0.0
        self.frames_out = 0

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock()
        return asyncio.get_event_loop().time()

    def reset(self) -> None:
        """Drop the accumulated deadline (call before a fresh talk-spurt)."""
        self._deadline = 0.0

    async def write(self, frame: bytes) -> None:
        """Send one frame, then sleep until its pacing deadline."""
        now = self._now()
        # Re-clamp: never let a stalled deadline cause a burst.
        self._deadline = max(self._deadline, now)
        await self._sink(frame)
        self.frames_out += 1
        self._deadline += self._frame_sec
        delay = self._deadline - self._now()
        if delay > 0:
            await asyncio.sleep(delay)


def make_silence_frame(sample_rate: int = 8000, frame_ms: int = 20) -> bytes:
    """A single silent mono 16-bit PCM frame (useful for pre-roll / keepalive)."""
    return b"\x00" * (int(sample_rate * (frame_ms / 1000.0)) * 2)
