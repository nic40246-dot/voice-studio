import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from app.config import PROFILES_DIR
from app.core.audio_processing import validate_audio_sample, clean_audio_sample

PROFILES_METADATA_FILE = PROFILES_DIR / "profiles.json"


class VoiceProfileManager:
    def __init__(self, profiles_dir: Path = PROFILES_DIR):
        self.profiles_dir = Path(profiles_dir)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.profiles_dir / "profiles.json"
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> dict:
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_profiles(self):
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.profiles, f, indent=2, ensure_ascii=False)

    def get_default_profile_id(self) -> str | None:
        for p in self.profiles.values():
            if p.get("is_default"):
                return p["id"]
        if self.profiles:
            sorted_p = sorted(self.profiles.values(), key=lambda x: x.get("created_at", ""), reverse=True)
            return sorted_p[0]["id"]
        return None

    def set_default_profile(self, profile_id: str):
        for pid, p in self.profiles.items():
            p["is_default"] = (pid == profile_id)
        self._save_profiles()

    def list_profiles(self) -> list[dict]:
        # Return profiles with default profile first
        default_id = self.get_default_profile_id()
        profs = list(self.profiles.values())
        if default_id:
            profs.sort(key=lambda p: 0 if p["id"] == default_id else 1)
        return profs

    def get_profile(self, profile_id: str) -> dict | None:
        return self.profiles.get(profile_id)

    def create_profile(
        self,
        name: str,
        source_audio_path: str | Path,
        primary_language: str = "en",
        description: str = "",
    ) -> dict:
        source_path = Path(source_audio_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source audio not found: {source_path}")

        # Validate quality
        validation = validate_audio_sample(source_path)
        if not validation.get("valid", False):
            raise ValueError(f"Audio validation failed: {validation.get('error', 'Sample too short or silent')}")

        profile_id = str(uuid.uuid4())[:8]
        profile_folder = self.profiles_dir / profile_id
        profile_folder.mkdir(parents=True, exist_ok=True)

        target_wav = profile_folder / "reference.wav"
        clean_audio_sample(source_path, target_wav)

        profile_data = {
            "id": profile_id,
            "name": name.strip(),
            "description": description.strip(),
            "primary_language": primary_language.lower(),
            "reference_audio": str(target_wav.resolve()),
            "duration_sec": validation.get("duration", 0),
            "sample_rate": validation.get("sample_rate", 24000),
            "rms_db": validation.get("rms_db", -20.0),
            "created_at": datetime.now().isoformat(),
        }

        self.profiles[profile_id] = profile_data
        self._save_profiles()
        return profile_data

    def delete_profile(self, profile_id: str) -> bool:
        if profile_id in self.profiles:
            folder = self.profiles_dir / profile_id
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            del self.profiles[profile_id]
            self._save_profiles()
            return True
        return False
