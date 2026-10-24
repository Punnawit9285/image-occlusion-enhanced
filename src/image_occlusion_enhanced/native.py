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
Conversion between this add-on's mask files and the occlusions of the Image
Occlusion built into Anki 23.10 and later.

Anki keeps every shape of a built-in occlusion note in the note's Occlusion
field, written as a cloze:

    {{c1::image-occlusion:rect:left=.1:top=.2:width=.3:height=.4:oi=1}}

Positions and sizes are fractions of the image's width and height. Shapes
that share a cloze number make up one card. Text shapes carry number 0 and
are labels shown on every card. "oi=1" (occlude inactive) on every shape is
what makes a note Hide All, Guess One rather than Hide One, Guess One.

Plain Python without Anki imports, so that it can be unit tested.
"""

import math
import re
from collections import Counter, OrderedDict
from typing import Dict, List, Optional, Sequence, Set, Tuple
from xml.dom import minidom

from . import geometry
from .geometry import Matrix, Point
from .masks import (
    HIDE_ALL_GUESS_ALL,
    HIDE_ALL_GUESS_ONE,
    HIDE_ONE_GUESS_ONE,
    LEGACY_HIDE_ALL_REVEAL_ALL,
    NOTE_ID_RE,
    WHOLE_IMAGE_NOTE_NR,
    layer_nodes,
)

# Defaults of Anki's own occlusion editor and reviewer
NATIVE_FILL = "#ffeba2"
NATIVE_TEXT_FILL = "#000000"
NATIVE_FONT_SIZE = 40  # pixels, used when a text shape has no "fs"
# Anki stores rotations in ten-thousandths of a full turn
_ANGLE_UNITS = 10000

# Freehand outlines can have thousands of points. Anything within half a
# pixel of the simplified outline is dropped, and no polygon keeps more than
# this many points, which keeps the Occlusion field a sensible size.
_SIMPLIFY_TOLERANCE = 0.5
_MAX_POLYGON_POINTS = 120

_ZERO_WIDTH_SPACE = "​"  # how the mask editor fills empty label lines
_LINE_HEIGHT = 1.2  # em; the mask editor's spacing of label lines
_ASCENT = 0.9  # em; baseline below the top of a line of Arial

SVG_NS = "http://www.w3.org/2000/svg"

_CLOZE_RE = re.compile(
    r"\{\{c(\d+)::image-occlusion:(rect|ellipse|polygon|text)"
    r"((?:\\.|[^\\}]|\}(?!\}))*)\}\}",
    re.S,
)
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class Shape:
    """One shape of a built-in occlusion note"""

    def __init__(self, kind: str, ordinal: int, props: Optional[Dict[str, str]] = None):
        self.kind = kind  # "rect", "ellipse", "polygon" or "text"
        self.ordinal = ordinal
        self.props: Dict[str, str] = OrderedDict(props or {})

    def number(self, name: str, default: float = 0.0) -> float:
        try:
            value = float(self.props.get(name, ""))
        except ValueError:
            return default
        return value if math.isfinite(value) else default

    def __repr__(self) -> str:
        return "Shape(%r, %r, %r)" % (self.kind, self.ordinal, dict(self.props))


# Occlusion field text ----------------------------------------------------------


def format_number(value: float) -> str:
    """Write a number the way Anki's occlusion editor does (".25", "1.")."""
    if not math.isfinite(value) or round(value, 4) == 0:
        return ".0000"
    return re.sub(r"^0+|0+$", "", "%.4f" % value)


def _escape(value: str) -> str:
    # A "}}" would end the cloze early; Anki's own editor does not guard
    # against that.
    value = value.replace("}}", "} }")
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _split_properties(body: str) -> List[str]:
    """Split ":a=1:b=x\\:y" on the colons that are not escaped."""
    parts, current, escaped = [], [], False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def parse_occlusions(text: str) -> List[Shape]:
    shapes = []
    for match in _CLOZE_RE.finditer(text or ""):
        props: Dict[str, str] = OrderedDict()
        for part in _split_properties(match.group(3)):
            if "=" in part:
                name, value = part.split("=", 1)
                props[name] = value
        shapes.append(Shape(match.group(2), int(match.group(1)), props))
    return shapes


