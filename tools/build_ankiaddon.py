#!/usr/bin/env python3
"""
Package the add-on as .ankiaddon files: one to attach to a GitHub release and
one to upload to AnkiWeb.

    python3 tools/build_ankiaddon.py [--version 2.1.0] [--out build]

An .ankiaddon is a zip of the add-on folder's contents plus a manifest.json
telling Anki which folder to install it into. Anki's own Tools > Add-ons >
Install from file... (or drag-and-drop onto that list) reads it.

The package installs under its own folder name rather than the AnkiWeb ID
1374772155. Anki checks numbered folders against AnkiWeb for updates, and
AnkiWeb still serves the 2022 release, so installing under that ID would
invite Anki to "update" these fixes away again. The AnkiWeb version is listed
as a conflict instead: Anki disables it when this package is installed. Notes,
the note type and the add-on's settings live in the collection and profile,
not in the folder, so nothing is lost by switching.

The AnkiWeb package is the same, except that its manifest lists the GitHub
package's folder as a conflict too. AnkiWeb installs an add-on under its
numeric ID and only reads "conflicts" from the manifest, so installing it
switches off a copy installed from GitHub. The GitHub package must not list
its own folder, or Anki would disable it while updating it.
"""

import argparse
import json
import pathlib
import py_compile
import re
import sys
import tempfile
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "image_occlusion_enhanced"

PACKAGE = "image_occlusion_enhanced_2"
# Shown in Anki's add-on list. Marked as a continuation of the original
# add-on, as its license asks of modified versions.
NAME = "Image Occlusion Enhanced (Continued)"
HOMEPAGE = "https://github.com/Punnawit9285/image-occlusion-enhanced"
# The original add-on, from AnkiWeb and from its own GitHub releases
ORIGINAL = ["1374772155", "image_occlusion_enhanced"]
# This version's AnkiWeb ID, once it has one; the GitHub package then
# switches off a copy installed from AnkiWeb as well
ANKIWEB_ID = ""
CONFLICTS = {
    "github": ORIGINAL + ([ANKIWEB_ID] if ANKIWEB_ID else []),
    "ankiweb": ORIGINAL + [PACKAGE],
}
# Anki 2.1.50; the compatibility layer covers everything newer
MIN_POINT_VERSION = 50

# never shipped: caches, and the files Anki itself writes into an install
SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache"}
SKIP_FILES = {"meta.json", "manifest.json", ".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def read_version() -> str:
    text = (SOURCE / "_version.py").read_text()
    match = re.search(r"""__version__\s*=\s*["']v?([^"']+)["']""", text)
    if not match:
        sys.exit("could not read __version__ from _version.py")
    return match.group(1)


def shipped_files():
    for path in sorted(SOURCE.rglob("*")):
        relative = path.relative_to(SOURCE)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if not path.is_file():
            continue
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
            continue
        yield path, relative


def check_sources(files) -> None:
    """Refuse to package Python that does not even compile."""
    with tempfile.TemporaryDirectory() as scratch:
        for path, relative in files:
            if path.suffix != ".py" or "_vendor" in relative.parts:
                continue
            try:
                py_compile.compile(
                    str(path), cfile=str(pathlib.Path(scratch) / "check.pyc"), doraise=True
                )
            except py_compile.PyCompileError as error:
                sys.exit("syntax error, not packaging:\n%s" % error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", help="version to stamp (default: _version.py)")
    parser.add_argument("--out", default=str(ROOT / "build"), help="output folder")
    args = parser.parse_args()
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    version = (args.version or read_version()).lstrip("v")
    files = list(shipped_files())
    if not any(relative.as_posix() == "__init__.py" for _, relative in files):
        sys.exit("no __init__.py at the add-on root - wrong source folder?")
    check_sources(files)

    for target, suffix in (("github", ""), ("ankiweb", "-ankiweb")):
        manifest = {
            "package": PACKAGE,
            "name": NAME,
            "human_version": version,
            "author": "Glutanimate, Punnawit9285",
            "homepage": HOMEPAGE,
            "conflicts": CONFLICTS[target],
            "min_point_version": MIN_POINT_VERSION,
            "mod": int(time.time()),
        }
        name = "image-occlusion-enhanced-%s%s.ankiaddon" % (version, suffix)
        target_path = out_dir / name
        with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=4) + "\n")
            for path, relative in files:
                archive.write(path, relative.as_posix())
        size_kb = target_path.stat().st_size / 1024
        print("built %s (%d files, %.0f KB)" % (target_path, len(files) + 1, size_kb))


if __name__ == "__main__":
    main()
