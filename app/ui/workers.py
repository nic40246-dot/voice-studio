import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QThread, Signal

from app.config import DEFAULT_SAMPLE_RATE
from app.core.pptx_service import PowerPointService
from app.core.tts_engine import TTSEngine
from app.core.gemini_director import (
    analyze_deck_storyline,
    auto_direct_slide_with_gemini,
    detect_slide_tone_heuristic,
    humanize_script_with_gemini,
)


class CancelToken:
    def __init__(self):
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True


class HumanizeWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        raw_text: str,
        language: str = "en",
        tone: str = "engaging",
        custom_instructions: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.raw_text = raw_text
        self.language = language
        self.tone = tone
        self.custom_instructions = custom_instructions

    def run(self):
        try:
            result = humanize_script_with_gemini(
                raw_text=self.raw_text,
                language=self.language,
                tone=self.tone,
                custom_instructions=self.custom_instructions,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class AutoDirectSlideWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        raw_text: str,
        slide_index: int = 0,
        total_slides: int = 1,
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self.raw_text = raw_text
        self.slide_index = slide_index
        self.total_slides = total_slides
        self.language = language

    def run(self):
        try:
            result = auto_direct_slide_with_gemini(
                raw_text=self.raw_text,
                slide_index=self.slide_index,
                total_slides=self.total_slides,
                language=self.language,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class AutoDirectPresentationWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        slides: list[dict],
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self.slides = slides
        self.language = language
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    def run(self):
        try:
            total = len(self.slides)
            updated = []
            for i, slide in enumerate(self.slides):
                if self.cancel_requested:
                    break
                slide_num = i + 1
                self.progress.emit(slide_num, total, f"Auto-directing tone for Slide {slide_num}/{total}...")
                
                # Determine source text (existing script, or speaker notes, or body)
                script_key = "script_en" if self.language == "en" else "script_de"
                source = slide.get(script_key, "").strip() or slide.get("notes", "").strip() or slide.get("body", "").strip()
                
                if source:
                    res = auto_direct_slide_with_gemini(
                        raw_text=source,
                        slide_index=i,
                        total_slides=total,
                        language=self.language,
                    )
                else:
                    res = detect_slide_tone_heuristic("", i, total)
                    res["narration"] = ""

                slide_copy = dict(slide)
                slide_copy["tone_style"] = res["tone_style"]
                slide_copy["exaggeration"] = res["exaggeration"]
                slide_copy["speed"] = res["speed"]
                slide_copy["pause_ms"] = res.get("pause_ms", 250)
                slide_copy["tone_reason"] = res.get("reason", "")
                if res.get("narration"):
                    slide_copy[script_key] = res["narration"]

                updated.append(slide_copy)

            self.finished.emit(updated)
        except Exception as e:
            self.error.emit(str(e))


class StorylineAnalysisWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        slides: list[dict],
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self.slides = slides
        self.language = language

    def run(self):
        try:
            results = analyze_deck_storyline(self.slides, self.language)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class BatchGenerateAudioWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        slides: list[dict],
        language: str = "en",
        reference_audio_path: str | None = None,
        native_accent: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.slides = slides
        self.language = language
        self.reference_audio_path = reference_audio_path
        self.native_accent = native_accent
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    def run(self):
        try:
            engine = TTSEngine.get_instance()
            script_key = "script_en" if self.language == "en" else "script_de"
            audio_key = "audio_en_path" if self.language == "en" else "audio_de_path"
            
            total = len(self.slides)
            updated = []
            
            for i, slide in enumerate(self.slides):
                if self.cancel_requested:
                    break
                slide_num = i + 1
                script = slide.get(script_key, "").strip()
                if not script:
                    updated.append(dict(slide))
                    continue

                exag = slide.get("exaggeration", 0.70)
                spd = slide.get("speed", 1.0)
                pause = slide.get("pause_ms", 250)
                tone = slide.get("tone_style", "engaging")

                self.progress.emit(
                    slide_num,
                    total,
                    f"Synthesizing Slide {slide_num}/{total} [Tone: {tone}, Exag: {exag:.2f}]...",
                )

                wav_path = engine.generate_speech(
                    text=script,
                    language=self.language,
                    reference_audio_path=self.reference_audio_path,
                    speed=spd,
                    pause_duration_ms=pause,
                    cfg_weight=0.35,
                    temperature=0.82,
                    exaggeration=exag,
                    native_accent=self.native_accent,
                )

                slide_copy = dict(slide)
                slide_copy[audio_key] = wav_path
                updated.append(slide_copy)

            self.finished.emit(updated)
        except Exception as e:
            self.error.emit(str(e))


class TTSWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        text: str,
        language: str = "en",
        reference_audio_path: str | None = None,
        speed: float = 1.0,
        pause_duration_ms: int = 250,
        temperature: float = 0.82,
        cfg_weight: float = 0.35,
        exaggeration: float = 0.65,
        native_accent: bool = False,
        n_cfm_timesteps: int = 8,
        parent=None,
    ):
        super().__init__(parent)
        self.text = text
        self.language = language
        self.reference_audio_path = reference_audio_path
        self.speed = speed
        self.pause_duration_ms = pause_duration_ms
        self.temperature = temperature
        self.cfg_weight = cfg_weight
        self.exaggeration = exaggeration
        self.native_accent = native_accent
        self.n_cfm_timesteps = n_cfm_timesteps
        self.cancel_token = CancelToken()

    def cancel(self):
        self.cancel_token.cancel()

    def run(self):
        try:
            engine = TTSEngine.get_instance()
            output_wav = engine.generate_speech(
                text=self.text,
                language=self.language,
                reference_audio_path=self.reference_audio_path,
                speed=self.speed,
                pause_duration_ms=self.pause_duration_ms,
                temperature=self.temperature,
                cfg_weight=self.cfg_weight,
                exaggeration=self.exaggeration,
                native_accent=self.native_accent,
                n_cfm_timesteps=self.n_cfm_timesteps,
                progress_callback=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
                cancel_token=self.cancel_token,
            )
            self.finished.emit(output_wav)
        except InterruptedError:
            self.error.emit("Generation was cancelled")
        except Exception as e:
            self.error.emit(str(e))


def resolve_input_device(device_id: int | None = None) -> tuple[int, int]:
    """Find a valid input device index and its working sample rate."""
    all_devs = sd.query_devices()

    def test_dev(idx: int):
        try:
            d = all_devs[idx]
            if d.get("max_input_channels", 0) <= 0:
                return None
            native_sr = int(d.get("default_samplerate", 44100))
            for sr in [DEFAULT_SAMPLE_RATE, native_sr, 44100, 48000, 16000]:
                try:
                    sd.check_input_settings(device=idx, channels=1, samplerate=sr)
                    return (idx, sr)
                except Exception:
                    continue
        except Exception:
            return None
        return None

    # 1. Try requested device if valid
    if device_id is not None and device_id >= 0:
        res = test_dev(device_id)
        if res:
            return res

    # 2. Try default input device if valid (not -1)
    try:
        def_in = sd.default.device[0]
        if def_in >= 0:
            res = test_dev(def_in)
            if res:
                return res
    except Exception:
        pass

    # 3. Search all devices
    for idx in range(len(all_devs)):
        res = test_dev(idx)
        if res:
            return res

    raise RuntimeError(
        "No operational microphone detected. Please check Windows sound settings or connect a microphone."
    )


class AudioRecordWorker(QThread):
    level = Signal(float)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        output_wav_path: str,
        device: int | None = None,
        max_duration_sec: int = 30,
        parent=None,
    ):
        super().__init__(parent)
        self.output_wav_path = output_wav_path
        self.device = device
        self.max_duration_sec = max_duration_sec
        self.is_recording = False
        self.recorded_frames = []

    def stop_recording(self):
        self.is_recording = False

    def run(self):
        self.is_recording = True
        self.recorded_frames = []

        try:
            dev_idx, sample_rate = resolve_input_device(self.device)

            def callback(indata, frames, time_info, status):
                if not self.is_recording:
                    raise sd.CallbackStop()
                self.recorded_frames.append(indata.copy())
                rms = np.sqrt(np.mean(indata**2)) if len(indata) > 0 else 0.0
                self.level.emit(float(rms))

            with sd.InputStream(
                device=dev_idx,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                callback=callback,
            ):
                start_time = time.time()
                while self.is_recording and (time.time() - start_time < self.max_duration_sec):
                    time.sleep(0.05)

            if not self.recorded_frames:
                self.error.emit("No audio frames recorded")
                return

            full_audio = np.concatenate(self.recorded_frames, axis=0)
            sf.write(self.output_wav_path, full_audio, sample_rate, subtype="PCM_16")
            self.finished.emit(self.output_wav_path)
        except Exception as e:
            self.error.emit(str(e))


class PPTXExtractWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, pptx_path: str, generate_thumbnails: bool = True, parent=None):
        super().__init__(parent)
        self.pptx_path = pptx_path
        self.generate_thumbnails = generate_thumbnails

    def run(self):
        try:
            service = PowerPointService()
            slides = service.extract_slides_info(self.pptx_path, generate_thumbnails=self.generate_thumbnails)
            self.finished.emit(slides)
        except Exception as e:
            self.error.emit(str(e))


class PPTXBatchExportWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        source_pptx: str,
        output_pptx: str,
        slide_audio_map: dict[int, str],
        slide_video_map: dict[int, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.source_pptx = source_pptx
        self.output_pptx = output_pptx
        self.slide_audio_map = slide_audio_map
        self.slide_video_map = slide_video_map

    def run(self):
        try:
            service = PowerPointService()
            result = service.batch_export_presentation(
                source_pptx=self.source_pptx,
                output_pptx=self.output_pptx,
                slide_audio_map=self.slide_audio_map,
                slide_video_map=self.slide_video_map,
                progress_callback=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