def format_shape(shape: Shape) -> str:
    props = "".join(
        ":%s=%s" % (name, _escape(value)) for name, value in shape.props.items()
    )
    return "{{c%d::image-occlusion:%s%s}}" % (shape.ordinal, shape.kind, props)


def format_occlusions(shapes: Sequence[Shape]) -> str:
    # Anki's editor puts a line break after every shape
    return "".join(format_shape(shape) + "<br>" for shape in shapes)


def angle_to_native(degrees: float) -> str:
    return str(round((degrees % 360) / 360 * _ANGLE_UNITS))


def angle_from_native(value: str) -> float:
    try:
        return (float(value) % _ANGLE_UNITS) / _ANGLE_UNITS * 360
    except ValueError:
        return 0.0


# Reading mask files --------------------------------------------------------------


def _length(value: str) -> Optional[float]:
    """An SVG length in pixels ("800", "800px", "10cm")"""
    match = re.match(
        r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)\s*$", value or ""
    )
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2)
    factors = {
        "": 1,
        "px": 1,
        "pt": 1.25,
        "pc": 15,
        "mm": 3.543307,
        "cm": 35.43307,
        "in": 90,
    }
    if unit not in factors:
        return None
    return number * factors[unit]


def canvas_of(svg_node) -> Tuple[float, float, Matrix]:
    """Width and height of a mask file, and the transform from its user
    coordinates to those pixels (only not the identity with a viewBox)."""
    width = _length(svg_node.getAttribute("width"))
    height = _length(svg_node.getAttribute("height"))
    view_box = [
        float(n)
        for n in re.findall(
            r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",
            svg_node.getAttribute("viewBox"),
        )
    ]
    matrix = geometry.IDENTITY
    if len(view_box) == 4 and view_box[2] > 0 and view_box[3] > 0:
        min_x, min_y, vb_width, vb_height = view_box
        width = width or vb_width
        height = height or vb_height
        matrix = (
            width / vb_width,
            0.0,
            0.0,
            height / vb_height,
            -min_x * width / vb_width,
            -min_y * height / vb_height,
        )
    if not width or not height:
        raise ValueError("the mask file has no size")
    return width, height, matrix


def _style_value(node, name: str) -> Optional[str]:
    """A presentation attribute, also when it is given in a style attribute"""
    style = node.getAttribute("style") if node.hasAttribute("style") else ""
    for declaration in style.split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            if key.strip() == name:
                return value.strip()
    if node.hasAttribute(name):
        return node.getAttribute(name)
    return None


def _hex_color(value: Optional[str]) -> Optional[str]:
    if not value or not _COLOR_RE.match(value.strip()):
        return None
    value = value.strip().lower()
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    return value


def _float_attr(node, name: str, default: float = 0.0) -> float:
    value = _length(node.getAttribute(name)) if node.hasAttribute(name) else None
    return default if value is None else value


def _elements(node) -> list:
    return [child for child in node.childNodes if child.nodeType == child.ELEMENT_NODE]


def _text_lines(node) -> List[str]:
    tspans = node.getElementsByTagName("tspan")
    if tspans:
        lines = [
            "".join(t.data for t in tspan.childNodes if t.nodeType == t.TEXT_NODE)
            for tspan in tspans
        ]
    else:
        lines = ["".join(t.data for t in node.childNodes if t.nodeType == t.TEXT_NODE)]
    return [line.replace(_ZERO_WIDTH_SPACE, "") for line in lines]


