import os
import re
import uuid
from pathlib import Path
from typing import Optional
import numpy as np
import soundfile as sf
import torch
import torch.nn.functional as F

from app.config import AUDIO_CACHE_DIR, DEFAULT_SAMPLE_RATE, MODEL_DEVICE
from .audio_processing import (
    adjust_audio_speed,
    apply_micro_fade,
    apply_notch_filter,
    crossfade_concat,
    extract_optimal_reference_audio,
    normalize_peak,
    trim_trailing_noise,
    trim_leading_noise,
)
from app.core.pronunciation import PronunciationManager


class TTSEngine:
    _instance = None
    _model = None
    _active_model_name = "Stock Multilingual (23 Languages)"
    _active_model_path = None
    _is_custom_model = False

    def __init__(self):
        self.pronunciation_mgr = PronunciationManager()
        self.conditionals_cache = {}
        self._neutral_prompt_tokens = None
        # Intel Core i5-14500 tuning: 6 performance cores avoids E-core thread contention
        torch.set_num_threads(6)

    @classmethod
    def get_instance(cls) -> "TTSEngine":
        if cls._instance is None:
            cls._instance = TTSEngine()
        return cls._instance

    def load_model(self, custom_model_path: Optional[str] = None):
        if self._model is None:
            import chatterbox
            import os
            # Intel Core i5-14500 has exactly 6 Performance cores (P-cores).
            # Pin to 6 threads to avoid high-latency E-core thrashing.
            torch.set_num_threads(6)
            self._model = chatterbox.ChatterboxMultilingualTTS.from_pretrained(device=MODEL_DEVICE)
            if self._model.conds is not None and self._model.conds.t3.cond_prompt_speech_tokens is not None:
                self._neutral_prompt_tokens = self._model.conds.t3.cond_prompt_speech_tokens.clone()

        # Check for fine-tuned LoRA or custom model checkpoint
        target_custom = custom_model_path
        if target_custom is None and not self._is_custom_model:
            # Default auto-discovery path
            # Do not auto-inject t3_finetuned.safetensors by default.
            # Overfitted weights cause hallucinated start-tokens and pacing collapse.
            # Custom checkpoints must be explicitly requested via custom_model_path.
            pass

        if target_custom and Path(target_custom).exists():
            self._apply_custom_weights(target_custom)

        return self._model

    def _apply_custom_weights(self, weights_path: str):
        p = Path(weights_path)
        if not p.exists():
            return
        try:
            if p.suffix == ".safetensors":
                from safetensors.torch import load_file
                state_dict = load_file(str(p))
                if "model" in state_dict:
                    state_dict = state_dict["model"][0]
                self._model.t3.load_state_dict(state_dict, strict=False)
                self._active_model_name = f"Custom LoRA ({p.name})"
                self._active_model_path = str(p)
                self._is_custom_model = True
            elif p.is_dir() and (p / "adapter_config.json").exists():
                from peft import PeftModel
                self._model.t3 = PeftModel.from_pretrained(self._model.t3, str(p))
                self._active_model_name = f"PEFT LoRA ({p.name})"
                self._active_model_path = str(p)
                self._is_custom_model = True
        except Exception as e:
            print(f"Warning: Failed to load custom weights from {weights_path}: {e}")

    def get_model_info(self) -> dict:
        return {
            "model_name": self._active_model_name,
            "is_custom": self._is_custom_model,
            "path": self._active_model_path,
        }

    def switch_to_stock_model(self):
        """Reloads the pristine stock Hugging Face multilingual weights."""
        self._model = None
        self._is_custom_model = False
        self._active_model_name = "Stock Multilingual (23 Languages)"
        self._active_model_path = None
        return self.load_model()

    def _get_neutral_prompt_tokens(self, model):
        if self._neutral_prompt_tokens is not None:
            return self._neutral_prompt_tokens
        try:
            hub_path = Path.home() / ".cache" / "huggingface" / "hub"
            conds_files = list(hub_path.glob("**/conds.pt"))
            if conds_files:
                import chatterbox
                c = chatterbox.mtl_tts.Conditionals.load(conds_files[0], map_location="cpu")
                if c and c.t3 and c.t3.cond_prompt_speech_tokens is not None:
                    self._neutral_prompt_tokens = c.t3.cond_prompt_speech_tokens.clone()
                    return self._neutral_prompt_tokens
        except Exception:
            pass
        return None

    def is_loaded(self) -> bool:
        return self._model is not None

    def _clean_text_for_synthesis(self, text: str, lang: str = "en") -> str:
        if not text:
            return ""
        # Strip emojis and pictographs
        text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
        text = re.sub(r'[\u2600-\u27bf\u2300-\u23ff]', '', text)

        # Remove slide bullet symbols and list markers at line starts
        text = re.sub(r'(?m)^[\s\t]*[•◦▪▫►✔★*–—\-]+[\s\t]*', '', text)
        # Remove isolated bullet symbols mid-text
        text = re.sub(r'[•◦▪▫►✔★]', ' ', text)

        # Currency expansions (e.g. $5.2M -> 5.2 million dollars, $100 -> 100 dollars)
        def repl_usd(m):
            val = m.group(1)
            suffix = m.group(2) or ""
            unit = "Dollar" if lang.lower().startswith("de") else ("dollar" if val == "1" else "dollars")
            if suffix.lower() in ("m", "million"):
                suffix_word = "Millionen" if lang.lower().startswith("de") else "million"
                return f"{val} {suffix_word} {unit}"
            elif suffix.lower() in ("b", "billion", "mrd"):
                suffix_word = "Milliarden" if lang.lower().startswith("de") else "billion"
                return f"{val} {suffix_word} {unit}"
            elif suffix.lower() in ("k", "thousand", "tsd"):
                suffix_word = "Tausend" if lang.lower().startswith("de") else "thousand"
                return f"{val} {suffix_word} {unit}"
            return f"{val} {unit}"

        def repl_eur(m):
            val = m.group(1)
            suffix = m.group(2) or ""
            unit = "Euro" if lang.lower().startswith("de") else ("euro" if val == "1" else "euros")
            if suffix.lower() in ("m", "million"):
                suffix_word = "Millionen" if lang.lower().startswith("de") else "million"
                return f"{val} {suffix_word} {unit}"
            elif suffix.lower() in ("b", "billion", "mrd"):
                suffix_word = "Milliarden" if lang.lower().startswith("de") else "billion"
                return f"{val} {suffix_word} {unit}"
            elif suffix.lower() in ("k", "thousand", "tsd"):
                suffix_word = "Tausend" if lang.lower().startswith("de") else "thousand"
                return f"{val} {suffix_word} {unit}"
            return f"{val} {unit}"

        text = re.sub(r'\$\s*([0-9]+(?:[.,][0-9]+)?)\s*([kKmMbB](?:illion|n)?)?\b', repl_usd, text)
        text = re.sub(r'€\s*([0-9]+(?:[.,][0-9]+)?)\s*([kKmMbB](?:illion|rd)?)?\b', repl_eur, text)

        if lang.lower().startswith("de"):
            text = re.sub(r'£\s*([0-9]+(?:[.,][0-9]+)?)\b', r'\1 Pfund', text)
            text = re.sub(r'([0-9]+(?:[.,][0-9]+)?)\s*%', r'\1 Prozent', text)
            text = re.sub(r'\s*&\s*', ' und ', text)
        else:
            text = re.sub(r'£\s*([0-9]+(?:[.,][0-9]+)?)\b', r'\1 pounds', text)
            text = re.sub(r'([0-9]+(?:[.,][0-9]+)?)\s*%', r'\1 percent', text)
            text = re.sub(r'\s*&\s*', ' and ', text)

        # Normalize curly quotes and dashes
        text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        text = text.replace('—', ' - ').replace('–', ' - ')

        # Explicit acronym & phonetic term normalization
        text = re.sub(r'\bS[.\-\s]?E[.\-\s]?F[.\-\s]?E\b', 'Sefe', text, flags=re.IGNORECASE)
        text = re.sub(r'\bG[.\-\s]?P[.\-\s]?T\b', 'Gee Pee Tee', text, flags=re.IGNORECASE)
        text = re.sub(r'\bA[.\-]I\b', 'Ay-Eye', text, flags=re.IGNORECASE)
        text = re.sub(r'\bAI\b', 'Ay-Eye', text)

        # Collapse horizontal whitespace per line (keep \n intact)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()

    def _split_into_chunks(self, text: str, lang: str = "en", default_pause_ms: int = 250) -> list[tuple[str, int]]:
        """
        Splits text into chunks, preserving paragraph and line pauses.
        When the user enters two lines down (\\n\\n), a paragraph pause (650-750ms) is applied.
        When text contains ellipses (... or …), an explicit rhetorical pause (800ms) is applied.
        Never merges sentences across line breaks or paragraph breaks.
        Returns list of (chunk_text, pause_after_ms).
        """
        if not text:
            return []

        cleaned = self._clean_text_for_synthesis(text, lang=lang)
        if not cleaned:
            return []

        cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
        # Mark ellipses
        cleaned = re.sub(r'…|\.{3,}', ' __ELLIPSIS_BREAK__ ', cleaned)

        raw_paras = [p.strip() for p in re.split(r'\n\s*\n+', cleaned) if p.strip()]
        chunks: list[tuple[str, int]] = []

        for p_idx, para in enumerate(raw_paras):
            is_last_para = (p_idx == len(raw_paras) - 1)
            raw_lines = [ln.strip() for ln in para.split('\n') if ln.strip()]

            for l_idx, line in enumerate(raw_lines):
                is_last_line = (l_idx == len(raw_lines) - 1)

                # Split by ellipsis marker
                ellipsis_parts = [ep.strip() for ep in re.split(r'\s*__ELLIPSIS_BREAK__\s*', line) if ep.strip()]
                for e_idx, e_part in enumerate(ellipsis_parts):
                    is_last_in_ellipsis = (e_idx == len(ellipsis_parts) - 1)

                    # Split sentences by sentence-closing punctuation
                    sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', e_part) if s.strip()]
                    for s_idx, s in enumerate(sents):
                        if not s or not re.search(r'[\w\u00C0-\u017F]', s):
                            continue
                        is_last_sent = (s_idx == len(sents) - 1)

                        # Determine pause duration after this chunk
                        if not is_last_in_ellipsis and is_last_sent:
                            pause_ms = max(800, int(default_pause_ms * 2.5))
                        elif is_last_sent and is_last_line and not is_last_para:
                            # Two lines down / paragraph break pause
                            pause_ms = max(650, int(default_pause_ms * 2.5))
                        elif is_last_sent and not is_last_line:
                            # Single line break pause
                            pause_ms = max(400, int(default_pause_ms * 1.5))
                        else:
                            # Standard intra-paragraph sentence pause
                            pause_ms = default_pause_ms

                        # Ensure proper terminal punctuation
                        if s and s[-1] not in ".!?:;—–":
                            s += "."
                        if s[0].islower():
                            s = s[0].upper() + s[1:]

                        chunks.append((s, pause_ms))

        # The final chunk of the clip has 0ms trailing pause
        if chunks:
            chunks[-1] = (chunks[-1][0], 0)

        return chunks

    def generate_speech(
        self,
        text: str,
        language: str = "en",
        reference_audio_path: str | None = None,
        speed: float = 1.0,
        pause_duration_ms: int = 250,
        temperature: float = 0.82,
        cfg_weight: float = 0.35,
        exaggeration: float = 0.65,
        native_accent: bool = True,
        n_cfm_timesteps: int = 8,
        progress_callback=None,
        cancel_token=None,
    ) -> str:
        model = self.load_model()
        from chatterbox.models.t3.modules.cond_enc import T3Cond
        from chatterbox.mtl_tts import drop_invalid_tokens, punc_norm

        lang_code = "de" if language.lower().startswith("de") else "en"

        # Golden Ratio for engaging, natural, non-robotic delivery:
        # Exaggeration 0.70-0.78 boosts emotional range, pitch dynamism & consonant vitality.
        # CFG weight 0.20-0.38 frees rhythm and pitch from rigid robotic lock.
        # Temperature 0.80-0.82 provides melodic human pitch variance and micro-intonation.
        eff_cfg_weight = max(0.20, min(cfg_weight, 0.45))
        # Clamp temperature to [0.72, 0.78] to prevent attention drift, hallucinations, and pacing collapse
        eff_temperature = max(0.72, min(temperature, 0.78))
        eff_exaggeration = max(0.50, min(exaggeration, 0.80))

        # Enforce repetition penalty 1.20 (Chatterbox T3 native default).
        # Values > 1.4 heavily distort acoustic tokens, inducing token looping and repeating words at chunk tails.
        eff_repetition_penalty = 1.20

        # Automatically normalize syntactic prosody boundaries (removes fake pauses after function words)
        from app.core.audio_processing import clean_prosody_boundaries
        text = clean_prosody_boundaries(text)

        # Apply pronunciation substitutions
        processed_text = self.pronunciation_mgr.apply(text, lang_code)
        chunks = self._split_into_chunks(processed_text, lang=lang_code, default_pause_ms=pause_duration_ms)
        if not chunks:
            raise ValueError("Input text is empty")

        # Cache reference conditionals if audio prompt provided
        if reference_audio_path and Path(reference_audio_path).exists():
            ref_resolved = str(Path(reference_audio_path).resolve())
            eff_ref_path = extract_optimal_reference_audio(ref_resolved)
            cache_key = (eff_ref_path, round(float(eff_exaggeration), 2))
            if cache_key not in self.conditionals_cache:
                model.prepare_conditionals(eff_ref_path, exaggeration=float(eff_exaggeration))
                self.conditionals_cache[cache_key] = model.conds
            else:
                model.conds = self.conditionals_cache[cache_key]

        # Resolve effective speaker embedding (supports custom profile blended embeddings)
        effective_speaker_emb = model.conds.t3.speaker_emb
        if reference_audio_path:
            custom_emb_file = Path(reference_audio_path).resolve().parent / "speaker_emb.pt"
            if custom_emb_file.exists():
                try:
                    custom_emb = torch.load(str(custom_emb_file), map_location=model.device)
                    if custom_emb.ndim == 1:
                        custom_emb = custom_emb.unsqueeze(0)
                    effective_speaker_emb = custom_emb.to(model.device)
                except Exception:
                    pass

        # Select conditioning:
        # Prompt tokens from reference audio leak phonetic content ("hello everyone...").
        # Using Chatterbox pretrained neutral prompt tokens preserves pristine articulation
        # while speaker_emb ensures 100% clone timbre of the user's voice.
        neutral_tokens = self._get_neutral_prompt_tokens(model)
        selected_tokens = neutral_tokens if neutral_tokens is not None else model.conds.t3.cond_prompt_speech_tokens

        t3_cond_to_use = T3Cond(
            speaker_emb=effective_speaker_emb,
            cond_prompt_speech_tokens=selected_tokens.to(model.device),
            emotion_adv=model.conds.t3.emotion_adv,
        ).to(device=model.device)

        audio_parts = []
        total_chunks = len(chunks)
        for idx, (chunk, pause_ms) in enumerate(chunks):
            if cancel_token and cancel_token.is_cancelled:
                raise InterruptedError("Generation cancelled by user")

            if progress_callback:
                progress_callback(idx + 1, total_chunks, f"Synthesizing sentence {idx+1}/{total_chunks}...")

            # Clean and tokenize sentence
            # Use punc_norm but preserve ! and ? intonation contours and ensure sentence termination
            norm_text = punc_norm(chunk)
            norm_text = norm_text.rstrip(" ,;:—-\t\r\n")
            if chunk.rstrip().endswith("?") and not norm_text.endswith("?"):
                norm_text = norm_text.rstrip(".!") + "?"
            elif chunk.rstrip().endswith("!") and not norm_text.endswith("!"):
                norm_text = norm_text.rstrip(".?") + "!"
            elif not norm_text.endswith((".", "!", "?")):
                norm_text = norm_text + "."

            text_tokens = model.tokenizer.text_to_tokens(norm_text, language_id=lang_code).to(model.device)
            text_tokens = torch.cat([text_tokens, text_tokens], dim=0)

            sot = model.t3.hp.start_text_token
            eot = model.t3.hp.stop_text_token
            text_tokens = F.pad(text_tokens, (1, 0), value=sot)
            text_tokens = F.pad(text_tokens, (0, 1), value=eot)

            # Dynamic ceiling: speech tokens run ~4-5x text tokens.
            # Give sufficient headroom so long sentences never truncate before EOS.
            n_text_toks = text_tokens.shape[-1]
            max_tokens = min(max(int(n_text_toks * 5.5) + 60, 80), 650)

            with torch.inference_mode():
                speech_tokens = model.t3.inference(
                    t3_cond=t3_cond_to_use,
                    text_tokens=text_tokens,
                    max_new_tokens=max_tokens,
                    temperature=eff_temperature,
                    cfg_weight=eff_cfg_weight,
                    repetition_penalty=eff_repetition_penalty,
                    top_p=0.95,
                    min_p=0.05,
                )[0]
                speech_tokens = drop_invalid_tokens(speech_tokens).to(model.device)

                wav, _ = model.s3gen.inference(
                    speech_tokens=speech_tokens,
                    ref_dict=model.conds.gen,
                    n_cfm_timesteps=n_cfm_timesteps,
                )
                # Pure audio directly from vocoder without PerthNet neural watermark distortion
                data = wav.squeeze(0).detach().cpu().numpy()
                # Clean trailing hallucinated vocoder noise, rumble, or silent trailing gaps
                data = trim_trailing_noise(data, sr=DEFAULT_SAMPLE_RATE)
                # Trim leading vocoder breath/pop/filler artifacts before speech begins
                data = trim_leading_noise(data, sr=DEFAULT_SAMPLE_RATE)
                # Apply 5ms micro-fade to eliminate splice pops/clicks
                data = apply_micro_fade(data, fade_ms=5.0, sample_rate=DEFAULT_SAMPLE_RATE)

            audio_parts.append(data)

            # Insert clean digital zero pause between chunks
            if idx < total_chunks - 1 and pause_ms > 0:
                chunk_silence_samples = int((pause_ms / 1000.0) * DEFAULT_SAMPLE_RATE)
                if chunk_silence_samples > 0:
                    audio_parts.append(np.zeros(chunk_silence_samples, dtype=np.float32))

        # Join audio parts with clean digital silence preserved across pause segments
        final_parts = []
        for p in audio_parts:
            # If it is a silence segment, keep it pure digital zero (no crossfade pollution)
            if np.all(p == 0.0):
                final_parts.append(p)
            else:
                final_parts.append(p)
        
        full_audio = crossfade_concat(final_parts, crossfade_ms=10.0, sr=DEFAULT_SAMPLE_RATE)
        # Apply 4,900 Hz notch filter to eliminate stationary S3Gen vocoder metallic tone (Issue #536)
        full_audio = apply_notch_filter(full_audio, freq=4900.0, q=15.0, sr=DEFAULT_SAMPLE_RATE)
        # Studio peak normalization (-1.5 dBFS) for vocoder headroom consistency
        full_audio = normalize_peak(full_audio, target_dbfs=-1.5)

        # Save raw synthesized WAV to cache
        cache_id = str(uuid.uuid4())[:12]
        raw_output_wav = AUDIO_CACHE_DIR / f"raw_{cache_id}.wav"
        sf.write(str(raw_output_wav), full_audio, DEFAULT_SAMPLE_RATE, subtype="PCM_16")

        # Apply speed adjustment if requested (pitch-preserving)
        final_output_wav = AUDIO_CACHE_DIR / f"tts_{cache_id}.wav"
        adjust_audio_speed(raw_output_wav, final_output_wav, speed_factor=speed)

        # Clean up temporary raw file if speed was altered
        if raw_output_wav != final_output_wav and raw_output_wav.exists():
            try:
                raw_output_wav.unlink()
            except Exception:
                pass

        if progress_callback:
            progress_callback(total_chunks, total_chunks, "Finished")

        return str(final_output_wav.resolve())
