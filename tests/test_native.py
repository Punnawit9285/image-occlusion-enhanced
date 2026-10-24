import math
from xml.dom import minidom

import pytest

from conftest import DATA
from image_occlusion_enhanced import masks, native

SVG = (DATA / "sample-original-mask.svg").read_text()
UNIQ = "e7dd28558d524ad2a95558d2633ecd48"
IDS = ["%s-ao-%d" % (UNIQ, i) for i in range(1, 7)]


def by_ordinal(shapes):
    out = {}
    for s in shapes:
        out.setdefault(s.ordinal, []).append(s)
    return out


def test_format_number_matches_anki():
    assert native.format_number(0.1) == ".1"
    assert native.format_number(0.12345) == ".1235"
    assert native.format_number(1) == "1."
    assert native.format_number(0) == ".0000"
    assert native.format_number(0.00001) == ".0000"
    # like toFixed(4).replace(/^0+|0+$/g, ""), which leaves the zero after a sign
    assert native.format_number(-0.25) == "-0.25"


def test_parse_and_format_round_trip():
    text = (
        r"{{c1::image-occlusion:rect:left=.1:top=.2:width=.3:height=.4:oi=1}}<br>"
        r"{{c0::image-occlusion:text:left=.6:top=.6:text=a\:b } c \\ d:scale=1:fs=.05}}"
    )
    shapes = native.parse_occlusions(text)
    assert [(s.kind, s.ordinal) for s in shapes] == [("rect", 1), ("text", 0)]
    assert shapes[1].props["text"] == "a:b } c \\ d"
    assert (
        native.parse_occlusions(native.format_occlusions(shapes))[1].props
        == shapes[1].props
    )


def test_escape_closing_braces():
    shape = native.Shape("text", 0, {"text": "x}}y"})
    assert "}}" not in native.format_shape(shape)[:-2]


def test_angles_use_ten_thousandths_of_a_turn():
    assert native.angle_to_native(10) == "278"
    assert abs(native.angle_from_native("278") - 10.008) < 0.01


def test_sample_to_native():
    result = native.svg_to_native(SVG, "ao", set(IDS))
    assert list(result.ordinals.values()) == [1, 2, 3, 4, 5, 6]
    groups = by_ordinal(result.shapes)
    assert [s.kind for s in groups[1]] == ["rect"]
    assert [s.kind for s in groups[2]] == ["ellipse"]
    assert [s.kind for s in groups[3]] == ["polygon"]  # rotated rectangle
    assert [s.kind for s in groups[4]] == ["polygon"]  # path
    assert [s.kind for s in groups[5]] == ["polygon"]
    assert [s.kind for s in groups[6]] == ["rect", "rect"]  # group
    assert all(s.props.get("oi") == "1" for o in range(1, 7) for s in groups[o])
    # rect at x=30 y=280 120x40 in an 800x600 image
    rect = groups[1][0].props
    assert (rect["left"], rect["top"], rect["width"], rect["height"]) == (
        ".0375",
        ".4667",
        ".15",
        ".0667",
    )
    ellipse = groups[2][0].props
    assert (ellipse["left"], ellipse["top"], ellipse["rx"], ellipse["ry"]) == (
        ".8125",
        ".225",
        ".0688",
        ".0417",
    )
    # labels from both layers, the arrow-less line is left for the image
    texts = groups[0]
    assert sorted(s.props["text"] for s in texts) == ["Anterior: view", "Knee\njoint"]
    blue = [s for s in texts if s.props["text"] == "Anterior: view"][0]
    assert blue.props["fill"] == "#0000ff"
    assert (
        result.annotations
        and "<line" in result.annotations
        and "<text" not in result.annotations
    )
    assert not result.left_out


def test_rotated_rect_corners():
    result = native.svg_to_native(SVG, "ao", set(IDS))
    poly = [s for s in result.shapes if s.ordinal == 3][0]
    points = [
        tuple(float(c) for c in p.split(",")) for p in poly.props["points"].split()
    ]
    assert len(points) == 4
    # rotate(10 650 442.5) of the corner (550, 425)
    a = math.radians(10)
    x, y = 550 - 650, 425 - 442.5
    expected = (
        650 + x * math.cos(a) - y * math.sin(a),
        442.5 + x * math.sin(a) + y * math.cos(a),
    )
    assert abs(points[0][0] * 800 - expected[0]) < 0.1
    assert abs(points[0][1] * 600 - expected[1]) < 0.1
    left = float(poly.props["left"])
    assert abs(left - min(p[0] for p in points)) < 1e-4


