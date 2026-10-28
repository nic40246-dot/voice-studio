"""
Dataset Curator for Chatterbox / T3 Fine-Tuning.
Processes raw speech recordings, performs VAD silence trimming, slices into 3-12s utterances,
resamples to 24 kHz mono, and transcribes with Whisper to generate an LJSpeech-formatted dataset.
"""

import csv
import os
import re
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import soundfile as sf
import torch


def trim_silence_vad(y: np.ndarray, top_db: int = 30) -> np.ndarray:
    """Trims leading and trailing silence using librosa energy thresholds."""
    if len(y) == 0:
        return y
    trimmed, _ = librosa.effects.trim(y, top_db=top_db)
    return trimmed


def slice_audio_chunks(
    y: np.ndarray,
    sr: int = 24000,
    min_chunk_s: float = 2.5,
    max_chunk_s: float = 11.0,
    split_top_db: int = 28,
) -> list[np.ndarray]:
    """
    Slices a continuous audio recording into natural utterance chunks bounded between
    min_chunk_s and max_chunk_s at pause intervals.
    """
    # Find non-silent intervals
    intervals = librosa.effects.split(y, top_db=split_top_db, frame_length=2048, hop_length=512)
    chunks = []
    current_chunk = []
    current_samples = 0

    max_samples = int(max_chunk_s * sr)
    min_samples = int(min_chunk_s * sr)

    for start_idx, end_idx in intervals:
        seg = y[start_idx:end_idx]
        seg_len = len(seg)

        if current_samples + seg_len <= max_samples:
            current_chunk.append(seg)
            current_samples += seg_len
        else:
            if current_samples >= min_samples:
                concatenated = np.concatenate(current_chunk)
                chunks.append(concatenated)
            current_chunk = [seg]
            current_samples = seg_len

    if current_chunk and current_samples >= min_samples:
        chunks.append(np.concatenate(current_chunk))

    return chunks


def curate_dataset_from_audio(
    source_audio_paths: list[str],
    output_dir: str = "data/finetune_dataset",
    whisper_model_name: str = "openai/whisper-tiny",
    target_sr: int = 24000,
    language: str = "en",
) -> dict:
    """
    Takes a list of audio files, slices them into training clips, transcribes them with Whisper,
    and produces `wavs/` directory and `metadata.csv` in LJSpeech format.
    """
    out_path = Path(output_dir)
    wavs_dir = out_path / "wavs"
    wavs_dir.mkdir(parents=True, exist_ok=True)
    metadata_csv = out_path / "metadata.csv"

    # Load Whisper ASR
    from transformers import pipeline
    device = "cuda" if torch.cuda.is_available() else "cpu"
    asr_pipe = pipeline("automatic-speech-recognition", model=whisper_model_name, device=device)

    records = []
    clip_idx = 0
    total_duration_s = 0.0

    for src_path_str in source_audio_paths:
        src_path = Path(src_path_str)
        if not src_path.exists():
            continue

        y, sr = sf.read(str(src_path))
        if y.ndim > 1:
            y = np.mean(y, axis=1)

        # Resample to 24,000 Hz if needed
        if sr != target_sr:
            y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
            sr = target_sr

        y = trim_silence_vad(y, top_db=28)
        chunks = slice_audio_chunks(y, sr=target_sr)

        for chunk in chunks:
            # Apply 10ms micro-fade to avoid edge clicks
            fade_len = int(target_sr * 0.010)
            if len(chunk) > fade_len * 2:
                chunk[:fade_len] *= np.linspace(0.0, 1.0, fade_len)
                chunk[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)

            clip_filename = f"utterance_{clip_idx:05d}.wav"
            clip_path = wavs_dir / clip_filename
            sf.write(str(clip_path), chunk, target_sr, subtype="PCM_16")

            # Transcribe with Whisper
            transcription = asr_pipe(str(clip_path))["text"].strip()
            # Clean transcription
            norm_transcription = re.sub(r'[^\w\s\',.?!-]', '', transcription).strip()

            if len(norm_transcription.split()) >= 3:
                records.append({
                    "id": clip_path.stem,
                    "text": transcription,
                    "normalized_text": norm_transcription,
                })
                duration = len(chunk) / target_sr
                total_duration_s += duration
                clip_idx += 1

    # Write metadata.csv (LJSpeech standard)
    with open(metadata_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="|")
        for rec in records:
            writer.writerow([rec["id"], rec["text"], rec["normalized_text"]])

    return {
        "output_dir": str(out_path),
        "total_clips": len(records),
        "total_duration_minutes": round(total_duration_s / 60.0, 2),
        "metadata_file": str(metadata_csv),
    }


if __name__ == "__main__":
    import sys
    print("Dataset Curator Initialized.")
