"""Release versions come from pyproject.toml; build labels stay separate."""
from __future__ import annotations

import ast
import importlib.metadata
import re
import runpy
import tomllib
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]


def _expected() -> str:
    return tomllib.loads((DESKTOP / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_project_version_is_numeric():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _expected())


def test_uninstalled_source_reads_pyproject(monkeypatch):
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)
    package = runpy.run_path(str(DESKTOP / "src/neuroedit_desktop/__init__.py"))
    assert package["__version__"] == _expected()


def test_installed_package_uses_distribution_metadata(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "8.7.6")
    package = runpy.run_path(str(DESKTOP / "src/neuroedit_desktop/__init__.py"))
    assert package["__version__"] == "8.7.6"


def test_packaging_reads_project_version_and_includes_distribution_metadata(monkeypatch):
    source = (DESKTOP / "NeuroEdit.spec").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in n.targets))
    monkeypatch.chdir(DESKTOP)
    result = eval(compile(ast.Expression(assignment.value), "NeuroEdit.spec", "eval"),
                  {"tomllib": tomllib, "Path": Path})
    assert result == _expected()
    assert 'copy_metadata("neuroedit-desktop")' in source
    assert 'version("neuroedit-desktop") != APP_VERSION' in source


def test_installer_separates_numeric_version_and_artifact_label():
    script = (DESKTOP / "scripts/build_alpha_windows.ps1").read_text(encoding="utf-8")
    installer = (DESKTOP / "installer/NeuroEdit.iss").read_text(encoding="utf-8")
    assert '/DMyAppVersion=$AppVersion' in script
    assert '/DArtifactLabel=$Version' in script
    assert 'AppVersion={#MyAppVersion}' in installer
    assert 'OutputBaseFilename=NeuroEdit-{#ArtifactLabel}-Windows-Setup' in installer
