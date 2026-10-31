"""Private local Canvas viewer bundle; no server or cloud polling is started."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from importlib.resources import files

from .map_api import MapSnapshot


def _replace_private(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".map-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_map_view(snapshot: MapSnapshot, directory: str | Path) -> None:
    """Create/update an exclusively managed private viewer directory atomically.

    A browser polls ONLY local snapshot.json every five seconds. The caller
    controls when another cloud snapshot is fetched. Raster filenames include
    their content hash to prevent drawing a new floor with an old image.
    No credentials, signed URLs, DIDs or cloud object names enter the bundle.
    Retain the directory privately; no external fonts/CDNs/services are used.
    """
    root = Path(directory)
    marker = root / ".mihome-map-view"
    if root.is_symlink():
        raise ValueError("Viewer directory must not be a symlink")
    if root.exists():
        if not root.is_dir() or marker.is_symlink() or not marker.is_file():
            raise ValueError("Existing directory is not managed by the map viewer")
        if marker.read_bytes() != b"mihome-map-view-v1\n":
            raise ValueError("Invalid viewer marker")
    else:
        root.mkdir(mode=0o700)
        _replace_private(marker, b"mihome-map-view-v1\n")
    # This helper owns this directory; keep privacy when updating a managed one.
    root.chmod(0o700)
    payload = snapshot.to_dict()
    image_name = "map-" + payload["map"]["raster_revision"] + ".png"
    if not (root / image_name).is_file() or (root / image_name).is_symlink():
        _replace_private(root / image_name, snapshot.png())
    payload["map"]["image"] = image_name
    _replace_private(root / "index.html", files("mihome_cloud").joinpath("resources/map_view.html").read_bytes())
    _replace_private(root / "snapshot.json", json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
