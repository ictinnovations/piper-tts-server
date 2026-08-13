from piper_tts_server.sanitize import tts_sanitize, split_for_tts


def test_strips_markdown_and_emoji():
    assert tts_sanitize("**Hello** _world_ `code`") == "Hello world code"
    assert tts_sanitize("Great news 🎉🚀 done") == "Great news done"


def test_collapses_whitespace():
    assert tts_sanitize("a\n\n b   c\t") == "a b c"


def test_split_on_sentence_end():
    chunks, rem = split_for_tts("Hello there. How are")
    assert chunks == ["Hello there."]
    assert rem == "How are"


def test_split_urdu_full_stop():
    chunks, rem = split_for_tts("سلام ۔ ")
    assert chunks == ["سلام ۔"]


def test_force_flush_tail():
    chunks, rem = split_for_tts("no terminator here", force_flush=True)
    assert chunks == ["no terminator here"]
    assert rem == ""


def test_clause_break_lets_synthesis_start_early():
    chunks, rem = split_for_tts("First part, and the rest")
    assert chunks == ["First part,"]
    assert rem == "and the rest"
