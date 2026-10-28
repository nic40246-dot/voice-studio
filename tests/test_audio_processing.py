import os
from pathlib import Path
import numpy as np
import soundfile as sf
import pytest

from app.core.audio_processing import (
    validate_audio_sample,
    clean_audio_sample,
    adjust_audio_speed,
    convert_wav_to_mp3,
    generate_silence_wav,
    apply_micro_fade,
    normalize_peak,
)


def test_audio_validation_and_cleaning(tmp_path):
    # Create synthetic test tone (5 seconds, 24kHz)
    sr = 24000
    duration = 5.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Sine wave with amplitude 0.5 (-6 dBFS)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t)

    raw_wav = tmp_path / "raw_tone.wav"
    sf.write(str(raw_wav), audio, sr, subtype="PCM_16")

    # 1. Validation test
    val = validate_audio_sample(raw_wav)
    assert val["valid"] is True
    assert abs(val["duration"] - 5.0) < 0.1
    assert val["sample_rate"] == 24000

    # 2. Clean and normalize test
    clean_wav = tmp_path / "clean_tone.wav"
    clean_audio_sample(raw_wav, clean_wav)
    assert clean_wav.exists()

    clean_data, clean_sr = sf.read(str(clean_wav))
    assert clean_sr == 24000
    assert len(clean_data) > 0

    # 3. Time stretch test (1.25x speed)
    speed_wav = tmp_path / "speed_tone.wav"
    adjust_audio_speed(clean_wav, speed_wav, speed_factor=1.25)
    assert speed_wav.exists()
    speed_data, _ = sf.read(str(speed_wav))
    # 1.25x speed means duration is roughly 5.0 / 1.25 = 4.0s
    assert len(speed_data) < len(clean_data)

    # 4. MP3 conversion test
    mp3_file = tmp_path / "test_out.mp3"
    convert_wav_to_mp3(clean_wav, mp3_file)
    assert mp3_file.exists()
    assert os.path.getsize(str(mp3_file)) > 1000

    # 5. Micro-fade and peak normalization
    faded = apply_micro_fade(clean_data, fade_ms=5.0, sample_rate=24000)
    assert len(faded) == len(clean_data)
    assert abs(faded[0]) < 1e-4

    peaked = normalize_peak(faded, target_dbfs=-1.0)
    max_peak = np.max(np.abs(peaked))
    target_amp = 10.0 ** (-1.0 / 20.0)
    assert abs(max_peak - target_amp) < 0.05


def test_m4a_audio_validation_and_cleaning(tmp_path):
    import subprocess
    sr = 24000
    duration = 4.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = 0.5 * np.sin(2 * np.pi * 350 * t)
    raw_wav = tmp_path / "source.wav"
    sf.write(str(raw_wav), audio, sr, subtype="PCM_16")

    raw_m4a = tmp_path / "voice_sample.m4a"
    subprocess.run(["ffmpeg", "-y", "-i", str(raw_wav), "-c:a", "aac", str(raw_m4a)], check=True, capture_output=True)
    assert raw_m4a.exists()

    # Validate M4A sample
    val = validate_audio_sample(raw_m4a)
    assert val["valid"] is True
    assert abs(val["duration"] - 4.0) < 0.2
    assert val["sample_rate"] == 24000
    assert val["rms_db"] > -30.0

    # Clean and convert M4A sample to standardized PCM WAV
    clean_wav = tmp_path / "reference.wav"
    clean_audio_sample(raw_m4a, clean_wav)
    assert clean_wav.exists()
    c_data, c_sr = sf.read(str(clean_wav))
    assert c_sr == 24000
    assert len(c_data) > 0


def test_extract_optimal_reference_audio(tmp_path):
    from app.core.audio_processing import extract_optimal_reference_audio

    sr = 24000
    # Create 15-second synthetic speech-like tone with silent intro (0-5s) and voiced signal (5-15s)
    total_len = int(15.0 * sr)
    audio = np.zeros(total_len, dtype=np.float32)
    t = np.linspace(0, 10.0, int(10.0 * sr), endpoint=False)
    # Voiced tone at 120 Hz
    audio[int(5.0 * sr) :] = 0.4 * np.sin(2 * np.pi * 120 * t)

    test_wav = tmp_path / "long_reference.wav"
    sf.write(str(test_wav), audio, sr, subtype="PCM_16")

    opt_path = extract_optimal_reference_audio(test_wav, target_sec=6.0)
    assert Path(opt_path).exists()
    opt_data, opt_sr = sf.read(opt_path)
    assert opt_sr == sr
    # Optimal audio must be 6 seconds and non-empty
    assert abs(len(opt_data) / sr - 6.0) < 0.1
    assert np.max(np.abs(opt_data)) > 0.1


