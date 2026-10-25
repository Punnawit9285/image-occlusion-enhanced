"""Runs the tap-to-reveal script in Chromium; skipped without Node and Playwright."""

import json
import shutil
import subprocess

import pytest

from conftest import DATA, ROOT
from image_occlusion_enhanced import tapreveal

SCRIPT = ROOT / "tests" / "js" / "tapreveal.test.js"


def _have_playwright() -> bool:
    if not shutil.which("node"):
        return False
    probe = subprocess.run(
        ["node", "-e", "require('playwright')"], capture_output=True, cwd=str(ROOT)
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _have_playwright(), reason="needs Node and Playwright")
def test_tap_to_reveal_in_chromium(tmp_path):
    script = tmp_path / "script.html"
    script.write_text(tapreveal.tap_to_reveal_script)
    work = tmp_path / "www"
    work.mkdir()
    run = subprocess.run(
        [
            "node",
            str(SCRIPT),
            str(script),
            str(DATA / "sample-original-mask.svg"),
            str(work),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(ROOT),
    )
    assert run.returncode == 0, run.stderr
    results = json.loads(run.stdout.strip().splitlines()[-1])
    assert results["errors"] == []
    loaded = results["loaded"]
    assert loaded["layer"] and loaded["masks"] == 6 and loaded["aligned"]
    assert not loaded["imgVisible"]
    assert results["clicked"]["revealed"] == 1
    assert results["clickedTwice"]["revealed"] == 0
    assert results["toggled"]["aligned"] and results["toggled"]["revealed"] == 0
    assert results["resized"]["aligned"]
    # whenever the mask cannot be used, the card stays as it was
    for case in ("missing", "noMasks", "fileUrl"):
        assert results[case] == {"layer": False, "imgVisible": True}, case
