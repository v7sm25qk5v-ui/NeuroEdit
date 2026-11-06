from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neuroedit_desktop.models import ProjectState


@dataclass
class ProjectStore:
    project_path: Path

    @classmethod
    def create(cls, folder: Path) -> ProjectStore:
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("masks", "audio", "stills"):
            asset_dir = folder / name
            if asset_dir.is_symlink() or asset_dir.is_junction():
                raise ValueError(f"Managed asset directory is a link: {asset_dir}")
            asset_dir.mkdir(exist_ok=True)
        return cls(project_path=folder / "project.json")

    @classmethod
    def open(cls, project_path: Path) -> tuple[ProjectStore, ProjectState]:
        with project_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(project_path=project_path), ProjectState.from_dict(data)

    def save(self, project: ProjectState) -> None:
        self.save_data(project.to_dict())

    def save_data(self, data: dict[str, Any]) -> None:
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.project_path.parent,
                prefix=".neuroedit-project-", suffix=".tmp", delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                json.dump(data, handle, indent=2)
            os.replace(tmp_path, self.project_path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
