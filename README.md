# Personal AI Voice Studio — English & German Narration Suite

A professional, local desktop application for zero-shot voice cloning, expressive neural speech synthesis, and automated PowerPoint presentation narration.

Runs entirely locally on CPU/GPU without cloud subscriptions, third-party API dependencies, or privacy leaks.

---

## Key Highlights

- **Neural Architecture:** Resemble AI Chatterbox-Multilingual (500M Flow-Matching + Neural Codec).
- **Commercial Workplace License:** 100% Permissive MIT License for code and model weights (no cloud subscriptions, API keys, or royalties).
- **Zero-Shot Voice Cloning:** Clone your natural voice from 10–30s audio sample (WAV/MP3/M4A) or live microphone recording.
- **Human Expressiveness (Default: 0.65):** Natural dynamic pitch range and conversational cadence, avoiding both robotic flatline and unnatural hyper-modulation.
- **Natural English & German Synthesis:** Human-like timbre, cadence, and breath micro-pauses (no robotic monotone or phase distortion).
- **Direct PowerPoint COM Automation:** Embed generated audio directly onto slides with automatic playback (`PlayOnEntry = msoTrue`).
- **Screen Recording Attachments:** Embed MP4 videos into specific presentation slides.
- **Optimized for Intel Core i5-14500:** Multi-threaded CPU AVX2 vectorized execution across all 14 cores (128 GB RAM).

---

## Quick Start (Windows 11)

### 1. Requirements & Setup
- Windows 10/11 (64-bit)
- Python 3.10 or 3.11
- Microsoft PowerPoint (Desktop Office 365, 2019, or 2021) for direct COM embedding.

### 2. Launching the App
Option A: Double-click `launch.bat` in Windows File Explorer.
Option B: Run from PowerShell:
```powershell
.\.venv\Scripts\activate
python run.py
```

---

## How to Record & Use Your Own Voice

Voice Studio clones voices from short, high-quality audio references. To create your own voice profile:

### Step 1: Open the "Voice Profiles" Tab
Navigate to the **Voice Profiles** tab in the top navigation bar.

### Step 2: Record or Import Your Reference Audio
- **Option 1: Live Recording (Recommended):**
  - Read the built-in **Teleprompter Script** provided in the tab. This script is phonetically balanced with diverse English and German phonemes.
  - Click **"Start Recording"** (or use the visual 3-second countdown).
  - Speak naturally at your normal presentation pace for **15 to 25 seconds**.
  - Click **"Stop & Process"**.
- **Option 2: Import Existing File:**
  - Click **"Import Audio Sample"** and choose any clean `.wav`, `.mp3`, or `.m4a` file containing 10–30 seconds of isolated speech.

### Step 3: Best Practices for Voice Samples
For the most convincing, natural-sounding results:
- **Quiet Environment:** Record in a quiet room with minimal echo and no background fan/AC hum.
- **Consistent Distance:** Keep 10–15 cm from your microphone using a pop filter if available.
- **Conversational Tone:** Speak in the style you intend to use for your presentations. Avoid reading monotone.
- **Automatic Audio Conditioning:** The application automatically trims leading/trailing silence, filters low-frequency rumble (<70 Hz), and normalizes loudness to -20 dBFS RMS.

### Step 4: Save & Select Profile
- Give your profile a name (e.g. `My Studio Voice`) and click **"Save Profile"**.
- Your profile is now immediately available in both the **Text-to-Speech Studio** and **PowerPoint Studio** tabs.

---

## Application Structure & Tabs

### 1. 🎙️ Voice Profiles (Voice Studio)
- **Calibration Teleprompter Script:** Built-in phonetically balanced reading scripts for English and German. Reading this text covers all critical vowels, plosives, and cadence contours needed for studio-grade voice cloning.
- **Visual Recording Assistant:** 3-second countdown (`3... 2... 1... Speak!`), highlighted teleprompter box, live duration counter (`18.2s / 25s target`), and RMS volume meter.
- **Copy to Clipboard:** One-click script copying for dual-monitor or mobile teleprompting.
- **Import Audio:** Select WAV, MP3, M4A, or FLAC reference voice sample.
- **Audio Quality Audit:** Automatically evaluates duration, RMS loudness, peak level, and clipping.
- **Automatic Audio Conditioning:** Trims leading/trailing silence, applies gentle high-pass filtering (70Hz rumble cutoff), and normalizes loudness to -20 dBFS.

