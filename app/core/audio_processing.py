import os
import re
import subprocess
from pathlib import Path
import librosa
import numpy as np
import soundfile as sf
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

from app.config import (
    DEFAULT_SAMPLE_RATE,
    TARGET_LOUDNESS_DBFS,
    MIN_SAMPLE_DURATION_SEC,
    MAX_SAMPLE_DURATION_SEC,
)


def load_audio_array(file_path: str | Path) -> tuple[np.ndarray, int]:
    """
    Robust audio loader supporting WAV, MP3, M4A (AAC/ALAC), FLAC, OGG.
    Uses soundfile first; falls back to pydub/ffmpeg for container formats like M4A.
    """
    file_path = str(Path(file_path).resolve())
    try:
        data, sr = sf.read(file_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data.astype(np.float32), int(sr)
    except Exception:
        seg = AudioSegment.from_file(file_path)
        sr = int(seg.frame_rate)
        samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
        if seg.channels > 1:
            samples = samples.reshape((-1, seg.channels)).mean(axis=1)
        max_val = float(1 << (seg.sample_width * 8 - 1))
        data = samples / max_val
        return data, sr


def validate_audio_sample(file_path: str | Path) -> dict:
    file_path = Path(file_path)
    if not file_path.exists():
        return {"valid": False, "error": f"File does not exist: {file_path}"}

    try:
        data, sr = load_audio_array(file_path)

        duration = len(data) / sr
        peak = np.max(np.abs(data)) if len(data) > 0 else 0.0
        peak_db = 20 * np.log10(peak) if peak > 1e-7 else -100.0

        rms = np.sqrt(np.mean(data**2)) if len(data) > 0 else 0.0
        rms_db = 20 * np.log10(rms) if rms > 1e-7 else -100.0

        warnings = []
        if duration < MIN_SAMPLE_DURATION_SEC:
            warnings.append(f"Sample is too short ({duration:.1f}s). Minimum {MIN_SAMPLE_DURATION_SEC}s recommended for voice cloning.")
        elif duration > MAX_SAMPLE_DURATION_SEC:
            warnings.append(f"Sample is long ({duration:.1f}s). Using first {MAX_SAMPLE_DURATION_SEC}s is recommended.")

        if peak > 0.99:
            warnings.append("Audio sample contains digital clipping. Speak slightly further from microphone.")
        elif rms_db < -35.0:
            warnings.append("Audio level is quiet. Automatic gain normalization will boost the signal.")

        return {
            "valid": bool(duration >= MIN_SAMPLE_DURATION_SEC and rms > 1e-5),
            "duration": float(duration),
            "sample_rate": int(sr),
            "peak_db": float(round(peak_db, 1)),
            "rms_db": float(round(rms_db, 1)),
            "warnings": warnings,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def clean_audio_sample(input_path: str | Path, output_path: str | Path, target_sr: int = DEFAULT_SAMPLE_RATE) -> str:
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())

    # Load via pydub for robust format handling (mp3, wav, m4a)
    seg = AudioSegment.from_file(input_path)
    seg = seg.set_channels(1).set_frame_rate(target_sr)

    # Trim leading and trailing silence (< -42 dBFS)
    start_trim = detect_leading_silence(seg, silence_threshold=-42.0)
    end_trim = detect_leading_silence(seg.reverse(), silence_threshold=-42.0)
    duration_ms = len(seg)

    trimmed = seg[start_trim : duration_ms - end_trim]
    if len(trimmed) < 1000:  # fallback if over-trimmed
        trimmed = seg

    # Loudness normalization to target dBFS
    change_in_gain = TARGET_LOUDNESS_DBFS - trimmed.dBFS
    normalized = trimmed.apply_gain(change_in_gain)

    # Export clean 16-bit PCM WAV
    normalized.export(output_path, format="wav", parameters=["-acodec", "pcm_s16le"])
    return output_path


def adjust_audio_speed(input_path: str | Path, output_path: str | Path, speed_factor: float = 1.0) -> str:
    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())

    if abs(speed_factor - 1.0) < 0.02:
        if input_path != output_path:
            import shutil
            shutil.copy2(input_path, output_path)
        return output_path

    # Clamp speed factor between 0.5x and 2.0x
    speed = max(0.5, min(2.0, speed_factor))

    # Use ffmpeg atempo filter for pitch-preserving WSOLA time stretch
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"atempo={speed:.3f}",
        "-vn", output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path


