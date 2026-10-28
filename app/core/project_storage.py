import json
import uuid
from pathlib import Path
from datetime import datetime

from app.config import PROJECTS_DIR


class ProjectModel:
    def __init__(self, name: str = "Untitled Project", pptx_path: str = ""):
        self.project_id = str(uuid.uuid4())[:8]
        self.name = name
        self.pptx_path = pptx_path
        self.active_language = "en"
        self.voice_profile_id = ""
        self.slides = []  # list of slide dicts
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "pptx_path": self.pptx_path,
            "active_language": self.active_language,
            "voice_profile_id": self.voice_profile_id,
            "slides": self.slides,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectModel":
        proj = cls(name=data.get("name", "Untitled"), pptx_path=data.get("pptx_path", ""))
        proj.project_id = data.get("project_id", proj.project_id)
        proj.active_language = data.get("active_language", "en")
        proj.voice_profile_id = data.get("voice_profile_id", "")
        proj.slides = data.get("slides", [])
        proj.created_at = data.get("created_at", proj.created_at)
        proj.updated_at = data.get("updated_at", proj.updated_at)
        return proj


class ProjectManager:
    def __init__(self, projects_dir: Path = PROJECTS_DIR):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def save_project(self, project: ProjectModel, file_path: str | Path | None = None) -> str:
        project.updated_at = datetime.now().isoformat()
        if file_path is None:
            safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in project.name)
            file_path = self.projects_dir / f"{safe_name}_{project.project_id}.vsproj"
        else:
            file_path = Path(file_path)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, indent=2, ensure_ascii=False)

        return str(file_path.resolve())

    def load_project(self, file_path: str | Path) -> ProjectModel:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Project file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return ProjectModel.from_dict(data)

    def list_saved_projects(self) -> list[dict]:
        projects = []
        for file in self.projects_dir.glob("*.vsproj"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                projects.append({
                    "path": str(file.resolve()),
                    "name": data.get("name", file.stem),
                    "slides_count": len(data.get("slides", [])),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                pass
        return sorted(projects, key=lambda x: x.get("updated_at", ""), reverse=True)
