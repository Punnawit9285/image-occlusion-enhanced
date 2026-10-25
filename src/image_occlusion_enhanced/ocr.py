# -*- coding: utf-8 -*-

# Image Occlusion Enhanced Add-on for Anki
#
# Copyright (C) 2026  Punnawit9285 <https://github.com/Punnawit9285>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version, with the additions
# listed at the end of the license file that accompanied this program.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# NOTE: This program is subject to certain additional terms pursuant to
# Section 7 of the GNU Affero General Public License.  You should have
# received a copy of these additional terms immediately following the
# terms and conditions of the GNU Affero General Public License that
# accompanied this program.

"""
Finds the text labels in an image, so that the mask editor can cover them.

Text recognition is left to whatever is available, in this order:

- Tesseract (https://tesseract-ocr.github.io), if it is installed or its
  location is set in the add-on's options. Runs on every system.
- On macOS, the system's own text recognition (Vision, macOS 10.15+).
- On Windows, the system's own text recognition (Windows 10+).

Words are then grouped into labels: words on a line that are close
together form one label, and so do lines stacked closely on top of each
other, as in a two-line label.

Plain Python without Anki imports, so that it can be unit tested.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, List, Optional, Sequence, Tuple

# Where installers put Tesseract. Anki started from the Dock or the Start
# menu often does not see the PATH a terminal would.
TESSERACT_LOCATIONS = (
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/local/bin/tesseract",
    "/usr/bin/tesseract",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

TIMEOUT = 120  # seconds

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


class OcrError(Exception):
    pass


class Word:
    """A recognized piece of text, in image pixels"""

    def __init__(
        self,
        text: str,
        left: float,
        top: float,
        width: float,
        height: float,
        line: object = None,
    ):
        self.text = text
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        # words that the engine put on the same line share this
        self.line = line

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def __repr__(self) -> str:
        return "Word(%r, %g, %g, %g, %g)" % (
            self.text,
            self.left,
            self.top,
            self.width,
            self.height,
        )


Box = Tuple[float, float, float, float]  # left, top, width, height


# Grouping ----------------------------------------------------------------------


def _meaningful(text: str) -> bool:
    return any(char.isalnum() for char in text)


def _split_line(words: List[Word]) -> List[List[Word]]:
    """Split a line where the gap between two words is much wider than a
    space, as between two labels that happen to share a line."""
    words = sorted(words, key=lambda w: w.left)
    groups = [[words[0]]]
    for previous, word in zip(words, words[1:]):
        height = max(previous.height, word.height)
        if word.left - previous.right > 1.2 * height:
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


def _bounds(words: Sequence[Word]) -> Word:
    left = min(w.left for w in words)
    top = min(w.top for w in words)
    right = max(w.right for w in words)
    bottom = max(w.bottom for w in words)
    return Word(" ".join(w.text for w in words), left, top, right - left, bottom - top)


def _stacked(upper: Word, lower: Word) -> bool:
    """Whether lower continues the label upper starts on the next line"""
    height = min(upper.height, lower.height)
    gap = lower.top - upper.bottom
    if gap < -0.3 * height or gap > 0.6 * height:
        return False
    overlap = min(upper.right, lower.right) - max(upper.left, lower.left)
    return overlap > 0.4 * min(upper.width, lower.width)


def group_labels(
    words: Sequence[Word], image_width: float, image_height: float
) -> List[Box]:
    """Boxes to cover the labels made up of the given words"""
    words = [w for w in words if _meaningful(w.text) and w.width > 0 and w.height > 0]
    lines = {}
    for index, word in enumerate(words):
        lines.setdefault(
            word.line if word.line is not None else ("word", index), []
        ).append(word)
    pieces = []
    for line_words in lines.values():
        pieces.extend(_bounds(group) for group in _split_line(line_words))

    # merge multi-line labels, top to bottom
    pieces.sort(key=lambda p: (p.top, p.left))
    labels: List[Word] = []
    for piece in pieces:
        for i, label in enumerate(labels):
            last_line = label.line or label
            if _stacked(last_line, piece):
                merged = _bounds([label, piece])
                merged.line = piece  # the lowest line, for the next comparison
                labels[i] = merged
                break
        else:
            piece.line = None
            labels.append(piece)

    boxes = []
    for label in labels:
        pad = max(3.0, 0.2 * min(label.height, 40))
        left = max(0.0, label.left - pad)
        top = max(0.0, label.top - pad)
        right = min(float(image_width), label.right + pad)
        bottom = min(float(image_height), label.bottom + pad)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            continue
        if width * height > 0.4 * image_width * image_height:
            continue  # a page of text, not a label
        boxes.append((round(left, 1), round(top, 1), round(width, 1), round(height, 1)))
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes


# Tesseract ---------------------------------------------------------------------


def find_tesseract(configured: str = "") -> Optional[str]:
    if configured:
        return configured if os.path.isfile(configured) else None
    found = shutil.which("tesseract")
    if found:
        return found
    for location in TESSERACT_LOCATIONS:
        if os.path.isfile(location):
            return location
    return None


def parse_tesseract_tsv(tsv: str, min_confidence: float = 40) -> List[Word]:
    words = []
    lines = tsv.splitlines()
    if not lines:
        return words
    header = lines[0].split("\t")
    try:
        col = {
            name: header.index(name)
            for name in (
                "level",
                "block_num",
                "par_num",
                "line_num",
                "left",
                "top",
                "width",
                "height",
                "conf",
                "text",
            )
        }
    except ValueError:
        raise OcrError("Tesseract gave output in an unexpected format")
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) <= col["text"] or cells[col["level"]] != "5":
            continue
        text = cells[col["text"]].strip()
        try:
            confidence = float(cells[col["conf"]])
        except ValueError:
            continue
        if not text or confidence < min_confidence:
            continue
        words.append(
            Word(
                text,
                float(cells[col["left"]]),
                float(cells[col["top"]]),
                float(cells[col["width"]]),
                float(cells[col["height"]]),
                (
                    cells[col["block_num"]],
                    cells[col["par_num"]],
                    cells[col["line_num"]],
                ),
            )
        )
    return words


def _run(command: List[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=TIMEOUT,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise OcrError("Text recognition took longer than %d seconds." % TIMEOUT)
    except OSError as e:
        raise OcrError(str(e))
    output = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0:
        detail = (
            result.stderr.decode("utf-8", errors="replace").strip() or output.strip()
        )
        raise OcrError(
            detail.splitlines()[-1] if detail else "exit code %d" % result.returncode
        )
    return output


def tesseract_words(
    executable: str, image_path: str, languages: str = ""
) -> List[Word]:
    # Sparse text mode finds text scattered over the image, as on a diagram,
    # rather than looking for paragraphs.
    command = [executable, image_path, "stdout", "--psm", "11"]
    if languages:
        command += ["-l", languages]
    return parse_tesseract_tsv(_run(command + ["tsv"]))


# macOS --------------------------------------------------------------------------

_VISION_SCRIPT = r"""
ObjC.import("Foundation");
ObjC.import("Vision");
function run(argv) {
  var url = $.NSURL.fileURLWithPath(argv[0]);
  var handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $({}));
  var request = $.VNRecognizeTextRequest.alloc.init;
  request.recognitionLevel = 0;  // accurate
  request.usesLanguageCorrection = false;
  try { request.automaticallyDetectsLanguage = true; } catch (e) {}
  var error = $();
  if (!handler.performRequestsError($([request]), error)) {
    throw new Error("Text recognition failed: " + ObjC.unwrap(error.localizedDescription));
  }
  var results = request.results;
  var out = [];
  for (var i = 0; i < results.count; i++) {
    var observation = results.objectAtIndex(i);
    var candidate = observation.topCandidates(1).firstObject;
    var box = observation.boundingBox;
    out.push([ObjC.unwrap(candidate.string), box.origin.x, box.origin.y,
              box.size.width, box.size.height]);
  }
  return JSON.stringify(out);
}
"""


def parse_vision_output(output: str, width: float, height: float) -> List[Word]:
    """Vision gives one box per line of text, as fractions of the image with
    the origin in the bottom left corner."""
    try:
        observations = json.loads(output.strip() or "[]")
    except ValueError:
        raise OcrError("macOS text recognition gave unexpected output")
    words = []
    for index, (text, x, y, w, h) in enumerate(observations):
        words.append(
            Word(
                text,
                x * width,
                (1 - y - h) * height,
                w * width,
                h * height,
                ("vision", index),
            )
        )
    return words


def vision_words(image_path: str, width: float, height: float) -> List[Word]:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as script:
        script.write(_VISION_SCRIPT)
    try:
        output = _run(
            ["/usr/bin/osascript", "-l", "JavaScript", script.name, image_path]
        )
    finally:
        os.unlink(script.name)
    return parse_vision_output(output, width, height)


# Windows ------------------------------------------------------------------------

_WINDOWS_SCRIPT = r"""
param([string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($operation, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'No text recognition language is installed in Windows.' }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lineNumber = 0
foreach ($line in $result.Lines) {
    foreach ($word in $line.Words) {
        $box = $word.BoundingRect
        [Console]::Out.WriteLine(("{0}`t{1}`t{2}`t{3}`t{4}`t{5}" -f $lineNumber, $box.X, $box.Y, $box.Width, $box.Height, $word.Text))
    }
    $lineNumber++
}
"""


def parse_windows_output(output: str) -> List[Word]:
    words = []
    for line in output.splitlines():
        cells = line.split("\t", 5)
        if len(cells) != 6:
            continue
        try:
            number = int(cells[0])
            left, top, width, height = (float(c.replace(",", ".")) for c in cells[1:5])
        except ValueError:
            continue
        words.append(Word(cells[5], left, top, width, height, ("windows", number)))
    return words


def windows_words(image_path: str) -> List[Word]:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ps1", delete=False, encoding="utf-8-sig"
    ) as script:
        script.write(_WINDOWS_SCRIPT)
    try:
        output = _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script.name,
                os.path.abspath(image_path),
            ]
        )
    finally:
        os.unlink(script.name)
    return parse_windows_output(output)


# Choosing an engine ---------------------------------------------------------------


class Engine:
    def __init__(
        self, name: str, find_words: Callable[[str, float, float], List[Word]]
    ):
        self.name = name
        self.find_words = find_words


def available_engine(tesseract: str = "", languages: str = "") -> Optional[Engine]:
    executable = find_tesseract(tesseract)
    if executable:
        return Engine(
            "Tesseract", lambda path, w, h: tesseract_words(executable, path, languages)
        )
    if sys.platform == "darwin" and os.path.exists("/usr/bin/osascript"):
        return Engine("macOS text recognition", vision_words)
    if sys.platform == "win32":
        return Engine(
            "Windows text recognition", lambda path, w, h: windows_words(path)
        )
    return None


def find_labels(
    engine: Engine, image_path: str, width: float, height: float, scale: float = 1.0
) -> List[Box]:
    """Boxes over the labels of an image, in the coordinates of an image of
    width x height. image_path may be a copy of the image enlarged by scale,
    which helps with small text."""
    words = engine.find_words(image_path, width * scale, height * scale)
    if scale != 1:
        for word in words:
            word.left /= scale
            word.top /= scale
            word.width /= scale
            word.height /= scale
    return group_labels(words, width, height)
