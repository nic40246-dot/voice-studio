import pytest
from app.core.pronunciation import PronunciationManager


def test_pronunciation_rules(tmp_path):
    rules_file = tmp_path / "rules.json"
    mgr = PronunciationManager(file_path=rules_file)

    # Test default English rules
    text_en = "We built a new SaaS platform with a modern API."
    applied_en = mgr.apply(text_en, "en")
    assert "Sass" in applied_en
    assert "A P I" in applied_en

    # Test default German rules
    text_de = "Das neue B2B System unterstützt KI und Teams."
    applied_de = mgr.apply(text_de, "de")
    assert "B to B" in applied_de
    assert "K I" in applied_de
    assert "Teems" in applied_de

    # Test dynamic custom rule
    mgr.set_rule("en", "Q4", "Quarter Four")
    custom_applied = mgr.apply("Targets for Q4 are set.", "en")
    assert "Quarter Four" in custom_applied

    # Test automatic acronym expansion (couples of capital letters)
    acronym_text = "AI and ML models optimize CPU and GPU performance across multiple APIs."
    acronym_applied = mgr.apply(acronym_text, "en")
    assert "Ay-Eye" in acronym_applied
    assert "M L" in acronym_applied
    assert "C P U" in acronym_applied
    assert "G P U" in acronym_applied
    assert "A P I s" in acronym_applied

    # Test dotted abbreviations
    dotted_text = "Partners in the U.S.A. utilize advanced A.I. tools."
    dotted_applied = mgr.apply(dotted_text, "en")
    assert "U S A" in dotted_applied
    assert "Ay-Eye" in dotted_applied

    # Test SEFE pronunciation override (2-syllable bisyllabic mapping)
    sefe_text = "At SEFE and Sefe and S.E.F.E. and S-E-F-E we lead energy."
    sefe_applied = mgr.apply(sefe_text, "en")
    assert "Sefe" in sefe_applied
    assert "S-E-F-E" not in sefe_applied
    assert "S E F E" not in sefe_applied
    assert "S.E.F.E." not in sefe_applied

    # Test GPT pronunciation override
    gpt_text = "Running GPT-4 with G.P.T. and Gpt."
    gpt_applied = mgr.apply(gpt_text, "en")
    assert "Gee Pee Tee" in gpt_applied
    assert "G.P.T." not in gpt_applied
    assert "G P T" not in gpt_applied