def test_hide_one_guess_one_has_no_oi():
    ids = {i.replace("-ao-", "-oa-") for i in IDS}
    result = native.svg_to_native(SVG.replace("-ao-", "-oa-"), "oa", ids)
    assert all("oi" not in s.props for s in result.shapes)


def test_masks_without_cards_are_left_out():
    result = native.svg_to_native(SVG, "ao", set(IDS[:2]))
    assert list(result.ordinals.values()) == [1, 2]
    assert result.left_out["masks whose card was deleted"] == 4


def test_hide_all_guess_all_is_one_card():
    result = native.svg_to_native(SVG, "ag")
    assert {s.ordinal for s in result.shapes if s.kind != "text"} == {1}


def test_custom_fill_is_kept():
    svg = SVG.replace(
        'fill="#FFEBA2" id="%s"' % IDS[0], 'fill="#00FF00" id="%s"' % IDS[0]
    )
    result = native.svg_to_native(svg, "ao", set(IDS))
    assert by_ordinal(result.shapes)[1][0].props["fill"] == "#00ff00"
    assert "fill" not in by_ordinal(result.shapes)[2][0].props


def test_viewbox_is_honoured():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 20 10">'
        '<g><title>Masks</title><rect id="u-ao-1" x="2" y="1" width="4" height="2"/></g></svg>'
    )
    rect = native.svg_to_native(svg, "ao").shapes[0].props
    assert (rect["left"], rect["top"], rect["width"], rect["height"]) == (
        ".1",
        ".1",
        ".2",
        ".2",
    )


def test_not_a_mask_file():
    with pytest.raises(ValueError):
        native.svg_to_native("<html/>", "ao")


def test_native_to_svg_round_trip():
    there = native.svg_to_native(SVG, "ao", set(IDS))
    back = native.native_to_svg(there.occlusions, 800, 600, "f00")
    assert back.mode == "ao"
    assert list(back.note_ids.values()) == ["f00-ao-%d" % i for i in range(1, 7)]
    assert masks.mask_ids(back.svg) == list(back.note_ids.values())
    again = native.svg_to_native(back.svg, "ao")
    assert [(s.kind, s.ordinal) for s in again.shapes if s.kind != "text"] == [
        (s.kind, s.ordinal) for s in there.shapes if s.kind != "text"
    ]
    for a, b in zip(again.shapes, there.shapes):
        if a.kind in ("rect", "ellipse"):
            for key in ("left", "top"):
                assert abs(float(a.props[key]) - float(b.props[key])) < 1e-3
    doc = minidom.parseString(back.svg.encode())
    assert doc.getElementsByTagName("tspan").length == 2  # "Knee\njoint"


def test_native_modes():
    hide_one = "{{c1::image-occlusion:rect:left=.1:top=.1:width=.1:height=.1}}{{c2::image-occlusion:rect:left=.5:top=.1:width=.1:height=.1}}"
    assert native.native_to_svg(hide_one, 100, 100, "u").mode == "oa"
    one_card = "{{c1::image-occlusion:rect:left=.1:top=.1:width=.1:height=.1:oi=1}}{{c1::image-occlusion:ellipse:left=.5:top=.1:rx=.1:ry=.1:oi=1}}"
    result = native.native_to_svg(one_card, 100, 100, "u")
    assert result.mode == "ag"
    assert result.note_ids == {1: "u-ag-0"}
    assert masks.mask_ids(result.svg) == ["u-ag-1", "u-ag-2"]


def test_native_polygon_offset_and_rotation():
    text = (
        "{{c1::image-occlusion:polygon:left=.5:top=.5:points=.1,.1 .2,.1 .1,.2:oi=1}}"
        "{{c2::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:angle=2500:oi=1}}"
    )
    svg = native.native_to_svg(text, 100, 100, "u").svg
    doc = minidom.parseString(svg.encode())
    polygon = doc.getElementsByTagName("polygon")[0]
    assert polygon.getAttribute("points") == "50,50 60,50 50,60"
    rect = doc.getElementsByTagName("rect")[0]
    assert rect.getAttribute("transform") == "rotate(90 10 10)"


def test_native_without_shapes():
    with pytest.raises(ValueError):
        native.native_to_svg(
            "{{c0::image-occlusion:text:left=.1:top=.1:text=hi}}", 10, 10, "u"
        )