def _text_box(node) -> Tuple[float, float, float, float, float, List[str]]:
    """Estimated (left, top, width, height, font size, lines) of a label,
    in the label's own coordinates. Fonts are not available here, so the
    width is a typical average for proportional fonts."""
    lines = _text_lines(node)
    font_size = _length(_style_value(node, "font-size") or "") or 16.0
    x = _float_attr(node, "x")
    y = _float_attr(node, "y")
    tspans = node.getElementsByTagName("tspan")
    if tspans and tspans[0].hasAttribute("x"):
        x = _float_attr(tspans[0], "x", x)
    width = max((len(line) for line in lines), default=0) * font_size * 0.55
    height = font_size * (1 + _LINE_HEIGHT * (len(lines) - 1))
    anchor = _style_value(node, "text-anchor") or "start"
    left = x - width / 2 if anchor == "middle" else x - width if anchor == "end" else x
    return left, y - font_size * _ASCENT, width, height, font_size, lines


class ToNative:
    """A mask file converted to the built-in format"""

    def __init__(self):
        self.shapes: List[Shape] = []
        # mask ID -> cloze number of the card asking about it
        self.ordinals: Dict[str, int] = OrderedDict()
        # SVG of what the built-in format cannot hold (arrows, lines...):
        # the caller paints this onto a copy of the image, if anything
        self.annotations: Optional[str] = None
        # what had to be left out, by description
        self.left_out: Counter = Counter()

    @property
    def occlusions(self) -> str:
        return format_occlusions(self.shapes)


