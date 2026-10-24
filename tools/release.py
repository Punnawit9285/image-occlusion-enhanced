#!/usr/bin/env python3
"""
Helpers for the release workflow (.github/workflows/release.yml).

    python3 tools/release.py check v2.1.0    # the tag matches every version
    python3 tools/release.py notes v2.1.0    # that version's CHANGELOG entry

The version lives in src/image_occlusion_enhanced/_version.py. The
CHANGELOG needs an entry for it, and pyproject.toml has to agree.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def addon_version() -> str:
    text = (ROOT / "src" / "image_occlusion_enhanced" / "_version.py").read_text()
    match = re.search(r"""__version__\s*=\s*["']v?([^"']+)["']""", text)
    if not match:
        sys.exit("could not read __version__ from _version.py")
    return match.group(1)


def pyproject_version() -> str:
    match = re.search(
        r'^version\s*=\s*"v?([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M
    )
    return match.group(1) if match else ""


def changelog_entry(version: str) -> str:
    """The CHANGELOG text under "## [version]", without its download link"""
    text = (ROOT / "CHANGELOG.md").read_text()
    match = re.search(
        r"^## \[%s\][^\n]*\n(.*?)(?=^## \[|\Z)" % re.escape(version), text, re.M | re.S
    )
    if not match:
        return ""
    body = re.sub(r"^### \[Download\]\([^)]*\)\s*\n", "", match.group(1), flags=re.M)
    return body.strip()


def problems(tag: str) -> list:
    version = addon_version()
    found = []
    if tag.lstrip("v") != version:
        found.append("tag %s does not match _version.py (%s)" % (tag, version))
    if pyproject_version() != version:
        found.append(
            "pyproject.toml has %s, _version.py %s" % (pyproject_version(), version)
        )
    if not changelog_entry(version):
        found.append("CHANGELOG.md has no entry for %s" % version)
    return found


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "notes"):
        sys.exit(__doc__)
    command, tag = sys.argv[1], sys.argv[2]
    if command == "check":
        found = problems(tag)
        for problem in found:
            print("error:", problem)
        sys.exit(1 if found else 0)
    print(changelog_entry(tag.lstrip("v")))


if __name__ == "__main__":
    main()
