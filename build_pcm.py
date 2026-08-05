#!/usr/bin/env python3
"""Build the KiCad PCM (Plugin & Content Manager) package + repository manifests.

Produces, under dist/:
  * provenmetal-sourcing-<version>.zip  - the PCM package archive
      metadata.json            (package metadata, at archive root)
      plugins/plugin.json      (+ provenmetal_kicad/, requirements.txt, resources/)
      resources/icon.png       (64x64 package icon shown in PCM)
  * packages.json              - the repo index (metadata + download_* per version)
  * repository.json            - points PCM at packages.json (with its sha256)

Usage:
  python build_pcm.py [--download-base URL]

--download-base defaults to the GitHub releases URL for this repo; the archive is
expected to be uploaded there as a release asset (see the release step in CI /
the README). Everything is deterministic so the sha256 in packages.json matches
the built archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
PLUGIN = ROOT / "plugin"
DIST = ROOT / "dist"
PCM = ROOT / "pcm"  # committed manifests (hosted via raw github)

DEFAULT_DOWNLOAD_BASE = "https://github.com/proven-metal/provenmetal-kicad/releases/download"
# Where the repository will be hosted (raw manifests). Adjust if hosting elsewhere.
DEFAULT_REPO_BASE = "https://raw.githubusercontent.com/proven-metal/provenmetal-kicad/main/pcm"


def load_metadata() -> dict:
    return json.loads((ROOT / "metadata.json").read_text())


def archive_files() -> list[tuple[Path, str]]:
    """(source path, arcname) pairs for the PCM archive."""
    items: list[tuple[Path, str]] = []
    # Plugin content lands under plugins/ (KiCad installs that subtree).
    for p in sorted(PLUGIN.rglob("*")):
        if p.is_dir():
            continue
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        items.append((p, f"plugins/{p.relative_to(PLUGIN).as_posix()}"))
    # Package icon shown in the PCM UI (separate from the plugin's action icons).
    icon = PLUGIN / "resources" / "icon.png"
    if icon.exists():
        items.append((icon, "resources/icon.png"))
    return items


def build_archive(version: str, base_metadata: dict) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"provenmetal-sourcing-{version}.zip"
    # Deterministic archive: fixed mtime, sorted entries.
    archive_meta = {k: v for k, v in base_metadata.items()}
    # The in-archive metadata carries no download_* (those live in packages.json).
    for v in archive_meta.get("versions", []):
        v.pop("_comment", None)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("metadata.json", date_time=(2025, 1, 1, 0, 0, 0))
        zf.writestr(info, json.dumps(archive_meta, indent=2))
        for src, arc in archive_files():
            zi = zipfile.ZipInfo(arc, date_time=(2025, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, src.read_bytes())
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def install_size() -> int:
    return sum(p.stat().st_size for p, _ in archive_files())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-base", default=DEFAULT_DOWNLOAD_BASE)
    ap.add_argument("--repo-base", default=DEFAULT_REPO_BASE)
    args = ap.parse_args()

    metadata = load_metadata()
    version = metadata["versions"][0]["version"]

    archive = build_archive(version, metadata)
    digest = sha256_of(archive)
    size = archive.stat().st_size
    isize = install_size()

    # packages.json: the repo index (metadata + per-version download info).
    pkg = json.loads(json.dumps(metadata))  # deep copy
    v = pkg["versions"][0]
    v.pop("_comment", None)
    v["download_url"] = f"{args.download_base}/v{version}/{archive.name}"
    v["download_sha256"] = digest
    v["download_size"] = size
    v["install_size"] = isize
    packages = {"packages": [pkg]}
    PCM.mkdir(exist_ok=True)
    packages_path = PCM / "packages.json"
    packages_path.write_text(json.dumps(packages, indent=2))

    # repository.json: points PCM at packages.json.
    packages_bytes = packages_path.read_bytes()
    now = int(time.time())
    repository = {
        "$schema": "https://go.kicad.org/pcm/schemas/v1",
        "name": "ProvenMetal KiCad Repository",
        "maintainer": {"name": "ProvenMetal", "contact": {"web": "https://provenmetal.com"}},
        "packages": {
            "url": f"{args.repo_base}/packages.json",
            "sha256": hashlib.sha256(packages_bytes).hexdigest(),
            "update_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
            "update_timestamp": now,
        },
    }
    (PCM / "repository.json").write_text(json.dumps(repository, indent=2))

    print(f"archive : {archive}  ({size} bytes, sha256 {digest[:16]}...)")
    print(f"install : {isize} bytes")
    print(f"index   : {packages_path}")
    print(f"repo    : {PCM / 'repository.json'}")
    print(f"\nPCM repository URL (add in KiCad):\n  {args.repo_base}/repository.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
