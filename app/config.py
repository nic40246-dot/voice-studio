from pathlib import Path
import os

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"

PROFILES_DIR = DATA_DIR / "profiles"
PROJECTS_DIR = DATA_DIR / "projects"
AUDIO_CACHE_DIR = DATA_DIR / "audio_cache"
EXPORTS_DIR = DATA_DIR / "exports"

for d in [PROFILES_DIR, PROJECTS_DIR, AUDIO_CACHE_DIR, EXPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Audio defaults
DEFAULT_SAMPLE_RATE = 24000  # Chatterbox native S3GEN sample rate
TARGET_LOUDNESS_DBFS = -20.0  # Professional broadcast / presentation target
MIN_SAMPLE_DURATION_SEC = 3.0
MAX_SAMPLE_DURATION_SEC = 60.0

# Supported TTS Languages
SUPPORTED_LANGUAGES = {
    "en": "English",
    "de": "German (Deutsch)",
}

# License & Model specs
MODEL_NAME = "Resemble AI Chatterbox-Multilingual"
MODEL_LICENSE = "MIT (Permissive Commercial Workplace Use)"
MODEL_DEVICE = "cpu"