class _Converter:
    def __init__(self, svg_node, width: float, height: float):
        self.svg_node = svg_node
        self.width = width
        self.height = height

    def _norm(self, point: Point) -> Point:
        return (point[0] / self.width, point[1] / self.height)

    def _polygon(self, points: Sequence[Point]) -> Optional[Tuple[str, Dict[str, str]]]:
        points = list(points)
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        points = geometry.simplify_to(points, _SIMPLIFY_TOLERANCE, _MAX_POLYGON_POINTS)
        if len(points) < 3:
            return None
        min_x, min_y, max_x, max_y = geometry.bounds(points)
        if max_x - min_x < 1e-6 or max_y - min_y < 1e-6:
            return None
        norm = [self._norm(p) for p in points]
        left, top = self._norm((min_x, min_y))
        return (
            "polygon",
            OrderedDict(
                [
                    ("left", format_number(left)),
                    ("top", format_number(top)),
                    (
                        "points",
                        " ".join(
                            "%s,%s" % (format_number(x), format_number(y))
                            for x, y in norm
                        ),
                    ),
                ]
            ),
        )

    def occluders(
        self, node, matrix: Matrix
    ) -> Optional[List[Tuple[str, Dict[str, str], Optional[str]]]]:
        """(kind, properties, fill) of the shapes one mask element is made of,
        or None if the element cannot be converted."""
        matrix = geometry.multiply(
            matrix, geometry.parse_transform(node.getAttribute("transform"))
        )
        fill = _hex_color(_style_value(node, "fill"))
        name = node.nodeName
        shapes: List[Tuple[str, Dict[str, str], Optional[str]]] = []
        if name == "g":
            for child in _elements(node):
                if child.nodeName in ("title", "desc"):
                    continue
                inner = self.occluders(child, matrix)
                if inner is None:
                    return None
                # a group's fill is inherited by children without their own
                shapes.extend((kind, props, own or fill) for kind, props, own in inner)
            return shapes
        if name == "rect":
            x, y = _float_attr(node, "x"), _float_attr(node, "y")
            w, h = _float_attr(node, "width"), _float_attr(node, "height")
            if w <= 0 or h <= 0:
                return []
            corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            points = [geometry.apply(matrix, c) for c in corners]
            if geometry.is_axis_aligned(matrix):
                min_x, min_y, max_x, max_y = geometry.bounds(points)
                left, top = self._norm((min_x, min_y))
                right, bottom = self._norm((max_x, max_y))
                props = OrderedDict(
                    [
                        ("left", format_number(left)),
                        ("top", format_number(top)),
                        ("width", format_number(right - left)),
                        ("height", format_number(bottom - top)),
                    ]
                )
                return [("rect", props, fill)]
            polygon = self._polygon(points)
            return [(polygon[0], polygon[1], fill)] if polygon else []
        if name in ("ellipse", "circle"):
            cx, cy = _float_attr(node, "cx"), _float_attr(node, "cy")
            if name == "circle":
                rx = ry = _float_attr(node, "r")
            else:
                rx, ry = _float_attr(node, "rx"), _float_attr(node, "ry")
            if rx <= 0 or ry <= 0:
                return []
            if geometry.is_axis_aligned(matrix):
                center = geometry.apply(matrix, (cx, cy))
                rx, ry = abs(matrix[0]) * rx, abs(matrix[3]) * ry
                left, top = self._norm((center[0] - rx, center[1] - ry))
                nrx, nry = self._norm((rx, ry))
                props = OrderedDict(
                    [
                        ("left", format_number(left)),
                        ("top", format_number(top)),
                        ("rx", format_number(nrx)),
                        ("ry", format_number(nry)),
                    ]
                )
                return [("ellipse", props, fill)]
            points = [
                geometry.apply(matrix, p)
                for p in geometry.ellipse_points(cx, cy, rx, ry)
            ]
            polygon = self._polygon(points)
            return [(polygon[0], polygon[1], fill)] if polygon else []
        if name in ("polygon", "polyline"):
            points = [
                geometry.apply(matrix, p)
                for p in geometry.parse_points(node.getAttribute("points"))
            ]
            polygon = self._polygon(points)
            return [(polygon[0], polygon[1], fill)] if polygon else []
        if name == "path":
            for subpath in geometry.flatten_path(node.getAttribute("d")):
                polygon = self._polygon([geometry.apply(matrix, p) for p in subpath])
                if polygon:
                    shapes.append((polygon[0], polygon[1], fill))
            return shapes
        if name == "line":
            x1, y1 = _float_attr(node, "x1"), _float_attr(node, "y1")
            x2, y2 = _float_attr(node, "x2"), _float_attr(node, "y2")
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 1e-6:
                return []
            half = (
                max(_length(_style_value(node, "stroke-width") or "") or 1.0, 1.0) / 2
            )
            nx, ny = -(y2 - y1) / length * half, (x2 - x1) / length * half
            corners = [
                (x1 + nx, y1 + ny),
                (x2 + nx, y2 + ny),
                (x2 - nx, y2 - ny),
                (x1 - nx, y1 - ny),
            ]
            polygon = self._polygon([geometry.apply(matrix, c) for c in corners])
            stroke = _hex_color(_style_value(node, "stroke"))
            return [(polygon[0], polygon[1], stroke or fill)] if polygon else []
        if name == "text":
            # Text that was once a card of its own, from before labels existed:
            # it becomes a box over where the text is drawn.
            left, top, w, h, _size, lines = _text_box(node)
            if not any(lines) or w <= 0:
                return []
            corners = [
                (left, top),
                (left + w, top),
                (left + w, top + h),
                (left, top + h),
            ]
            polygon = self._polygon([geometry.apply(matrix, c) for c in corners])
            return [(polygon[0], polygon[1], fill)] if polygon else []
        return None

    def label(self, node, matrix: Matrix) -> Optional[Shape]:
        matrix = geometry.multiply(
            matrix, geometry.parse_transform(node.getAttribute("transform"))
        )
        left, top, _w, _h, font_size, lines = _text_box(node)
        text = "\n".join(lines).strip("\n")
        if not text.strip():
            return None
        x, y = geometry.apply(matrix, (left, top))
        scale = math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2])) or 1.0
        angle = math.degrees(math.atan2(matrix[1], matrix[0]))
        nx, ny = self._norm((x, y))
        props: Dict[str, str] = OrderedDict(
            [("left", format_number(nx)), ("top", format_number(ny))]
        )
        if abs(angle) > 0.01:
            props["angle"] = angle_to_native(angle)
        props["text"] = text
        props["scale"] = "1"
        props["fs"] = format_number(font_size * scale / self.height)
        fill = _hex_color(_style_value(node, "fill"))
        if fill and fill != NATIVE_TEXT_FILL:
            props["fill"] = fill
        return Shape("text", 0, props)


