"""Release hygiene: one version everywhere, a package that installs, and add-on
code that still runs on the Python of the oldest supported Anki (3.9)."""

import ast
import json
import py_compile
import subprocess
import sys
import zipfile

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import release  # noqa: E402

SOURCE = ROOT / "src" / "image_occlusion_enhanced"


def test_versions_agree():
    version = release.addon_version()
    assert release.problems("v" + version) == []
    assert release.changelog_entry(version)


def test_mismatched_tag_is_reported():
    assert release.problems("v0.0.1")


def test_newest_changelog_entry_is_the_current_version():
    text = (ROOT / "CHANGELOG.md").read_text()
    first = text[text.index("## [") :].split("]", 1)[0][4:]
    assert first == release.addon_version()


@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    out = tmp_path_factory.mktemp("build")
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_ankiaddon.py"), "--out", str(out)],
        check=True,
        capture_output=True,
    )
    built = {p.name: p for p in out.glob("*.ankiaddon")}
    assert len(built) == 2
    (ankiweb,) = [p for name, p in built.items() if name.endswith("-ankiweb.ankiaddon")]
    (github,) = [p for name, p in built.items() if not name.endswith("-ankiweb.ankiaddon")]
    return github, ankiweb


def _read(package):
    with zipfile.ZipFile(package) as archive:
        return archive.namelist(), json.loads(archive.read("manifest.json"))


def test_package_contents(packages):
    for package in packages:
        names, manifest = _read(package)
        assert "__init__.py" in names and "svg-edit/editor/svg-editor.html" in names
        assert "svg-edit/editor/pathseg.js" in names
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        assert not any(n.startswith("/") or ".." in n for n in names)
        assert manifest["name"] and manifest["human_version"] == release.addon_version()
        assert "1374772155" in manifest["conflicts"]


def test_conflicts(packages):
    github, ankiweb = (_read(p)[1] for p in packages)
    # Anki would disable a package that lists its own folder while updating it
    assert github["package"] not in github["conflicts"]
    # installing from AnkiWeb switches off a copy installed from GitHub
    assert github["package"] in ankiweb["conflicts"]


def _python_files():
    return sorted(SOURCE.rglob("*.py"))


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SOURCE)))
def test_runs_on_python_3_9(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, str(path), feature_version=(3, 9))
    if "from __future__ import annotations" in source:
        return
    # "int | None" parses on 3.9 but fails there when the annotation is
    # evaluated, which happens when the function is defined
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
            every += [a for a in (arguments.vararg, arguments.kwarg) if a]
            annotations = [a.annotation for a in every if a.annotation]
            if node.returns:
                annotations.append(node.returns)
        for annotation in annotations:
            for part in ast.walk(annotation):
                assert not (
                    isinstance(part, ast.BinOp) and isinstance(part.op, ast.BitOr)
                ), "%s:%d uses X | Y in an annotation" % (path.name, node.lineno)


def test_every_module_compiles(tmp_path):
    for path in _python_files():
        py_compile.compile(str(path), cfile=str(tmp_path / "x.pyc"), doraise=True)
