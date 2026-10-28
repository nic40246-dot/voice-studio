from pathlib import Path
import soundfile as sf
import pytest

from app.core.tts_engine import TTSEngine


def test_clean_text_and_split_into_chunks_with_paragraph_pause():
    engine = TTSEngine.get_instance()

    # Test 1: Clean text currency, percent, bullet stripping
    raw_slide_text = "• Slide point with $5M and 10% ROI & AI platform."
    cleaned = engine._clean_text_for_synthesis(raw_slide_text, lang="en")
    assert "•" not in cleaned
    assert "5 million dollars" in cleaned
    assert "10 percent" in cleaned
    assert " and " in cleaned

    # Test 2: Two lines down creates distinct chunks with paragraph pause (>= 650ms)
    multi_paragraph = """Welcome to our presentation.

Today we will cover the three major milestones. We achieved record results."""

    chunks = engine._split_into_chunks(multi_paragraph, lang="en", default_pause_ms=250)
    assert len(chunks) == 3
    # Chunk 0 is the first paragraph sentence, followed by two lines down:
    assert chunks[0][0] == "Welcome to our presentation."
    assert chunks[0][1] >= 650, f"Expected paragraph pause >= 650ms, got {chunks[0][1]}ms"

    # Chunk 1 is the first sentence of second paragraph:
    assert chunks[1][0] == "Today we will cover the three major milestones."
    assert chunks[1][1] == 250, f"Expected standard sentence pause 250ms, got {chunks[1][1]}ms"

    # Chunk 2 is the last sentence:
    assert chunks[2][0] == "We achieved record results."
    assert chunks[2][1] == 0, f"Expected 0ms after final chunk, got {chunks[2][1]}ms"

    # Test 3: Ellipses creates rhetorical pause (>= 800ms)
    ellipsis_text = "Wait for it... here comes the result."
    e_chunks = engine._split_into_chunks(ellipsis_text, lang="en", default_pause_ms=250)
    assert len(e_chunks) == 2
    assert e_chunks[0][1] >= 800


def test_tts_synthesis_en_and_de():
    engine = TTSEngine.get_instance()

    # 1. English synthesis test
    wav_en = engine.generate_speech(
        text="Welcome to the executive presentation. Performance is on track.",
        language="en",
        speed=1.0,
        pause_duration_ms=250,
    )
    assert Path(wav_en).exists()
    data_en, sr_en = sf.read(wav_en)
    assert sr_en == 24000
    assert len(data_en) > 24000  # at least 1 second

    # 2. German synthesis test
    wav_de = engine.generate_speech(
        text="Willkommen zur Präsentation. Alle Systeme laufen einwandfrei.",
        language="de",
        speed=1.0,
        pause_duration_ms=250,
    )
    assert Path(wav_de).exists()
    data_de, sr_de = sf.read(wav_de)
    assert sr_de == 24000
    assert len(data_de) > 24000