_SKIPPED_NODES = ("title", "desc", "metadata", "defs")


def svg_to_native(svg: str, mode: str, card_ids: Optional[Set[str]] = None) -> ToNative:
    """Convert a mask file (the "Original Mask" of a note).

    mode is the occlusion mode of the notes. card_ids are the IDs of the masks
    that still have a note; any other mask is left out, since its card was
    deleted. Hide All, Guess All has a single card for all masks, so
    card_ids does not apply to it.
    """
    try:
        svg_node = minidom.parseString(svg.encode("utf-8")).documentElement
        layers = layer_nodes(svg_node)
    except Exception as e:
        raise ValueError("not a valid mask file (%s)" % e)
    width, height, base = canvas_of(svg_node)
    converter = _Converter(svg_node, width, height)
    result = ToNative()
    mask_layer = layers[-1]
    mask_matrix = geometry.multiply(
        base, geometry.parse_transform(mask_layer.getAttribute("transform"))
    )
    occlude_inactive = mode in (
        HIDE_ALL_GUESS_ONE,
        LEGACY_HIDE_ALL_REVEAL_ALL,
        HIDE_ALL_GUESS_ALL,
    )

    labels: List[Tuple[object, Matrix]] = []
    masks: List[Tuple[int, str, object]] = []
    for node in _elements(mask_layer):
        if node.nodeName in _SKIPPED_NODES:
            continue
        mask_id = node.getAttribute("id") if node.hasAttribute("id") else ""
        match = NOTE_ID_RE.match(mask_id)
        if node.nodeName == "text" and not (
            match and (card_ids is None or mask_id in card_ids)
        ):
            labels.append((node, mask_matrix))
            continue
        if mode == HIDE_ALL_GUESS_ALL:
            masks.append((len(masks), mask_id, node))
        elif match and (card_ids is None or mask_id in card_ids):
            masks.append((int(match.group("nr")), mask_id, node))
        else:
            result.left_out["masks whose card was deleted"] += 1

    masks.sort(key=lambda entry: entry[0])
    for position, (_nr, mask_id, node) in enumerate(masks):
        ordinal = 1 if mode == HIDE_ALL_GUESS_ALL else position + 1
        occluders = converter.occluders(node, mask_matrix)
        if occluders is None:
            result.left_out[
                "masks of a kind the built-in format cannot show (%s)" % node.nodeName
            ] += 1
            continue
        if not occluders:
            result.left_out["empty masks"] += 1
            continue
        if mode != HIDE_ALL_GUESS_ALL:
            result.ordinals[mask_id] = ordinal
        for kind, props, fill in occluders:
            if fill and fill != NATIVE_FILL:
                props["fill"] = fill
            if occlude_inactive:
                props["oi"] = "1"
            result.shapes.append(Shape(kind, ordinal, props))

    # Everything below the mask layer is drawn on every card. Text becomes
    # text shapes, which can still be edited; anything else is handed back to
    # be painted onto the image.
    annotations = svg_node.cloneNode(False)
    drawn = False
    for node in _elements(svg_node):
        if node.nodeName == "defs":
            annotations.appendChild(node.cloneNode(True))
    for layer in layers[:-1]:
        if layer.nodeName in _SKIPPED_NODES:
            continue
        layer_matrix = geometry.multiply(
            base, geometry.parse_transform(layer.getAttribute("transform"))
        )
        copy = layer.cloneNode(True)
        if layer.nodeName == "text":
            labels.append((layer, base))
            continue
        if layer.nodeName == "g":
            for child, original in zip(_elements(copy), _elements(layer)):
                if original.nodeName == "text":
                    labels.append((original, layer_matrix))
                    copy.removeChild(child)
                elif original.nodeName not in _SKIPPED_NODES:
                    drawn = True
        else:
            drawn = True
        annotations.appendChild(copy)
    if drawn:
        result.annotations = annotations.toxml()

    for node, matrix in labels:
        shape = converter.label(node, matrix)
        if shape:
            result.shapes.append(shape)
    return result


