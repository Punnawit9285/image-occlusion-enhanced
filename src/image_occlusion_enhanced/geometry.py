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
Plane geometry for converting masks: SVG transforms, flattening path data
into polygons, and simplifying those polygons.

Plain Python without Anki imports, so that it can be unit tested.
"""

import math
import re
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]

# An affine transform as SVG writes it: matrix(a b c d e f) maps (x, y) to
# (a*x + c*y + e, b*x + d*y + f).
Matrix = Tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_EPSILON = 1e-9

_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBER_RE = re.compile(_NUMBER)
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")


def multiply(outer: Matrix, inner: Matrix) -> Matrix:
    """The transform that applies `inner` first and then `outer`."""
    a1, b1, c1, d1, e1, f1 = outer
    a2, b2, c2, d2, e2, f2 = inner
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def apply(matrix: Matrix, point: Point) -> Point:
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def translation(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def rotation(degrees: float, cx: float = 0.0, cy: float = 0.0) -> Matrix:
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    turn: Matrix = (cos, sin, -sin, cos, 0.0, 0.0)
    if not cx and not cy:
        return turn
    return multiply(translation(cx, cy), multiply(turn, translation(-cx, -cy)))


def parse_transform(value: Optional[str]) -> Matrix:
    """Parse an SVG transform attribute; anything unreadable is ignored."""
    matrix = IDENTITY
    for name, args in _TRANSFORM_RE.findall(value or ""):
        nums = [float(n) for n in _NUMBER_RE.findall(args)]
        step: Optional[Matrix] = None
        if name == "matrix" and len(nums) == 6:
            step = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif name == "translate" and nums:
            step = translation(nums[0], nums[1] if len(nums) > 1 else 0.0)
        elif name == "scale" and nums:
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            step = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate" and nums:
            if len(nums) >= 3:
                step = rotation(nums[0], nums[1], nums[2])
            else:
                step = rotation(nums[0])
        elif name == "skewX" and nums:
            step = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and nums:
            step = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0, 0.0, 0.0)
        if step is not None:
            matrix = multiply(matrix, step)
    return matrix


def is_axis_aligned(matrix: Matrix) -> bool:
    """Whether the transform keeps rectangles axis-aligned rectangles.

    True for any mix of translation and (possibly mirrored) scaling.
    """
    return abs(matrix[1]) < _EPSILON and abs(matrix[2]) < _EPSILON


def ellipse_points(
    cx: float, cy: float, rx: float, ry: float, segments: int = 48
) -> List[Point]:
    return [
        (
            cx + rx * math.cos(2 * math.pi * i / segments),
            cy + ry * math.sin(2 * math.pi * i / segments),
        )
        for i in range(segments)
    ]


def parse_points(value: Optional[str]) -> List[Point]:
    """Read the points attribute of a <polygon> or <polyline>."""
    nums = [float(n) for n in _NUMBER_RE.findall(value or "")]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def bounds(points: Sequence[Point]) -> Tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y)"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


# Path data -------------------------------------------------------------------

_PATH_TOKEN_RE = re.compile(r"([MmZzLlHhVvCcSsQqTtAa])|(%s)" % _NUMBER)
_FLAG_RE = re.compile(r"\s*,?\s*([01])")

# number of arguments each path command takes per repetition
_ARG_COUNTS = {
    "M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0,
}  # fmt: skip


class _PathReader:
    """Tokenizer for path data that also copes with packed arc flags.

    Arc flags are single digits that may be written without separators
    ("a5 5 0 01 10 10"), which a plain number pattern would read as "01".
    """

    def __init__(self, data: str):
        self.data = data
        self.pos = 0

    def _skip_separators(self) -> None:
        while self.pos < len(self.data) and self.data[self.pos] in " \t\r\n,":
            self.pos += 1

    def peek_command(self) -> Optional[str]:
        self._skip_separators()
        if self.pos < len(self.data) and self.data[self.pos].isalpha():
            return self.data[self.pos]
        return None

    def at_end(self) -> bool:
        self._skip_separators()
        return self.pos >= len(self.data)

    def command(self) -> str:
        self._skip_separators()
        char = self.data[self.pos]
        self.pos += 1
        return char

    def number(self) -> float:
        self._skip_separators()
        match = _NUMBER_RE.match(self.data, self.pos)
        if not match:
            raise ValueError("expected a number at %d in path data" % self.pos)
        self.pos = match.end()
        return float(match.group(0))

    def flag(self) -> float:
        match = _FLAG_RE.match(self.data, self.pos)
        if not match:
            raise ValueError("expected an arc flag at %d in path data" % self.pos)
        self.pos = match.end()
        return float(match.group(1))

    def has_number(self) -> bool:
        self._skip_separators()
        return bool(_NUMBER_RE.match(self.data, self.pos))


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int) -> List[Point]:
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0]
                + t * t * t * p3[0],
                u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1]
                + t * t * t * p3[1],
            )
        )  # fmt: skip
    return out


def _quadratic(p0: Point, p1: Point, p2: Point, steps: int) -> List[Point]:
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return out


def _arc(
    p0: Point,
    rx: float,
    ry: float,
    angle: float,
    large_arc: bool,
    sweep: bool,
    p1: Point,
    steps: int,
) -> List[Point]:
    """Points along an SVG elliptical arc (SVG 1.1, appendix F.6.5)."""
    if p0 == p1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx < _EPSILON or ry < _EPSILON:
        return [p1]
    phi = math.radians(angle % 360)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy
    # scale radii up if they cannot span the two end points
    scale = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if scale > 1:
        root = math.sqrt(scale)
        rx, ry = rx * root, ry * root
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (p0[0] + p1[0]) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (p0[1] + p1[1]) / 2

    def angle_of(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        length = math.hypot(ux, uy) * math.hypot(vx, vy)
        value = math.acos(max(-1.0, min(1.0, dot / length))) if length else 0.0
        return -value if ux * vy - uy * vx < 0 else value

    theta = angle_of(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle_of(
        (x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry
    )
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    count = max(steps, int(abs(delta) / (math.pi / 16)) + 1)
    out = []
    for i in range(1, count + 1):
        t = theta + delta * i / count
        out.append(
            (
                cx + rx * math.cos(t) * cos_phi - ry * math.sin(t) * sin_phi,
                cy + rx * math.cos(t) * sin_phi + ry * math.sin(t) * cos_phi,
            )
        )
    out[-1] = p1
    return out


def flatten_path(data: str, curve_steps: int = 16) -> List[List[Point]]:
    """Turn SVG path data into one list of points per subpath.

    Curves and arcs are approximated by straight segments. Malformed data
    ends the path at the last command that could be read, the way browsers
    render it.
    """
    reader = _PathReader(data or "")
    subpaths: List[List[Point]] = []
    current: List[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    last_control: Optional[Point] = None
    last_command = ""
    command = ""

    def finish() -> None:
        nonlocal current
        if len(current) > 1:
            subpaths.append(current)
        current = []

    try:
        while not reader.at_end():
            explicit = reader.peek_command()
            if explicit:
                command = reader.command()
            elif not command or command in "Zz":
                break
            upper = command.upper()
            relative = command != upper
            if upper == "Z":
                if current:
                    pos = start
                finish()
                last_control = None
                last_command = upper
                continue
            if not explicit and not reader.has_number():
                break
            ox, oy = pos if relative else (0.0, 0.0)
            if upper == "M":
                finish()
                pos = (ox + reader.number(), oy + reader.number())
                start = pos
                current = [pos]
                # further coordinate pairs are implicit line-tos
                command = "l" if relative else "L"
                last_control = None
            elif upper == "L":
                pos = (ox + reader.number(), oy + reader.number())
                current.append(pos)
                last_control = None
            elif upper == "H":
                pos = (ox + reader.number() if relative else reader.number(), pos[1])
                current.append(pos)
                last_control = None
            elif upper == "V":
                pos = (pos[0], oy + reader.number() if relative else reader.number())
                current.append(pos)
                last_control = None
            elif upper == "C":
                c1 = (ox + reader.number(), oy + reader.number())
                c2 = (ox + reader.number(), oy + reader.number())
                end = (ox + reader.number(), oy + reader.number())
                current.extend(_cubic(pos, c1, c2, end, curve_steps))
                last_control, pos = c2, end
            elif upper == "S":
                if last_control is not None and last_command in ("C", "S"):
                    c1 = (2 * pos[0] - last_control[0], 2 * pos[1] - last_control[1])
                else:
                    c1 = pos
                c2 = (ox + reader.number(), oy + reader.number())
                end = (ox + reader.number(), oy + reader.number())
                current.extend(_cubic(pos, c1, c2, end, curve_steps))
                last_control, pos = c2, end
            elif upper == "Q":
                c1 = (ox + reader.number(), oy + reader.number())
                end = (ox + reader.number(), oy + reader.number())
                current.extend(_quadratic(pos, c1, end, curve_steps))
                last_control, pos = c1, end
            elif upper == "T":
                if last_control is not None and last_command in ("Q", "T"):
                    c1 = (2 * pos[0] - last_control[0], 2 * pos[1] - last_control[1])
                else:
                    c1 = pos
                end = (ox + reader.number(), oy + reader.number())
                current.extend(_quadratic(pos, c1, end, curve_steps))
                last_control, pos = c1, end
            elif upper == "A":
                rx, ry, angle = reader.number(), reader.number(), reader.number()
                large_arc, sweep = reader.flag(), reader.flag()
                end = (ox + reader.number(), oy + reader.number())
                current.extend(
                    _arc(pos, rx, ry, angle, bool(large_arc), bool(sweep), end,
                         curve_steps)
                )  # fmt: skip
                last_control, pos = None, end
            else:
                break
            if not current:
                # drawing without a preceding moveto starts at the origin
                current = [(0.0, 0.0)]
            last_command = upper
    except (ValueError, IndexError):
        pass
    finish()
    return subpaths


# Simplification --------------------------------------------------------------


def _distance_to_segment(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    if length < _EPSILON:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def simplify(points: Sequence[Point], tolerance: float) -> List[Point]:
    """Ramer-Douglas-Peucker: drop points closer than `tolerance` to the
    outline that remains. Iterative, so long freehand strokes cannot exhaust
    the recursion limit."""
    points = list(points)
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        index, furthest = first, -1.0
        for i in range(first + 1, last):
            dist = _distance_to_segment(points[i], points[first], points[last])
            if dist > furthest:
                index, furthest = i, dist
        if furthest > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, kept in zip(points, keep) if kept]


def simplify_to(
    points: Sequence[Point], tolerance: float, max_points: int
) -> List[Point]:
    """Simplify, loosening the tolerance until at most max_points remain."""
    result = simplify(points, tolerance)
    while len(result) > max_points:
        tolerance *= 1.5
        result = simplify(points, tolerance)
    return result
