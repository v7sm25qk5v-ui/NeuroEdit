import hashlib
import pytest
from neuroedit_desktop.update_release import is_newer_version, parse_release


def payload(data=b"abc"):
    tag = "v0.5.19-alpha.1"
    name = f"NeuroEdit-{tag}-macOS-unsigned.zip"
    base = "https://github.com/v7sm25qk5v-ui/NeuroEdit/releases"
    return {"tag_name": tag, "body": "notes", "html_url": f"{base}/tag/{tag}",
            "assets": [{"name": name, "size": len(data),
                        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                        "browser_download_url": f"{base}/download/{tag}/{name}"}]}


def test_version_order():
    assert is_newer_version("v0.5.19-alpha", "0.5.18")
    assert not is_newer_version("v0.5.18-alpha", "0.5.18")
    assert is_newer_version("v0.5.18-alpha.2", "v0.5.18-alpha.1")
    assert is_newer_version("v0.5.18", "v0.5.18-alpha.1")


def test_release_and_validation():
    assert parse_release(payload(), "darwin", "0.5.18").asset.size == 3
    for key, bad in [("digest", None), ("size", 0), ("browser_download_url", "http://evil")]:
        data = payload()
        data["assets"][0][key] = bad
        with pytest.raises(ValueError):
            parse_release(data, "darwin", "0.5.18")
    with pytest.raises(ValueError):
        parse_release(payload(), "win32", "0.5.18")