# Writing mask files --------------------------------------------------------------


def _fmt_px(value: float) -> str:
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


class FromNative:
    """A built-in occlusion note converted to a mask file"""

    def __init__(self, svg: str, mode: str, note_ids: Dict[int, str], mask_count: int):
        self.svg = svg
        self.mode = mode
        # cloze number -> ID of the note that takes over that card
        self.note_ids = note_ids
        self.mask_count = mask_count


def _mode_of(occluders: Sequence[Shape], ordinals: Sequence[int]) -> str:
    if len(ordinals) == 1 and len(occluders) > 1:
        # one card for all shapes
        return HIDE_ALL_GUESS_ALL
    hide_all = sum(1 for shape in occluders if shape.props.get("oi") == "1")
    return HIDE_ALL_GUESS_ONE if hide_all * 2 >= len(occluders) else HIDE_ONE_GUESS_ONE


def native_to_svg(
    occlusions: str,
    width: float,
    height: float,
    uniq_id: str,
    fill: str = "#FFEBA2",
    stroke: str = "#2D2D2D",
    stroke_width: float = 3,
    font_family: str = "Arial",
) -> FromNative:
    """Convert the Occlusion field of a built-in note into a mask file for an
    image of the given size. Notes get IDs starting with uniq_id."""
    shapes = parse_occlusions(occlusions)
    occluders = [s for s in shapes if s.kind != "text" and s.ordinal > 0]
    if not occluders:
        raise ValueError("the note has no shapes")
    ordinals = sorted({s.ordinal for s in occluders})
    mode = _mode_of(occluders, ordinals)
    occl_id = "%s-%s" % (uniq_id, mode)

    doc = minidom.getDOMImplementation().createDocument(SVG_NS, "svg", None)
    root = doc.documentElement
    root.setAttribute("xmlns", SVG_NS)
    root.setAttribute("width", _fmt_px(width))
    root.setAttribute("height", _fmt_px(height))
    root.appendChild(doc.createComment(" Created with Image Occlusion Enhanced "))

    def layer(title: str):
        group = doc.createElement("g")
        heading = doc.createElement("title")
        heading.appendChild(doc.createTextNode(title))
        group.appendChild(heading)
        root.appendChild(group)
        return group

    labels_layer = layer("Labels")
    masks_layer = layer("Masks")

    def px(x: float, y: float) -> Point:
        return (x * width, y * height)

    def element(shape: Shape):
        left, top = px(shape.number("left"), shape.number("top"))
        angle = angle_from_native(shape.props.get("angle", "0"))
        if shape.kind == "rect":
            node = doc.createElement("rect")
            w, h = px(shape.number("width"), shape.number("height"))
            for name, value in (("x", left), ("y", top), ("width", w), ("height", h)):
                node.setAttribute(name, _fmt_px(value))
        elif shape.kind == "ellipse":
            node = doc.createElement("ellipse")
            rx, ry = px(shape.number("rx"), shape.number("ry"))
            for name, value in (
                ("cx", left + rx),
                ("cy", top + ry),
                ("rx", rx),
                ("ry", ry),
            ):
                node.setAttribute(name, _fmt_px(value))
        else:
            node = doc.createElement("polygon")
            points = []
            for pair in shape.props.get("points", "").split():
                try:
                    x, y = (float(n) for n in pair.split(","))
                except ValueError:
                    continue
                points.append((x, y))
            if len(points) < 3:
                return None
            if "left" in shape.props or "top" in shape.props:
                # Anki draws a polygon with its bounding box at left/top
                min_x, min_y, _, _ = geometry.bounds(points)
                dx, dy = shape.number("left") - min_x, shape.number("top") - min_y
                points = [(x + dx, y + dy) for x, y in points]
            node.setAttribute(
                "points",
                " ".join(
                    "%s,%s" % tuple(_fmt_px(c) for c in px(x, y)) for x, y in points
                ),
            )
            angle = 0.0  # Anki does not rotate polygons
        if angle:
            node.setAttribute(
                "transform",
                "rotate(%s %s %s)" % (_fmt_px(angle), _fmt_px(left), _fmt_px(top)),
            )
        node.setAttribute("fill", _hex_color(shape.props.get("fill")) or fill)
        node.setAttribute("stroke", stroke)
        node.setAttribute("stroke-width", _fmt_px(stroke_width))
        return node

    note_ids: Dict[int, str] = OrderedDict()
    mask_count = 0
    if mode == HIDE_ALL_GUESS_ALL:
        note_ids[ordinals[0]] = "%s-%d" % (occl_id, WHOLE_IMAGE_NOTE_NR)
        for shape in occluders:
            node = element(shape)
            if node is not None:
                mask_count += 1
                node.setAttribute("id", "%s-%d" % (occl_id, mask_count))
                masks_layer.appendChild(node)
    else:
        for ordinal in ordinals:
            nodes = [element(s) for s in occluders if s.ordinal == ordinal]
            nodes = [n for n in nodes if n is not None]
            if not nodes:
                continue
            mask_count += 1
            note_id = "%s-%d" % (occl_id, mask_count)
            if len(nodes) == 1:
                mask = nodes[0]
            else:
                mask = doc.createElement("g")
                for node in nodes:
                    mask.appendChild(node)
            mask.setAttribute("id", note_id)
            masks_layer.appendChild(mask)
            note_ids[ordinal] = note_id

    for shape in shapes:
        if shape.kind != "text" or not shape.props.get("text", "").strip():
            continue
        size = shape.number("fs") * height if shape.number("fs") else NATIVE_FONT_SIZE
        size *= shape.number("scale", 1.0) or 1.0
        left, top = px(shape.number("left"), shape.number("top"))
        x, y = left, top + size * _ASCENT
        node = doc.createElement("text")
        node.setAttribute("x", _fmt_px(x))
        node.setAttribute("y", _fmt_px(y))
        node.setAttribute(
            "fill", _hex_color(shape.props.get("fill")) or NATIVE_TEXT_FILL
        )
        node.setAttribute("stroke", "none")
        node.setAttribute("stroke-width", "0")
        node.setAttribute("font-size", _fmt_px(size))
        node.setAttribute("font-family", font_family)
        node.setAttribute("text-anchor", "start")
        node.setAttribute("xml:space", "preserve")
        angle = angle_from_native(shape.props.get("angle", "0"))
        if angle:
            node.setAttribute(
                "transform",
                "rotate(%s %s %s)" % (_fmt_px(angle), _fmt_px(left), _fmt_px(top)),
            )
        lines = shape.props["text"].split("\n")
        if len(lines) == 1:
            node.appendChild(doc.createTextNode(lines[0]))
        else:
            for i, line in enumerate(lines):
                tspan = doc.createElement("tspan")
                tspan.setAttribute("x", _fmt_px(x))
                tspan.setAttribute("dy", "0" if i == 0 else "%sem" % _LINE_HEIGHT)
                tspan.appendChild(doc.createTextNode(line or _ZERO_WIDTH_SPACE))
                node.appendChild(tspan)
        labels_layer.appendChild(node)

    if not mask_count:
        raise ValueError("the note has no shapes that could be converted")
    return FromNative(root.toxml(), mode, note_ids, mask_count)
