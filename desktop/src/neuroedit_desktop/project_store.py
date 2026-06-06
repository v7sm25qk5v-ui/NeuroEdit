from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from neuroedit_desktop.models import ProjectState


@dataclass
class ProjectStore:
    project_path: Path

    @classmethod
    def create(cls, folder: Path) -> ProjectStore:
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("masks", "audio", "stills"):
            (folder / name).mkdir(exist_ok=True)
        return cls(project_path=folder / "project.json")

    @classmethod
    def open(cls, project_path: Path) -> tuple[ProjectStore, ProjectState]:
        with project_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(project_path=project_path), ProjectState.from_dict(data)

    def save(self, project: ProjectState) -> None:
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.project_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(project.to_dict(), handle, indent=2)
        os.replace(tmp_path, self.project_path)