def trim_trailing_noise(
    audio: np.ndarray,
    sr: int = DEFAULT_SAMPLE_RATE,
    silence_gap_ms: float = 200.0,
    thresh_db: float = -34.0,
    pad_ms: float = 30.0,
) -> np.ndarray:
    """
    Trims trailing hallucinated vocoder noise, rumble, and post-speech tail artifacts.
    Preserves all internal sentence pauses (commas, colons, rhetorical pauses).
    Only prunes trailing silence or isolated tail bursts after speech has finished.
    """
    if len(audio) < int(0.10 * sr):
        return audio

    hop = int(0.010 * sr)
    win = int(0.025 * sr)
    pad_samples = int((pad_ms / 1000.0) * sr)
    thresh = 10.0 ** (thresh_db / 20.0)

    # 1. Compute frame energy across entire clip
    frames_rms = []
    frames_pos = []
    for i in range(0, len(audio) - win, hop):
        frames_rms.append(float(np.sqrt(np.mean(audio[i : i + win] ** 2))))
        frames_pos.append(i)

    if not frames_rms:
        return audio

    peak_rms = max(frames_rms)
    adaptive_thresh = max(thresh, peak_rms * 0.06)

    active = [r > adaptive_thresh for r in frames_rms]
    if not any(active):
        return audio

    # 2. Identify active speech clusters to distinguish internal pauses from trailing bursts
    clusters = []
    in_c = False
    start_c = 0
    for idx, act in enumerate(active):
        if act and not in_c:
            in_c = True
            start_c = idx
        elif not act and in_c:
            in_c = False
            clusters.append((start_c, idx - 1))
    if in_c:
        clusters.append((start_c, len(active) - 1))

    # 3. Prune trailing post-speech burst artifacts backwards:
    # If the last cluster is separated from the previous speech by >= silence_gap_ms (280ms)
    # and is either short (< 280ms) or low energy (< 15% of peak RMS), it is a post-speech vocoder tail artifact.
    gap_sec = silence_gap_ms / 1000.0
    while len(clusters) > 1:
        last_start_idx, last_end_idx = clusters[-1]
        prev_end_idx = clusters[-2][1]
        last_dur = (frames_pos[last_end_idx] - frames_pos[last_start_idx]) / sr
        gap_before_last = (frames_pos[last_start_idx] - frames_pos[prev_end_idx]) / sr
        last_peak = max(frames_rms[last_start_idx : last_end_idx + 1])
        if gap_before_last >= gap_sec and (last_dur < 0.35 or last_peak < peak_rms * 0.20):
            clusters.pop()
        else:
            break

    final_cluster = clusters[-1]
    speech_end_pos = frames_pos[final_cluster[1]] + win
    cutoff = min(len(audio), speech_end_pos + pad_samples)
    trimmed = audio[:cutoff].copy()

    # 4. Apply soft cosine fade-out on the tail to prevent boundary clicks
    tail_fade_len = min(int(0.015 * sr), len(trimmed))
    if tail_fade_len > 0:
        fade_curve = np.cos(np.linspace(0, np.pi / 2, tail_fade_len)) ** 2
        trimmed[-tail_fade_len:] *= fade_curve

    return trimmed


def trim_leading_noise(
    audio: np.ndarray,
    sr: int = DEFAULT_SAMPLE_RATE,
    thresh_db: float = -34.0,
    pad_ms: float = 20.0,
) -> np.ndarray:
    """
    Trims leading hallucinated vocoder noise, breath pops, and pre-speech artifacts.
    Preserves natural speech attack by leaving a gentle pad before active speech.
    """
    if len(audio) < int(0.10 * sr):
        return audio

    hop = int(0.010 * sr)
    win = int(0.025 * sr)
    pad_samples = int((pad_ms / 1000.0) * sr)
    thresh = 10.0 ** (thresh_db / 20.0)

    frames_rms = []
    frames_pos = []
    for i in range(0, len(audio) - win, hop):
        frames_rms.append(float(np.sqrt(np.mean(audio[i : i + win] ** 2))))
        frames_pos.append(i)

    if not frames_rms:
        return audio

    peak_rms = max(frames_rms)
    adaptive_thresh = max(thresh, peak_rms * 0.08)

    active = [r > adaptive_thresh for r in frames_rms]
    if not any(active):
        return audio

    first_active_frame = active.index(True)
    speech_start_pos = frames_pos[first_active_frame]
    start_cut = max(0, speech_start_pos - pad_samples)
    trimmed = audio[start_cut:].copy()

    head_fade_len = min(int(0.015 * sr), len(trimmed))
    if head_fade_len > 0:
        fade_curve = np.sin(np.linspace(0, np.pi / 2, head_fade_len)) ** 2
        trimmed[:head_fade_len] *= fade_curve

    return trimmed