### 2. 📝 Text-to-Speech Studio
- Standalone generation workspace for any narrative text.
- **Human Expressiveness Slider:** Default set to **0.65** for realistic conversational intonation without robotic flattening.
- Pacing slider (0.7x to 1.4x) with pitch-preserving WSOLA time-stretch (no chipmunk effect).
- Inter-sentence micro-pause slider (150ms to 750ms) to ensure natural breathing intervals.
- Integrated audio player with position scrubbing and volume controls.
- Export options: Clean broadcast WAV or high-bitrate MP3 (192 kbps).
- **Pronunciation Rules:** Custom phonetic dictionary to override acronyms and technical terms (e.g., `API` → `A P I`, `SaaS` → `Sass`, `B2B` → `B to B`).

### 3. 📊 PowerPoint Studio (Slide Narration & Videos)
- Open any corporate presentation (`.pptx`) with 60+ slides.
- Extract slide titles, slide body texts, and original PowerPoint speaker notes.
- Automatically generates 320x180 slide thumbnails via PowerPoint COM.
- **Dual Script Tabs:** Manage English (`🇬🇧`) and German (`🇩🇪`) scripts side by side per slide.
- One-click **"Copy Speaker Notes to Script"** helper.
- **Embed Audio (Autoplay):** Embeds synthesized audio into the slide shape collection with:
  - `PlayOnEntry = msoTrue (-1)`
  - `HideWhileNotPlaying = msoTrue (-1)`
  - `Animate = msoTrue (-1)`
- **Attach MP4 Screen Recordings:** Embed demonstration videos directly onto designated slides.
- **Export Presentation:** Generates complete presentation copies:
  - `*_EN_Narrated.pptx`
  - `*_DE_Narrated.pptx`

### 4. ⚙️ Commercial License & Setup
- Model weights and code license audit verification.
- Hardware telemetry & thread status.
- Microsoft Teams presentation guide.

---

## Microsoft Teams Autoplay Presentation Guide

When delivering a presentation in Microsoft Teams:
1. Open the exported narrated PowerPoint file in PowerPoint.
2. In the Microsoft Teams meeting window, click **Share**.
3. **CRITICAL STEP:** Turn ON the switch **"Include computer sound"** (located at the top-right of the Share tray).
4. Share the PowerPoint presentation window.
5. Press **F5** to start Slide Show.
6. As you advance slides, each slide's embedded voiceover starts automatically and plays cleanly through the meeting audio stream.

---

## Directory Organization

```
voice-studio/
├── app/
│   ├── config.py                  # Audio parameters, paths, and constants
│   ├── core/
│   │   ├── audio_processing.py    # Noise gate, silence trim, -20 dBFS RMS, WSOLA stretch
│   │   ├── pptx_service.py        # win32com PowerPoint automation & python-pptx
│   │   ├── project_storage.py     # .vsproj project serialization
│   │   ├── pronunciation.py       # Phonetic dictionary rules manager
│   │   ├── tts_engine.py          # ChatterboxMultilingualTTS wrapper
│   │   └── voice_manager.py       # Voice profile lifecycle and validation
│   └── ui/
│       ├── audio_player_widget.py # PySide6 audio player with scrubbing
│       ├── main_window.py         # Main application window
│       ├── pptx_studio_tab.py     # PowerPoint studio tab
│       ├── theme.py               # Modern Windows 11 fluent dark theme
│       ├── tts_editor_tab.py      # Standalone TTS editor tab
│       ├── voice_studio_tab.py    # Voice profiles manager tab
│       └── workers.py             # Background QThreads with progress and cancel
├── data/
│   ├── audio_cache/               # Cached synthesis wav files
│   ├── exports/                   # Exported audio and presentations
│   ├── profiles/                  # Saved voice profiles
│   └── projects/                  # Saved .vsproj projects
├── tests/                         # Full automated pytest suite
├── launch.bat                     # Windows 11 launcher
├── requirements.txt               # Pinned dependencies
├── run.py                         # Application entry point
└── README.md
```

---

## Running the Automated Test Suite

```bash
.venv/Scripts/python.exe -m pytest tests -v
```
Output:
```
tests/test_audio_processing.py::test_audio_validation_and_cleaning PASSED
tests/test_pptx_integration.py::test_pptx_com_audio_embedding PASSED
tests/test_pronunciation.py::test_pronunciation_rules PASSED
tests/test_voice_profiles.py::test_voice_profile_lifecycle PASSED
```

---

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.
