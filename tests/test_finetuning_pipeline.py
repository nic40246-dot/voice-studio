"""
Unit tests for Dataset Curator and LoRA Fine-Tuning Pipeline.
"""

import numpy as np
import pytest
import torch
import torch.nn as nn

from tools.dataset_curator import trim_silence_vad, slice_audio_chunks
from tools.train_lora import LoRATrainingConfig, build_t3_lora_model
from app.core.tts_engine import TTSEngine


def test_trim_silence_vad():
    sr = 24000
    # Create 0.5s silence + 1s tone + 0.5s silence
    silence = np.zeros(int(sr * 0.5), dtype=np.float32)
    tone = np.sin(2 * np.pi * 440 * np.linspace(0, 1, sr)).astype(np.float32) * 0.5
    audio = np.concatenate([silence, tone, silence])

    trimmed = trim_silence_vad(audio, top_db=30)
    assert len(trimmed) < len(audio)
    assert len(trimmed) >= int(sr * 0.9)


def test_slice_audio_chunks():
    sr = 24000
    # Create 3 spoken bursts separated by silence
    burst = np.sin(2 * np.pi * 440 * np.linspace(0, 3, sr * 3)).astype(np.float32) * 0.5
    silence = np.zeros(sr * 1, dtype=np.float32)
    stream = np.concatenate([burst, silence, burst, silence, burst])

    chunks = slice_audio_chunks(stream, sr=sr, min_chunk_s=2.0, max_chunk_s=5.0)
    assert len(chunks) >= 2
    for c in chunks:
        dur = len(c) / sr
        assert 1.5 <= dur <= 5.5


def test_lora_injection_on_dummy_transformer():
    class DummyLayer(nn.Module):
        def __init__(self):
            super().__init__()
            self.q_proj = nn.Linear(64, 64)
            self.k_proj = nn.Linear(64, 64)
            self.v_proj = nn.Linear(64, 64)
            self.o_proj = nn.Linear(64, 64)

    class DummyT3(nn.Module):
        def __init__(self):
            super().__init__()
            self.layer = DummyLayer()
            self.spkr_enc = nn.Linear(32, 64)
            self.text_emb = nn.Embedding(100, 64)
            self.text_head = nn.Linear(64, 100)

    dummy_t3 = DummyT3()
    cfg = LoRATrainingConfig(lora_r=8, lora_alpha=16)
    lora_model = build_t3_lora_model(dummy_t3, cfg)

    trainable = [name for name, p in lora_model.named_parameters() if p.requires_grad]
    assert any("lora" in name.lower() for name in trainable)
    assert any("text_emb" in name.lower() for name in trainable)


def test_tts_engine_model_status():
    engine = TTSEngine.get_instance()
    info = engine.get_model_info()
    assert "model_name" in info
    assert "is_custom" in info
    assert isinstance(info["is_custom"], bool)
