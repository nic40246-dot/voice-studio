import numpy as np
import soundfile as sf
import pytest
from app.core.voice_manager import VoiceProfileManager


def test_voice_profile_lifecycle(tmp_path):
    profiles_dir = tmp_path / "profiles"
    mgr = VoiceProfileManager(profiles_dir=profiles_dir)

    # Generate a dummy reference audio sample (6 seconds, 24kHz)
    sr = 24000
    t = np.linspace(0, 6.0, int(sr * 6.0), endpoint=False)
    audio = 0.4 * np.sin(2 * np.pi * 300 * t)
    sample_file = tmp_path / "sample.wav"
    sf.write(str(sample_file), audio, sr, subtype="PCM_16")

    # Create profile
    profile = mgr.create_profile(
        name="Executive Voice EN",
        source_audio_path=sample_file,
        primary_language="en",
        description="Studio sample",
    )

    assert profile["id"] is not None
    assert profile["name"] == "Executive Voice EN"
    assert (profiles_dir / profile["id"] / "reference.wav").exists()

    # List profiles
    all_profiles = mgr.list_profiles()
    assert len(all_profiles) == 1
    assert all_profiles[0]["id"] == profile["id"]

    # Delete profile
    deleted = mgr.delete_profile(profile["id"])
    assert deleted is True
    assert len(mgr.list_profiles()) == 0
    assert not (profiles_dir / profile["id"]).exists()
