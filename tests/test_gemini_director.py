import pytest
from app.core.gemini_director import TONE_STYLES, _get_api_credentials, humanize_script_with_gemini

def test_gemini_credentials_and_styles():
    base_url, api_key, model_name = _get_api_credentials()
    assert base_url is not None
    assert "ag/gemini" in model_name or "gemini" in model_name
    assert "engaging" in TONE_STYLES
    assert "energetic_hook" in TONE_STYLES
    assert "deep_dive" in TONE_STYLES
    assert "key_takeaway" in TONE_STYLES

def test_gemini_humanize_script_live():
    base_url, api_key, model_name = _get_api_credentials()
    if not api_key:
        pytest.skip("No Gemini API key available in test environment")
    
    dry_text = "Sales up 15%. Churn at 1%."
    result = humanize_script_with_gemini(dry_text, language="en", tone="energetic_hook")
    assert isinstance(result, str)
    assert len(result) > len(dry_text)
    assert any(c in result for c in [".", "!", "—", "...", ":"])


def test_heuristic_tone_distribution():
    from app.core.gemini_director import detect_slide_tone_heuristic
    h_title = detect_slide_tone_heuristic("Title Slide", 0, 10)
    assert h_title["tone_style"] == "energetic_hook"
    assert h_title["exaggeration"] >= 0.95

    h_data = detect_slide_tone_heuristic("API latency 45ms and 99.9% availability", 4, 10)
    assert h_data["tone_style"] == "deep_dive"
    assert h_data["exaggeration"] <= 0.75

    h_end = detect_slide_tone_heuristic("Summary and conclusion", 9, 10)
    assert h_end["tone_style"] == "key_takeaway"


def test_auto_direct_slide_with_gemini():
    from app.core.gemini_director import auto_direct_slide_with_gemini
    res = auto_direct_slide_with_gemini("Welcome everyone to our presentation", 0, 5, language="en")
    assert "tone_style" in res
    assert "exaggeration" in res
    assert "speed" in res
    assert "narration" in res
    assert "reason" in res