def apply_micro_fade(audio: np.ndarray, fade_ms: float = 5.0, sample_rate: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
    fade_len = int((fade_ms / 1000.0) * sample_rate)
    if len(audio) < fade_len * 2 or fade_len < 2:
        return audio
    fade_in = np.sin(np.linspace(0, np.pi / 2, fade_len, endpoint=False)) ** 2
    fade_out = np.cos(np.linspace(0, np.pi / 2, fade_len, endpoint=False)) ** 2
    out = audio.copy()
    out[:fade_len] = out[:fade_len] * fade_in
    out[-fade_len:] = out[-fade_len:] * fade_out
    return out


def normalize_peak(audio: np.ndarray, target_dbfs: float = -1.0) -> np.ndarray:
    peak = np.max(np.abs(audio)) if len(audio) > 0 else 0.0
    if peak > 1e-5:
        target_amp = 10.0 ** (target_dbfs / 20.0)
        return (audio / peak) * target_amp
    return audio


def generate_silence_wav(output_path: str | Path, duration_ms: int = 300, sample_rate: int = DEFAULT_SAMPLE_RATE):
    samples = int((duration_ms / 1000.0) * sample_rate)
    silence = np.zeros(samples, dtype=np.int16)
    sf.write(str(output_path), silence, sample_rate, subtype="PCM_16")
    return str(output_path)


def convert_wav_to_mp3(wav_path: str | Path, mp3_path: str | Path, bitrate: str = "192k") -> str:
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_path),
        "-codec:a", "libmp3lame", "-b:a", bitrate,
        str(mp3_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return str(mp3_path)


def apply_notch_filter(
    audio: np.ndarray,
    freq: float = 4900.0,
    q: float = 15.0,
    sr: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    """
    Applies a narrow IIR notch filter to remove stationary vocoder tones (e.g., S3Gen 4900 Hz resonance).
    """
    if len(audio) < 16:
        return audio
    try:
        import scipy.signal as sp_signal
        w0 = freq / (sr / 2.0)
        if 0.0 < w0 < 1.0:
            b, a = sp_signal.iirnotch(w0, q)
            return sp_signal.filtfilt(b, a, audio).astype(np.float32)
    except Exception:
        pass
    return audio


def crossfade_concat(audio_list: list[np.ndarray], crossfade_ms: float = 20.0, sr: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
    """
    Concatenates a list of audio arrays using an equal-power crossfade across phrase boundaries
    to eliminate digital clicks, phase jumps, and synthetic boundary edges.
    """
    valid = [a for a in audio_list if len(a) > 0]
    if not valid:
        return np.array([], dtype=np.float32)
    if len(valid) == 1:
        return valid[0]

    fade_len = int((crossfade_ms / 1000.0) * sr)
    if fade_len <= 0:
        return np.concatenate(valid)

    out = valid[0]
    for nxt in valid[1:]:
        cur_fade = min(fade_len, len(out), len(nxt))
        if cur_fade <= 0:
            out = np.concatenate([out, nxt])
            continue

        t = np.linspace(0.0, 1.0, cur_fade, endpoint=True)
        fade_out = np.cos(0.5 * np.pi * t)
        fade_in = np.sin(0.5 * np.pi * t)

        overlap = (out[-cur_fade:] * fade_out) + (nxt[:cur_fade] * fade_in)
        out = np.concatenate([out[:-cur_fade], overlap, nxt[cur_fade:]])

    return out


def extract_optimal_reference_audio(audio_path: str | Path, target_sec: float = 10.0) -> str:
    p = Path(audio_path).resolve()
    if not p.exists():
        return str(audio_path)

    opt_path = p.parent / f"{p.stem}_optimal.wav"
    if opt_path.exists() and opt_path.stat().st_mtime >= p.stat().st_mtime:
        return str(opt_path)

    try:
        y, sr = sf.read(str(p))
        if y.ndim > 1:
            y = y[:, 0]
        y = y.astype(np.float32)
        total_sec = len(y) / sr
        if total_sec <= target_sec:
            return str(p)

        win_samples = int(target_sec * sr)
        step_samples = int(1.0 * sr)
        best_score = -1.0
        best_start = 0

        # Fast scan across 1-second hops
        for start in range(0, len(y) - win_samples + 1, step_samples):
            segment = y[start : start + win_samples]
            rms = float(np.sqrt(np.mean(segment**2)))
            f0, _, _ = librosa.pyin(
                segment,
                fmin=librosa.note_to_hz("C2"),
                fmax=librosa.note_to_hz("C6"),
                sr=sr,
            )
            vf0 = f0[~np.isnan(f0)]
            voiced_ratio = len(vf0) / len(f0) if len(f0) > 0 else 0.0
            med_f0 = float(np.median(vf0)) if len(vf0) > 0 else 0.0
            std_f0 = float(np.std(vf0)) if len(vf0) > 0 else 0.0

            # Conversational penalty for vocal fry (<88 Hz) to avoid overly bold/heavy monotone
            fry_penalty = 1.0 if med_f0 >= 92.0 else max(0.5, med_f0 / 92.0)
            # Dynamics reward for natural pitch movement
            dyn_reward = min(1.2, max(0.9, std_f0 / 16.0)) if std_f0 > 0 else 1.0

            score = voiced_ratio * min(rms / 0.03, 1.5) * fry_penalty * dyn_reward
            if score > best_score:
                best_score = score
                best_start = start

        optimal_segment = y[best_start : best_start + win_samples]
        optimal_segment = apply_micro_fade(optimal_segment, fade_ms=10.0, sample_rate=sr)
        sf.write(str(opt_path), optimal_segment, sr, subtype="PCM_16")
        return str(opt_path)
    except Exception:
        # Graceful fallback to original file if analysis fails
        return str(p)


# Linguistic function words that MUST NEVER have a pause (..., —, –, ,, :) immediately following them
_FUNCTION_WORDS = {
    # Prepositions (English)
    'by', 'to', 'in', 'at', 'on', 'with', 'for', 'about', 'from', 'into', 'through',
    'during', 'before', 'after', 'above', 'below', 'between', 'under', 'without',
    'over', 'across', 'behind', 'beyond', 'towards', 'upon', 'within', 'per',
    # Determiners / Articles
    'a', 'an', 'the', 'this', 'that', 'these', 'those', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
    # Subordinating / Coordinating Conjunctions
    'whether', 'if', 'because', 'although', 'since', 'unless', 'while', 'whereas',
    'that', 'which', 'who', 'whom', 'whose', 'and', 'or', 'nor', 'but',
    # Auxiliaries / Modals
    'will', 'would', 'shall', 'should', 'can', 'could', 'may', 'might', 'must',
    'is', 'are', 'was', 'were', 'am', 'be', 'been', 'being',
    'has', 'have', 'had', 'do', 'does', 'did',
    # German functional words
    'von', 'vom', 'zu', 'zum', 'zur', 'in', 'im', 'an', 'am', 'auf', 'mit', 'für',
    'vor', 'nach', 'über', 'unter', 'aus', 'bei', 'beim', 'durch', 'gegen', 'ohne', 'um',
    'ein', 'eine', 'einer', 'eines', 'einem', 'einen',
    'der', 'die', 'das', 'den', 'dem', 'des', 'dieser', 'diese', 'dieses',
    'mein', 'meine', 'dein', 'deine', 'sein', 'seine', 'ihr', 'ihre', 'unser', 'unsere',
    'während', 'ob', 'weil', 'obwohl', 'da', 'dass', 'wenn', 'als', 'und', 'oder', 'aber',
    'wird', 'werden', 'wurde', 'ist', 'sind', 'war', 'waren', 'kann', 'können', 'soll', 'sollte', 'muss', 'müssen',
}

_FUNCTION_WORDS_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in sorted(_FUNCTION_WORDS, key=len, reverse=True)) + r')\s*([.]{2,}|—|–|,|:)\s+',
    re.IGNORECASE
)


def clean_prosody_boundaries(text: str) -> str:
    """
    Enforces syntactic prosodic boundary rules across English and German text.
    Removes unnatural pauses (ellipses, dashes, commas, colons) that split functional heads
    (prepositions, articles, auxiliary verbs, conjunctions) from their dependent clauses.
    Example: 'By... remaining in the meeting' -> 'By remaining in the meeting'
    """
    if not text:
        return text

    def repl(m):
        return f"{m.group(1)} "

    cleaned = _FUNCTION_WORDS_PATTERN.sub(repl, text)
    cleaned = re.sub(r' +', ' ', cleaned)
    return cleaned


