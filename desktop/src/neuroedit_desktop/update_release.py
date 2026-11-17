"""Validate the public GitHub release metadata used by the updater."""

from dataclasses import dataclass
import re
from urllib.parse import quote

REPOSITORY = "https://github.com/v7sm25qk5v-ui/NeuroEdit"
MAX_ASSET_SIZE = 1024 * 1024 * 1024
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-alpha(?:\.(\d+))?)?$")


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    version: str
    body: str
    html_url: str
    asset: UpdateAsset


def _version(value: str) -> tuple[tuple[int, ...], int | None]:
    match = _VERSION.fullmatch(value)
    if not match:
        raise ValueError("Unsupported release version")
    core = tuple(int(part) for part in match.group(1, 2, 3))
    alpha = int(match.group(4) or 0) if "-alpha" in value else None
    return core, alpha


def is_newer_version(remote: str, current: str) -> bool:
    remote_core, remote_alpha = _version(remote)
    current_core, current_alpha = _version(current)
    if remote_core != current_core:
        return remote_core > current_core
    # Numeric versions in older builds omit the alpha tag entirely.
    if current_alpha is None:
        return False
    if remote_alpha is None:
        return True
    return remote_alpha > current_alpha


def parse_release(payload: object, platform: str, current_version: str) -> ReleaseInfo:
    if not isinstance(payload, dict):
        raise ValueError("Invalid release metadata")
    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise ValueError("Invalid release version")
    _version(tag)
    _version(current_version)
    suffix = {"darwin": "macOS-unsigned.zip", "win32": "Windows-Setup.exe"}.get(platform)
    if suffix is None:
        raise ValueError("Updates are not available for this platform")
    name = f"NeuroEdit-{tag}-{suffix}"
    expected_url = f"{REPOSITORY}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"
    html_url = f"{REPOSITORY}/releases/tag/{quote(tag, safe='')}"
    if payload.get("html_url") != html_url:
        raise ValueError("Invalid release page URL")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Invalid release asset list")
    matches = [item for item in assets if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        raise ValueError("A matching update download is unavailable")
    item = matches[0]
    size, digest = item.get("size"), item.get("digest")
    if item.get("browser_download_url") != expected_url:
        raise ValueError("Invalid update download URL")
    if type(size) is not int or not 0 < size <= MAX_ASSET_SIZE:
        raise ValueError("Invalid update download size")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("Update download has no valid SHA-256 digest")
    body = payload.get("body") or ""
    if not isinstance(body, str) or len(body) > 512 * 1024:
        raise ValueError("Invalid release notes")
    return ReleaseInfo(tag, ".".join(str(part) for part in _version(tag)[0]), body, html_url,
                       UpdateAsset(name, expected_url, size, digest[7:].lower()))
