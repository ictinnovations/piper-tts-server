"""
Text preparation for TTS.

LLM output is written for chat: markdown emphasis and emoji that a TTS engine
would try to pronounce ("asterisk asterisk...") or garble. `tts_sanitize`
strips to plain speakable text. `split_for_tts` chunks streaming LLM output at
sentence boundaries so synthesis can start before the full reply arrives --
including Urdu full stop (U+06D4), Arabic question mark (U+061F), and
Devanagari danda (U+0964), which the ASCII-only default would miss.
"""

import re
from typing import List, Tuple

# Sentence end: latin/urdu/devanagari terminators, or a clause break (comma,
# semicolon, colon) followed by more text -- lets synthesis start mid-reply.
_SENT_END = re.compile(r"([.!?؟।۔]\s|[,;:]\s(?=\S))")

_MD_STRIP = re.compile(r"[*_`#~]+")
_NON_SPEAKABLE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji & symbols
    "\U00002190-\U000021FF"   # arrows
    "\U00002600-\U000027BF"   # misc symbols / dingbats
    "\U0001F1E6-\U0001F1FF"   # regional indicators
    "️‍"            # variation selector / zero-width joiner
    "]+"
)


def tts_sanitize(text: str) -> str:
    """Strip markdown and non-speakable glyphs; collapse whitespace."""
    text = _MD_STRIP.sub("", text)
    text = _NON_SPEAKABLE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def split_for_tts(buf: str, force_flush: bool = False) -> Tuple[List[str], str]:
    """Return (complete chunks ready for TTS, remaining buffer).

    Feed streaming LLM deltas in; emit each completed sentence/clause as soon
    as it closes. Pass force_flush=True at end-of-stream to flush the tail.
    """
    chunks: List[str] = []
    remaining = buf
    while True:
        m = _SENT_END.search(remaining)
        if not m:
            break
        end = m.end()
        chunks.append(remaining[:end].strip())
        remaining = remaining[end:]
    if force_flush and remaining.strip():
        chunks.append(remaining.strip())
        remaining = ""
    return chunks, remaining
